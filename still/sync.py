"""Background IBKR retrieval, report import and the daily schedule.

One worker runs at a time. Every report, fetched or uploaded, goes through the
same pipeline: validate, parse, check it joins the stored history without a
gap, store it encrypted, rebuild the portfolio view and reconcile.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from threading import Event, RLock, Thread
from typing import Callable

from ibkr.flex import MAX_RANGE_DAYS, FlexClient, FlexError, FlexServiceError, single_worker, validate_report
from ibkr.ledger import LedgerError, merge, parse_ledger

from . import portfolio
from .auth import Auth
from .store import Store

ATTENTION = {"1012": "token_expired", "1013": "ip_restricted", "1015": "token_invalid", "1014": "query_invalid",
             "1011": "account_inactive", "1025": "too_many_failures", "1010": "legacy_query"}


class SyncError(Exception):
    """Safe to display."""


def history_ranges(start: date, end: date) -> list[tuple[str, str]]:
    """Split [start, end] into consecutive ranges IBKR accepts (at most MAX_RANGE_DAYS each)."""
    if start > end:
        raise SyncError("Choose a start date before today.")
    ranges = []
    while start <= end:
        stop = min(end, start + timedelta(days=MAX_RANGE_DAYS - 1))
        ranges.append((start.strftime("%Y%m%d"), stop.strftime("%Y%m%d")))
        start = stop + timedelta(days=1)
    return ranges


class Sync:
    def __init__(self, store: Store, auth: Auth, *, client_factory: Callable[[str, str], FlexClient] = FlexClient,
                 today: Callable[[], date] = date.today, now: Callable[[], datetime] = datetime.now):
        self.store, self.auth = store, auth
        self.client_factory, self.today, self.now = client_factory, today, now
        self.lock = RLock()
        self.job: dict | None = None
        self.thread: Thread | None = None
        self.view: dict | None = None
        self.ledger = None
        self.view_error: str | None = None
        self.stopping = Event()

    # Portfolio view ---------------------------------------------------------
    def rebuild(self) -> None:
        key = self.auth.key
        with self.lock:
            if key is None:
                self.view, self.view_error, self.ledger = None, None, None
                return
            try:
                reports = self.store.report_data(key)
                self.view = portfolio.build(reports, from_inception=bool(self.store.setting("fromInception")))
                # The merged ledger also feeds the price history, which rebuilds daily holdings from trades.
                self.ledger = merge(*(parse_ledger(r) for r in reports)) if reports else None
                self.view_error = None
            except (FlexError, portfolio.PortfolioError) as error:
                self.view, self.view_error, self.ledger = None, str(error), None

    # Import pipeline --------------------------------------------------------
    def import_report(self, data: bytes, source: str) -> dict:
        key = self.auth.key
        if key is None:
            raise SyncError("Unlock Still first.")
        try:
            validate_report(data)
            ledger = parse_ledger(data)
            existing = [parse_ledger(d) for d in self.store.report_data(key)]
            merge(*existing, ledger)  # Refuses gaps and conflicting transaction IDs before anything is stored.
        except FlexError as error:
            raise SyncError(str(error)) from None
        starts = min(s.from_date for s in ledger.statements).isoformat()
        ends = max(s.to_date for s in ledger.statements).isoformat()
        stored = self.store.add_report(key, data, source, starts, ends) is not None
        self.rebuild()
        return {"stored": stored, "fromDate": starts, "toDate": ends, **ledger.summary()}

    def upload(self, data: bytes) -> dict:
        run = self.store.start_run("upload")
        try:
            result = self.import_report(data, "upload")
        except SyncError as error:
            self.store.finish_run(run, "failed", str(error))
            raise
        message = "Report imported." if result["stored"] else "This report was already imported."
        self.store.finish_run(run, "ok", message, result)
        return {**result, "message": message}

    # Background retrieval ---------------------------------------------------
    def status(self) -> dict | None:
        with self.lock:
            return dict(self.job) if self.job else None

    def _credentials(self, key: bytes) -> tuple[str, str]:
        token, query = self.store.secret(key, "ibkr.token"), self.store.secret(key, "ibkr.queryId")
        if not token or not query:
            raise SyncError("Save your Flex Query ID and token first.")
        return token, query

    def next_range(self) -> tuple[str, str] | None:
        """Continue from the latest stored report so daily syncs never leave a gap.
        With no reports yet, use the period configured in the Flex query (None)."""
        reports = self.store.reports()
        if not reports:
            return None
        last = max(date.fromisoformat(r["toDate"]) for r in reports)
        yesterday = self.today() - timedelta(days=1)  # Completed days only.
        if last >= yesterday:
            raise SyncError("Already up to date with IBKR's latest completed day.")
        return last.strftime("%Y%m%d"), yesterday.strftime("%Y%m%d")

    def start(self, kind: str = "sync", from_date: date | None = None) -> dict:
        key = self.auth.key
        if key is None:
            raise SyncError("Unlock Still first.")
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise SyncError("A sync is already running.")
            token, query = self._credentials(key)
            if kind == "history":
                ranges = history_ranges(from_date, self.today() - timedelta(days=1))
            else:
                nxt = self.next_range()
                ranges = [None] if nxt is None else history_ranges(
                    datetime.strptime(nxt[0], "%Y%m%d").date(), datetime.strptime(nxt[1], "%Y%m%d").date())
            run = self.store.start_run(kind)
            self.job = {"run": run, "kind": kind, "stage": "Requesting the report from IBKR", "step": 0,
                        "steps": len(ranges), "done": False, "ok": None, "message": ""}
            self.thread = Thread(target=self._work, args=(run, token, query, ranges), daemon=True)
            self.thread.start()
            return dict(self.job)

    def _stage(self, **changes) -> None:
        with self.lock:
            self.job.update(changes)

    def _work(self, run: int, token: str, query: str, ranges) -> None:
        imported, attention = [], None
        try:
            client = self.client_factory(token, query)
            with single_worker(self.store.folder):
                for index, period in enumerate(ranges, 1):
                    if self.stopping.is_set():
                        raise SyncError("Stopped.")
                    label = "" if period is None else " for {} to {}".format(
                        *(datetime.strptime(d, "%Y%m%d").date().isoformat() for d in period))
                    self._stage(step=index, stage=f"Waiting for IBKR to prepare the report{label}")
                    report = client.fetch(*(period or (None, None)))
                    self._stage(stage="Checking and reconciling the report")
                    imported.append(self.import_report(report.content, "sync"))
            new = sum(1 for r in imported if r["stored"])
            message = f"Imported {new} new report{'s' if new != 1 else ''}." if new else "No new activity; already imported."
            self.store.finish_run(run, "ok", message, {"reports": imported})
            self._stage(done=True, ok=True, stage="Done", message=message)
        except (FlexError, SyncError) as error:
            if isinstance(error, FlexServiceError):
                attention = ATTENTION.get(error.code)
            self.store.finish_run(run, "failed", str(error), {"reports": imported, "attention": attention})
            self._stage(done=True, ok=False, stage="Stopped", message=str(error), attention=attention)
        except Exception:
            message = "Sync failed unexpectedly. Nothing was changed; try again."
            self.store.finish_run(run, "failed", message, {"reports": imported})
            self._stage(done=True, ok=False, stage="Stopped", message=message)

    # Daily schedule ---------------------------------------------------------
    def tick(self) -> bool:
        """Start the scheduled sync once per day after its time, while unlocked."""
        schedule = self.store.setting("schedule") or {}
        if not schedule.get("enabled") or self.auth.key is None:
            return False
        if self.thread and self.thread.is_alive():
            return False
        now = self.now()
        today = now.date().isoformat()
        if self.store.setting("lastScheduledRun") == today:
            return False
        hour, minute = (int(x) for x in schedule.get("time", "07:00").split(":"))
        if (now.hour, now.minute) < (hour, minute):
            return False
        self.store.set_setting("lastScheduledRun", today)  # One attempt per day, even if it fails.
        try:
            self.start("scheduled")
        except SyncError as error:
            run = self.store.start_run("scheduled")
            self.store.finish_run(run, "skipped", str(error))
        return True

    def run_scheduler(self, interval: float = 30.0) -> Thread:
        def loop():
            while not self.stopping.wait(interval):
                try:
                    self.tick()
                except Exception:
                    pass  # A scheduling problem must never stop the server.
        thread = Thread(target=loop, daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self.stopping.set()
