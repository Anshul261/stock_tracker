"""SEC company directory and routes, offline with a fake SEC transport. Synthetic data only."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
import json

from still.companies import Directory, SecError, fetch, valid_contact

COMPANIES = {"fields": ["cik", "name", "ticker", "exchange"], "data": [
    [1, "SYNTHETIC APPLE ORCHARDS INC", "APLO", "Nasdaq"], [2, "Apple Synthetic Co", "AAPS", "NYSE"],
    [3, "BERKSHIRE SYNTHETIC HOLDINGS", "BRK-B", "NYSE"], [4, "Apple Pie Otc Corp", "APIE", "OTC"],
    [5, "META SYNTHETIC PLATFORMS", "META", "Nasdaq"], [6, "<img src=x onerror=alert(1)>", "XSS", None]]}
FUNDS = {"fields": ["cik", "seriesId", "classId", "symbol"], "data": [[7, "S1", "C1", "VOO"], [5, "S2", "C2", "META"]]}
SUBMISSIONS = {"name": "Apple Synthetic Co", "tickers": ["AAPS"], "exchanges": ["NYSE"], "sicDescription": "Synthetic Computers",
               "stateOfIncorporationDescription": "Testland", "fiscalYearEnd": "0926", "category": "Large accelerated filer",
               "entityType": "operating", "website": "", "formerNames": [{"name": "APPLE SYNTHETIC COMPUTER"}],
               "addresses": {"business": {"street1": "1 Private Way"}}, "phone": "555-0100",
               "filings": {"recent": {"form": ["4", "10-Q", "8-K", "10-K"], "filingDate": ["2026-10-22", "2026-08-01", "2026-07-30", "2025-11-01"],
                                      "reportDate": ["", "2026-06-27", "2026-07-30", "2025-09-27"],
                                      "accessionNumber": ["0000000002-26-000004", "0000000002-26-000003", "0000000002-26-000002", "0000000002-25-000001"],
                                      "primaryDocument": ["form4.xml", "q3.htm", "8k.htm", "10k.htm"],
                                      "primaryDocDescription": ["FORM 4", "10-Q", "", "10-K"]}}}


class FakeSec:
    def __init__(self):
        self.calls = []

    def __call__(self, url, contact):
        self.calls.append((url, contact))
        if url.endswith("company_tickers_exchange.json"):
            return json.dumps(COMPANIES).encode()
        if url.endswith("company_tickers_mf.json"):
            return json.dumps(FUNDS).encode()
        if url.endswith("CIK0000000002.json"):
            return json.dumps(SUBMISSIONS).encode()
        raise SecError("SEC EDGAR could not be reached; try again later.")


class DirectoryTests(TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.sec = FakeSec()
        self.contact = "owner@example.com"
        self.now = 1_000_000.0
        self.directory = Directory(Path(self.folder.name), lambda: self.contact, transport=self.sec, clock=lambda: self.now)

    def tearDown(self):
        self.folder.cleanup()

    def tickers(self, query):
        return [r["ticker"] for r in self.directory.search(query)]

    def test_exact_ticker_then_prefix_then_name_words(self):
        self.assertEqual(self.tickers("META")[0], "META")
        self.assertEqual(self.tickers("apl"), ["APLO"])
        self.assertEqual(self.tickers("apple")[:2], ["AAPS", "APLO"])  # Listed companies before OTC; shorter names first.
        self.assertEqual(self.tickers("apple")[-1], "APIE")
        self.assertEqual(self.tickers("apple syn"), ["AAPS", "APLO"])  # Word order doesn't matter.
        self.assertEqual(self.tickers("apple orch"), ["APLO"])

    def test_punctuation_in_tickers_is_ignored(self):
        for query in ("BRK.B", "brk b", "BRKB", "BRK-B"):
            self.assertEqual(self.tickers(query)[0], "BRK-B", query)

    def test_funds_are_searchable_but_companies_win_duplicate_tickers(self):
        voo = self.directory.search("VOO")[0]
        self.assertEqual((voo["ticker"], voo["kind"], voo["name"]), ("VOO", "fund", ""))
        self.assertEqual([r["kind"] for r in self.directory.search("META") if r["ticker"] == "META"], ["company"])

    def test_requests_identify_the_owner_and_lists_are_cached(self):
        self.directory.search("META")
        self.assertEqual({c for _, c in self.sec.calls}, {"owner@example.com"})
        self.assertEqual(len(self.sec.calls), 2)
        again = Directory(Path(self.folder.name), lambda: None, transport=self.sec, clock=lambda: self.now + 3600)
        self.assertEqual([r["ticker"] for r in again.search("META")][0], "META")
        self.assertEqual(len(self.sec.calls), 2)  # Served from the on-disk cache, no contact needed.

    def test_without_a_contact_nothing_is_fetched(self):
        self.contact = None
        with self.assertRaisesRegex(SecError, "contact email"):
            self.directory.search("META")
        self.assertEqual(self.sec.calls, [])

    def test_stale_cache_is_used_when_sec_is_unreachable(self):
        self.directory.search("META")
        self.now += 8 * 86400
        self.directory.entries = None
        self.sec.calls.clear()
        broken = Directory(Path(self.folder.name), lambda: self.contact,
                           transport=lambda url, contact: (_ for _ in ()).throw(SecError("SEC EDGAR could not be reached; try again later.")),
                           clock=lambda: self.now)
        self.assertEqual(broken.search("META")[0]["ticker"], "META")

    def test_profile_lists_filings_with_sec_links_and_no_private_contact_details(self):
        p = self.directory.profile("aaps")
        self.assertEqual((p["name"], p["cik"], p["sic"], p["fiscalYearEnd"]), ("Apple Synthetic Co", 2, "Synthetic Computers", "0926"))
        self.assertEqual([f["form"] for f in p["keyFilings"]], ["10-Q", "8-K", "10-K"])
        self.assertEqual(p["filings"][1]["url"], "https://www.sec.gov/Archives/edgar/data/2/000000000226000003/q3.htm")
        self.assertEqual(p["filings"][2]["description"], "8-K")
        text = json.dumps(p)
        self.assertNotIn("Private Way", text)
        self.assertNotIn("555-0100", text)
        calls = len(self.sec.calls)
        self.directory.profile("AAPS")
        self.assertEqual(len(self.sec.calls), calls)  # Cached for an hour.
        with self.assertRaisesRegex(SecError, "not in SEC"):
            self.directory.profile("NOPE")

    def test_only_sec_hosts_and_valid_emails(self):
        with self.assertRaisesRegex(SecError, "Only SEC"):
            fetch("https://evil.example/company_tickers.json", "owner@example.com")
        with self.assertRaisesRegex(SecError, "Only SEC"):
            fetch("http://www.sec.gov/files/company_tickers.json", "owner@example.com")
        self.assertEqual(valid_contact(" owner@example.com "), "owner@example.com")
        for bad in ("", "owner", "a b@example.com", "owner@example", None, "<x>@example.com"):
            with self.assertRaises(SecError):
                valid_contact(bad)


if __name__ == "__main__":
    main()
