"""Offline tests for the local app: vault, sign-in, API guards, sync worker and portfolio view.
Synthetic data only; no IBKR or search provider is contacted."""
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import re
import sqlite3
import threading

from ibkr.flex import FlexReport, FlexServiceError, validate_report
from still import portfolio, vault
from still.auth import Auth, AuthError
from still.server import App, create_server
from still.store import Store
from still.sync import Sync, SyncError, history_ranges

ROOT = Path(__file__).resolve().parents[1]
ACTIVITY = (ROOT / "tests/fixtures/synthetic-activity.xml").read_bytes()
PASS = "synthetic owner passphrase"


def later_report(days=2, factor=1.02):
    """A follow-on report: no new activity, every mark price up by `factor`."""
    x = ACTIVITY.decode().replace('fromDate="20260102" toDate="20261021"', f'fromDate="20261021" toDate="202610{21 + days}"')
    x = re.sub(r"<Trades>.*?</Trades>", "<Trades />", x, flags=re.S)
    x = re.sub(r"<CashTransactions>.*?</CashTransactions>", "<CashTransactions />", x, flags=re.S)
    x = x.replace('startingCash="0"', 'startingCash="14820.50"').replace('reportDate="20261021"', f'reportDate="202610{21 + days}"')
    x = re.sub(r' (commissions|deposits|dividends|withholdingTax|netTradesPurchases)="[^"]*"', "", x)
    x = re.sub(r'markPrice="([\d.]+)"', lambda m: f'markPrice="{float(m[1]) * factor:.2f}"', x)

    def value(m):
        q = float(re.search(r'position="([\d.]+)"', m[0])[1])
        p = float(re.search(r'markPrice="([\d.]+)"', m[0])[1])
        return re.sub(r'positionValue="[\d.]+"', f'positionValue="{q * p:.2f}"', m[0])
    return re.sub(r"<OpenPosition [^>]*/>", value, x).encode()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class VaultTests(TestCase):
    def test_round_trip_wrong_passphrase_and_rewrap(self):
        record, key = vault.create(PASS)
        self.assertEqual(vault.unlock(record, PASS), key)
        with self.assertRaisesRegex(vault.VaultError, "Incorrect passphrase"):
            vault.unlock(record, PASS + "x")
        moved = vault.rewrap(record, PASS, "another synthetic passphrase")
        self.assertEqual(vault.unlock(moved, "another synthetic passphrase"), key)
        with self.assertRaises(vault.VaultError):
            vault.unlock(moved, PASS)

    def test_sealed_data_detects_tampering_and_wrong_purpose(self):
        _, key = vault.create(PASS)
        blob = vault.seal(key, b"secret", "secret:ibkr.token")
        self.assertEqual(vault.open_sealed(key, blob, "secret:ibkr.token"), b"secret")
        with self.assertRaises(vault.VaultError):
            vault.open_sealed(key, blob, "report")
        with self.assertRaises(vault.VaultError):
            vault.open_sealed(key, blob[:-1] + bytes([blob[-1] ^ 1]), "secret:ibkr.token")

    def test_weak_passphrases_are_refused(self):
        for weak in ("short", "aaaaaaaaaaaaaaaa", None, "x" * 2000):
            with self.assertRaises(vault.VaultError):
                vault.create(weak)


class StoreAndAuthTests(TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.store = Store(Path(self.folder.name) / "data")
        self.clock = Clock()
        self.auth = Auth(self.store, clock=self.clock)

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def test_files_are_private_and_hold_no_plaintext(self):
        self.auth.setup(PASS)
        self.store.set_secret(self.auth.key, "ibkr.token", "SYNTHETICTOKEN123")
        self.store.add_report(self.auth.key, ACTIVITY, "upload", "2026-01-02", "2026-10-21")
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.folder.stat().st_mode & 0o777, 0o700)
        raw = self.store.path.read_bytes()
        for leak in (b"SYNTHETICTOKEN123", b"NVIDIA", b"SYNTHETIC-7", b"Synthetic Person", PASS.encode()):
            self.assertNotIn(leak, raw)
        self.assertIsNone(self.store.add_report(self.auth.key, ACTIVITY, "upload", "2026-01-02", "2026-10-21"))

    def test_sessions_expire_and_lock_drops_the_key(self):
        token = self.auth.setup(PASS)
        self.assertTrue(self.auth.check(token))
        self.clock.now += 31 * 60
        self.assertFalse(self.auth.check(token))
        self.assertIsNotNone(self.auth.key)  # Idle expiry keeps background syncs working.
        token = self.auth.login(PASS)
        self.auth.lock_now()
        self.assertFalse(self.auth.check(token))
        self.assertIsNone(self.auth.key)
        self.assertEqual(self.auth.state(), "locked")

    def test_failed_sign_ins_back_off(self):
        self.auth.setup(PASS)
        for _ in range(3):
            with self.assertRaisesRegex(AuthError, "Incorrect"):
                self.auth.login("wrong synthetic passphrase")
        with self.assertRaisesRegex(AuthError, "Too many attempts"):
            self.auth.login(PASS)
        self.clock.now += 2
        self.assertTrue(self.auth.check(self.auth.login(PASS)))

    def test_reset_wipes_everything(self):
        self.auth.setup(PASS)
        self.store.set_secret(self.auth.key, "ibkr.token", "SYNTHETICTOKEN123")
        self.auth.reset()
        self.assertEqual(self.auth.state(), "setup")
        self.assertFalse(self.store.has_secret("ibkr.token"))


