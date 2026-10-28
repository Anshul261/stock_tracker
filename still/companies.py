"""US-listed companies and funds from SEC EDGAR: search, profiles and recent filings.

SEC's fair-access policy requires every request to identify the app and a
contact email, so nothing is fetched until the owner saves one in Settings.
Only www.sec.gov and data.sec.gov are contacted. The ticker lists are cached on
disk for a week; profiles are cached in memory for an hour. No prices: SEC data
has none, and Still shows prices only for holdings, from IBKR reports.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Callable
from urllib.parse import urlsplit
import json
import os
import re
import ssl
import time
import urllib.request

LISTS = {"companies": "https://www.sec.gov/files/company_tickers_exchange.json",
         "funds": "https://www.sec.gov/files/company_tickers_mf.json"}
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{:010d}.json"
HOSTS = frozenset({"www.sec.gov", "data.sec.gov"})
MAX_BYTES = 16 * 1024 * 1024
LIST_TTL, PROFILE_TTL = 7 * 86400, 3600
EMAIL = re.compile(r"[^@\s<>()\"']{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}")
# Forms most owners want first; everything else is still listed under "All filings".
KEY_FORMS = ("10-K", "10-Q", "8-K", "20-F", "40-F", "6-K", "DEF 14A", "S-1", "N-CSR", "N-CSRS", "497K")


class SecError(Exception):
    """Safe to display."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def fetch(url: str, contact: str) -> bytes:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS:
        raise SecError("Only SEC EDGAR addresses are allowed.")
    request = urllib.request.Request(url, headers={"User-Agent": f"Still/0.1 ({contact})", "Accept": "application/json",
                                                   "Accept-Encoding": "identity"})
    opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=15) as response:
            data = response.read(MAX_BYTES + 1)
    except Exception:
        raise SecError("SEC EDGAR could not be reached; try again later.") from None
    if len(data) > MAX_BYTES:
        raise SecError("SEC EDGAR sent more data than expected.")
    return data


def valid_contact(value) -> str:
    if not isinstance(value, str) or not EMAIL.fullmatch(value.strip()):
        raise SecError("Enter an email address SEC can use to contact you about your requests.")
    return value.strip()


def _key(text: str) -> str:
    """Tickers compare without punctuation: BRK-B, BRK.B and BRK B are the same."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


class Directory:
    def __init__(self, folder: Path, contact: Callable[[], str | None], *,
                 transport: Callable[[str, str], bytes] = fetch, clock: Callable[[], float] = time.time):
        self.path = folder / "sec-tickers.json"
        self.contact, self.transport, self.clock = contact, transport, clock
        self.lock = Lock()
        self.entries: list[dict] | None = None
        self.loaded_at = 0.0
        self.profiles: OrderedDict[int, tuple[float, dict]] = OrderedDict()

    def _contact(self) -> str:
        contact = self.contact()
        if not contact:
            raise SecError("Add a contact email for SEC in Settings → News & data to search all companies.")
        return contact

    def _build(self, lists: dict) -> list[dict]:
        entries, seen = [], set()
        for cik, name, ticker, exchange in lists["companies"]["data"]:
            if ticker and ticker not in seen:
                seen.add(ticker)
                entries.append({"ticker": ticker, "name": name, "exchange": exchange or "", "cik": int(cik), "kind": "company"})
        for cik, _series, _class, symbol in lists["funds"]["data"]:
            if symbol and symbol not in seen:
                seen.add(symbol)
                entries.append({"ticker": symbol, "name": "", "exchange": "", "cik": int(cik), "kind": "fund"})
        for e in entries:
            e["_ticker"], e["_name"] = _key(e["ticker"]), e["name"].upper()
        return entries

    def load(self) -> list[dict]:
        with self.lock:
            if self.entries is not None and self.clock() - self.loaded_at < LIST_TTL:
                return self.entries
            cached = None
            try:
                cached = json.loads(self.path.read_text())
            except (OSError, ValueError):
                pass
            if cached and self.clock() - cached.get("fetched", 0) < LIST_TTL:
                lists, fetched = cached["lists"], cached["fetched"]
            else:
                try:
                    contact = self._contact()
                    lists = {k: json.loads(self.transport(url, contact)) for k, url in LISTS.items()}
                    fetched = self.clock()
                    tmp = self.path.with_suffix(".tmp")
                    tmp.write_text(json.dumps({"fetched": fetched, "lists": lists}))
                    os.replace(tmp, self.path)
                except (SecError, ValueError, KeyError) as error:
                    if not cached:  # A stale list is better than none.
                        raise SecError(str(error) if isinstance(error, SecError) else "SEC sent an unexpected ticker list.") from None
                    lists, fetched = cached["lists"], cached["fetched"]
            try:
                self.entries = self._build(lists)
            except (KeyError, TypeError, ValueError):
                raise SecError("SEC sent an unexpected ticker list.") from None
            self.loaded_at = self.clock()
            return self.entries

    def search(self, query: str, limit: int = 20) -> list[dict]:
        if not isinstance(query, str) or not query.strip() or len(query) > 80:
            return []
        q = query.strip().upper()
        qk = _key(q)
        words = q.split()
        scored = []
        for e in self.load():
            if qk and e["_ticker"] == qk:
                score = 100
            elif qk and e["_ticker"].startswith(qk):
                score = 80 - len(e["_ticker"])
            elif e["_name"] and all(any(w2.startswith(w) for w2 in e["_name"].split()) for w in words):
                score = 60
            elif e["_name"] and q in e["_name"]:
                score = 40
            else:
                continue
            # Exchange-listed companies before OTC and funds; shorter names read as the main listing.
            score += {"Nasdaq": 5, "NYSE": 5, "CBOE": 3}.get(e["exchange"], 0) - len(e["name"]) / 1000
            scored.append((score, e))
        scored.sort(key=lambda pair: -pair[0])
        return [{k: v for k, v in e.items() if not k.startswith("_")} for _, e in scored[:limit]]

    def find(self, ticker: str) -> dict | None:
        key = _key(ticker or "")
        return next(({k: v for k, v in e.items() if not k.startswith("_")}
                     for e in self.load() if e["_ticker"] == key), None)

    def profile(self, ticker: str) -> dict:
        entry = self.find(ticker)
        if entry is None:
            raise SecError("That ticker is not in SEC's list of US-listed companies and funds.")
        cik = entry["cik"]
        with self.lock:
            hit = self.profiles.get(cik)
            if hit and self.clock() - hit[0] < PROFILE_TTL:
                return {**hit[1], "ticker": entry["ticker"], "kind": entry["kind"]}
        try:
            data = json.loads(self.transport(SUBMISSIONS.format(cik), self._contact()))
            recent = data["filings"]["recent"]
            filings = []
            for i in range(min(len(recent["form"]), 200)):
                accession = recent["accessionNumber"][i]
                document = recent["primaryDocument"][i]
                filings.append({
                    "form": recent["form"][i], "date": recent["filingDate"][i],
                    "reportDate": recent.get("reportDate", [""] * (i + 1))[i] or None,
                    "description": recent["primaryDocDescription"][i] or recent["form"][i],
                    "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{document}"
                    if document else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
                })
            profile = {
                "cik": cik, "name": data.get("name") or entry["name"], "tickers": data.get("tickers") or [],
                "exchanges": [x for x in data.get("exchanges") or [] if x], "sic": data.get("sicDescription") or "",
                "state": data.get("stateOfIncorporationDescription") or data.get("stateOfIncorporation") or "",
                "fiscalYearEnd": data.get("fiscalYearEnd") or "", "category": data.get("category") or "",
                "entityType": data.get("entityType") or "", "website": data.get("website") or data.get("investorWebsite") or "",
                "formerNames": [f.get("name") for f in data.get("formerNames") or [] if f.get("name")][:5],
                "filings": filings, "keyFilings": [f for f in filings if f["form"] in KEY_FORMS][:20],
                "edgar": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
            }
        except (KeyError, TypeError, ValueError, IndexError):
            raise SecError("SEC sent unexpected filing data for this company.") from None
        with self.lock:
            self.profiles[cik] = (self.clock(), profile)
            while len(self.profiles) > 64:
                self.profiles.popitem(last=False)
        return {**profile, "ticker": entry["ticker"], "kind": entry["kind"]}