class FakeClient:
    """Stands in for FlexClient: records requested ranges, returns queued reports or errors."""
    calls: list = []
    responses: list = []

    def __init__(self, token, query):
        self.token, self.query = token, query

    def fetch(self, from_date=None, to_date=None):
        FakeClient.calls.append((self.token, self.query, from_date, to_date))
        response = FakeClient.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return validate_report(response)


class SyncTests(TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.store = Store(Path(self.folder.name))
        self.auth = Auth(self.store)
        self.auth.setup(PASS)
        self.now = datetime(2026, 10, 26, 8, 0)
        self.sync = Sync(self.store, self.auth, client_factory=FakeClient, today=lambda: date(2026, 10, 26),
                         now=lambda: self.now)
        FakeClient.calls, FakeClient.responses = [], []

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def connect(self):
        self.store.set_secret(self.auth.key, "ibkr.token", "SYNTHETICTOKEN")
        self.store.set_secret(self.auth.key, "ibkr.queryId", "123")

    def run_job(self, kind="sync", start=None):
        self.sync.start(kind, start)
        self.sync.thread.join(5)
        return self.sync.status()

    def test_history_ranges_respect_ibkr_limit(self):
        ranges = history_ranges(date(2024, 1, 1), date(2026, 10, 25))
        self.assertEqual(ranges[0], ("20240101", "20241230"))
        self.assertEqual(ranges[-1][1], "20261025")
        for a, b in zip(ranges, ranges[1:]):
            self.assertEqual((datetime.strptime(b[0], "%Y%m%d") - datetime.strptime(a[1], "%Y%m%d")).days, 1)
        with self.assertRaises(SyncError):
            history_ranges(date(2026, 10, 27), date(2026, 10, 25))

    def test_first_sync_uses_query_period_then_continues_without_gaps(self):
        self.connect()
        FakeClient.responses = [ACTIVITY]
        job = self.run_job()
        self.assertTrue(job["ok"], job)
        self.assertEqual(FakeClient.calls[0], ("SYNTHETICTOKEN", "123", None, None))
        FakeClient.responses = [later_report(4)]
        self.assertTrue(self.run_job()["ok"])
        self.assertEqual(FakeClient.calls[1][2:], ("20261021", "20261025"))
        self.assertEqual(len(self.store.reports()), 2)
        self.assertEqual(self.sync.view["asOf"], "2026-10-25")
        with self.assertRaisesRegex(SyncError, "up to date"):
            self.sync.start()

    def test_ibkr_errors_are_recorded_with_attention_codes(self):
        self.connect()
        FakeClient.responses = [FlexServiceError("1012")]
        job = self.run_job()
        self.assertFalse(job["ok"])
        self.assertEqual(job["attention"], "token_expired")
        self.assertEqual(self.store.runs(1)[0]["status"], "failed")
        self.assertNotIn("SYNTHETICTOKEN", json.dumps(self.store.runs()))

    def test_sync_needs_credentials_and_an_unlocked_vault(self):
        with self.assertRaisesRegex(SyncError, "Query ID and token"):
            self.sync.start()
        self.connect()
        self.auth.lock_now()
        with self.assertRaisesRegex(SyncError, "Unlock"):
            self.sync.start()

    def test_reports_that_leave_a_gap_are_refused_before_storing(self):
        self.sync.upload(ACTIVITY)
        gap = later_report(4).replace(b'fromDate="20261021"', b'fromDate="20261024"')
        with self.assertRaisesRegex(SyncError, "gap"):
            self.sync.upload(gap)
        self.assertEqual(len(self.store.reports()), 1)

    def test_schedule_runs_once_a_day_after_its_time(self):
        self.connect()
        self.store.set_setting("schedule", {"enabled": True, "time": "09:00"})
        self.assertFalse(self.sync.tick())
        self.now = datetime(2026, 10, 26, 9, 5)
        FakeClient.responses = [ACTIVITY]
        self.assertTrue(self.sync.tick())
        self.sync.thread.join(5)
        self.assertFalse(self.sync.tick())
        self.assertEqual(len(FakeClient.calls), 1)


class PortfolioTests(TestCase):
    def test_view_matches_ibkr_report(self):
        view = portfolio.build([ACTIVITY], from_inception=True)
        self.assertEqual(view["value"], 267128.50)
        self.assertEqual(view["cashBase"], 14820.50)
        self.assertEqual(view["asOf"], "2026-10-21")
        self.assertEqual(view["reconciliation"]["counts"], {"pass": 33, "fail": 0, "unverified": 0})
        nvda = view["positions"][0]
        self.assertEqual((nvda["symbol"], nvda["qty"], nvda["price"]), ("NVDA", 240.0, 182.64))
        self.assertAlmostEqual(nvda["cost"] * 240, 30817.20, places=6)  # IBKR cost basis includes commission.
        self.assertIsNone(nvda["previous"])
        self.assertNotIn("Synthetic Person", json.dumps(view))

    def test_second_report_supplies_previous_marks_and_history(self):
        view = portfolio.build([ACTIVITY, later_report(2)], from_inception=True)
        self.assertEqual(view["previousDate"], "2026-10-21")
        self.assertEqual([h["date"] for h in view["history"]], ["2026-10-21", "2026-10-23"])
        self.assertEqual(view["positions"][0]["previous"], 182.64)


class ServerTests(TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.server = create_server(0, App(Path(self.folder.name), client_factory=FakeClient))
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = None

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.server.app.store.close()
        self.folder.cleanup()

    def call(self, path, body=None, *, method=None, raw=None, ctype="application/json", headers=None, cookie=True):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        method = method or ("POST" if data is not None else "GET")
        h = {"X-Still-Request": "1"} if method == "POST" else {}
        if data is not None:
            h["Content-Type"] = ctype
        if cookie and self.cookie:
            h["Cookie"] = self.cookie
        h.update(headers or {})
        try:
            response = urlopen(Request(self.base + path, data=data, headers=h, method=method), timeout=10)
        except HTTPError as error:
            return error.code, error.headers, error.read()
        if response.headers.get("Set-Cookie"):
            self.cookie = response.headers["Set-Cookie"].split(";")[0]
        return response.status, response.headers, response.read()

    def json(self, *args, **kwargs):
        status, _, body = self.call(*args, **kwargs)
        return status, json.loads(body)

    def setup_owner(self, mode="ibkr"):
        status, data = self.json("/api/setup", {"passphrase": PASS, "mode": mode})
        self.assertEqual(status, 200, data)

    def test_every_private_route_needs_a_session(self):
        _, private = self.server.app.routes()
        self.setup_owner()
        for method, path in private:
            with self.subTest(path=path):
                status, _, _ = self.call(path, {} if method == "POST" else None, method=method, cookie=False)
                self.assertEqual(status, 401)

    def test_session_cookie_is_http_only_and_strict(self):
        status, headers, _ = self.call("/api/setup", {"passphrase": PASS, "mode": "demo"})
        cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_mutations_need_the_request_header_and_same_origin(self):
        self.setup_owner()
        self.assertEqual(self.call("/api/lock", {}, headers={"X-Still-Request": ""})[0], 403)
        self.assertEqual(self.call("/api/lock", {}, headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.call("/api/portfolio", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.call("/api/portfolio", headers={"Host": "evil.example"})[0], 403)
        # Opening the page itself from a link elsewhere is allowed.
        self.assertEqual(self.call("/", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"})[0], 200)

    def test_setup_upload_and_portfolio(self):
        self.assertEqual(self.json("/api/session")[1]["state"], "setup")
        self.setup_owner()
        self.json("/api/ibkr/options", {"fromInception": True})
        status, result = self.json("/api/ibkr/upload", raw=ACTIVITY, ctype="application/xml")
        self.assertEqual((status, result["stored"]), (200, True))
        self.assertFalse(self.json("/api/ibkr/upload", raw=ACTIVITY, ctype="application/xml")[1]["stored"])
        status, data = self.json("/api/portfolio")
        self.assertEqual(data["view"]["value"], 267128.50)
        self.assertEqual(data["view"]["reconciliation"]["counts"]["fail"], 0)
        status, headers, body = self.call("/api/export/holdings.csv")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Disposition"].startswith("attachment"))
        self.assertIn(b"NVDA", body)

    def test_upload_rejects_malformed_and_oversized_reports(self):
        self.setup_owner()
        self.assertEqual(self.call("/api/ibkr/upload", raw=b"<html>not flex</html>", ctype="application/xml")[0], 400)
        self.assertEqual(self.call("/api/ibkr/upload", raw=ACTIVITY, ctype="text/csv")[0], 415)
        status, _, _ = self.call("/api/ibkr/upload", raw=b"x", ctype="application/xml",
                                 headers={"Content-Length": str(33 * 1024 * 1024)})
        self.assertEqual(status, 413)

    def test_credentials_are_validated_and_never_returned(self):
        self.setup_owner()
        self.assertEqual(self.call("/api/ibkr/credentials", {"queryId": "12ab", "token": "x"})[0], 400)
        self.assertEqual(self.call("/api/ibkr/credentials", {"queryId": "123", "token": "has space"})[0], 400)
        status, data = self.json("/api/ibkr/credentials", {"queryId": "123", "token": "SYNTHETICTOKEN", "tokenExpires": "2027-01-31"})
        self.assertEqual(status, 200)
        self.assertTrue(data["tokenSaved"])
        self.assertNotIn("SYNTHETICTOKEN", json.dumps(data))
        self.assertNotIn("SYNTHETICTOKEN", json.dumps(self.json("/api/ibkr")[1]))
        # The Query ID can stay as saved while the token is replaced.
        self.assertEqual(self.json("/api/ibkr/credentials", {"token": "SYNTHETICTOKEN2"})[0], 200)
        FakeClient.calls, FakeClient.responses = [], [ACTIVITY]
        self.json("/api/ibkr/sync", {})
        self.server.app.sync.thread.join(5)
        self.assertEqual(FakeClient.calls[0][:2], ("SYNTHETICTOKEN2", "123"))
        self.assertEqual(self.json("/api/ibkr/disconnect", {})[1]["tokenSaved"], False)

    def test_search_keys_are_stored_in_the_vault(self):
        self.setup_owner()
        self.assertEqual(self.call("/api/search-settings", {"provider": "searxng", "value": "http://example.org"})[0], 400)
        status, data = self.json("/api/search-settings", {"provider": "tavily", "value": "tvly-SYNTHETIC"})
        self.assertEqual((status, data["configured"]["tavily"], data["provider"]), (200, True, "tavily"))
        config = self.json("/api/news/config")[1]
        self.assertTrue(next(p for p in config["providers"] if p["id"] == "tavily")["configured"])
        blobs = sqlite3.connect(self.server.app.store.path).execute("SELECT blob FROM secrets").fetchall()
        self.assertTrue(blobs)
        self.assertFalse(any(b"tvly-SYNTHETIC" in row[0] for row in blobs))
        self.assertNotIn(b"tvly-SYNTHETIC", self.server.app.store.path.read_bytes())

    def test_lock_sign_in_and_reset(self):
        self.setup_owner()
        self.json("/api/ibkr/upload", raw=ACTIVITY, ctype="application/xml")
        self.json("/api/lock", {})
        self.assertEqual(self.json("/api/session")[1], {"state": "locked", "signedIn": False, "mode": None})
        self.assertEqual(self.call("/api/portfolio")[0], 401)
        self.assertEqual(self.call("/api/login", {"passphrase": "wrong synthetic passphrase"})[0], 400)
        self.assertEqual(self.json("/api/login", {"passphrase": PASS})[0], 200)
        self.assertEqual(self.json("/api/portfolio")[1]["view"]["value"], 267128.50)
        self.assertEqual(self.call("/api/reset", {"confirm": "reset"})[0], 400)
        self.assertEqual(self.json("/api/reset", {"confirm": "RESET"})[1]["state"], "setup")
        self.assertEqual(self.server.app.store.reports(), [])


if __name__ == "__main__":
    main()
