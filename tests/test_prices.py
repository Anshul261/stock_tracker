"""Alpaca prices and rebuilt portfolio history, offline with a fake Alpaca. Synthetic data only."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
import json

from ibkr.ledger import merge, parse_ledger
from still.auth import Auth
from still.prices import PriceError, Prices, alpaca_symbol
from still.store import Store

ROOT = Path(__file__).resolve().parents[1]
ACTIVITY = (ROOT / "tests/fixtures/synthetic-activity.xml").read_bytes()
TRADE_PRICES = {"NVDA": 128.40, "MSFT": 437.50, "AAPL": 221.60, "GOOGL": 173.25, "AMZN": 199.10, "VTI": 277.20,
                "TSM": 193.80, "COST": 905.30}
MARKS = {"NVDA": 182.64, "MSFT": 521.38, "AAPL": 248.50, "GOOGL": 198.24, "AMZN": 224.16, "VTI": 308.72,
         "TSM": 244.80, "COST": 962.40}


def weekdays(start, end):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


class FakeAlpaca:
    """Closes sit at each trade price until 20 Oct 2026, then jump to the report's mark on 21 Oct.
    SPY rises 0.1 every trading day. Bars come back 50 per page to exercise pagination."""

    def __init__(self, valid=("SYNTHKEYID1", "SYNTHSECRET1")):
        self.valid, self.calls = valid, []
        self.days = list(weekdays(date(2025, 12, 1), date(2026, 10, 21)))

    def close(self, symbol, day):
        if symbol == "SPY":
            return round(600 + 0.1 * self.days.index(day), 2)
        return MARKS[symbol] if day >= date(2026, 10, 21) else TRADE_PRICES[symbol]

    def __call__(self, path, params, key_id, secret):
        self.calls.append((path, dict(params)))
        if (key_id, secret) != self.valid:
            raise PriceError("Alpaca rejected the API key ID or secret. Check them in Settings → Prices.")
        symbols = params["symbols"].split(",")
        if path == "/v2/stocks/snapshots":
            return json.dumps({s: {"latestTrade": {"p": 101.5, "t": "2026-10-26T14:30:00Z"},
                                   "prevDailyBar": {"c": 100.0, "t": "2026-10-23T04:00:00Z"}} for s in symbols if s != "NOPE"}).encode()
        start = date.fromisoformat(params["start"])
        rows = [(s, d) for s in symbols for d in self.days if d >= start and s in MARKS | {"SPY": 0}]
        offset = int(params.get("page_token") or 0)
        page = rows[offset:offset + 50]
        bars = {}
        for s, d in page:
            bars.setdefault(s, []).append({"t": f"{d.isoformat()}T04:00:00Z", "c": self.close(s, d)})
        nxt = offset + 50 if offset + 50 < len(rows) else None
        return json.dumps({"bars": bars, "next_page_token": str(nxt) if nxt else None}).encode()


class PricesTests(TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.store = Store(Path(self.folder.name))
        self.auth = Auth(self.store)
        self.auth.setup("synthetic owner passphrase")
        self.alpaca = FakeAlpaca()
        self.clock = [1000.0]
        self.prices = Prices(self.store, self.auth, transport=self.alpaca, clock=lambda: self.clock[0],
                             now=lambda: datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc))
        self.ledger = merge(parse_ledger(ACTIVITY))

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def connect(self):
        return self.prices.save_keys("SYNTHKEYID1", "SYNTHSECRET1")

    def test_symbols_use_alpaca_share_class_format(self):
        self.assertEqual([alpaca_symbol(s) for s in ("BRK B", "BRK-B", "brk.b", "VOO")], ["BRK.B", "BRK.B", "BRK.B", "VOO"])

    def test_keys_are_checked_before_saving_and_stored_encrypted(self):
        with self.assertRaisesRegex(PriceError, "rejected"):
            self.prices.save_keys("WRONGKEYID", "WRONGSECRET")
        self.assertFalse(self.prices.configured())
        with self.assertRaisesRegex(PriceError, "without spaces"):
            self.prices.save_keys("has space", "SYNTHSECRET1")
        self.assertEqual(self.connect()["price"], 101.5)
        self.assertTrue(self.prices.configured())
        raw = self.store.path.read_bytes()
        self.assertNotIn(b"SYNTHKEYID1", raw)
        self.assertNotIn(b"SYNTHSECRET1", raw)
        self.prices.remove_keys()
        self.assertFalse(self.prices.configured())

    def test_quotes_map_back_to_ibkr_symbols_and_are_cached_briefly(self):
        self.connect()
        quotes = self.prices.quotes(["BRK B", "VOO", "NOPE"])
        self.assertEqual(set(quotes), {"BRK B", "VOO"})
        self.assertEqual((quotes["VOO"]["price"], quotes["VOO"]["previousClose"], quotes["VOO"]["source"]), (101.5, 100.0, "IEX"))
        snapshot_call = [c for c in self.alpaca.calls if c[0] == "/v2/stocks/snapshots"][-1]
        self.assertEqual((snapshot_call[1]["symbols"], snapshot_call[1]["feed"]), ("BRK.B,NOPE,VOO", "iex"))
        calls = len(self.alpaca.calls)
        self.prices.quotes(["VOO", "NOPE", "BRK B"])
        self.assertEqual(len(self.alpaca.calls), calls)
        self.clock[0] += 16
        self.prices.quotes(["VOO", "NOPE", "BRK B"])
        self.assertEqual(len(self.alpaca.calls), calls + 1)

    def test_without_keys_prices_explain_what_to_do(self):
        with self.assertRaisesRegex(PriceError, "Settings → Prices"):
            self.prices.quotes(["VOO"])

    def test_daily_bars_follow_pages_use_old_enough_sip_data_and_cache_encrypted(self):
        self.connect()
        closes = self.prices.daily(["NVDA", "MSFT"], date(2026, 6, 1))
        self.assertEqual(closes["NVDA"]["2026-10-21"], 182.64)
        self.assertEqual(len(closes["MSFT"]), len([d for d in self.alpaca.days if d >= date(2026, 6, 1)]))
        bar_calls = [c for c in self.alpaca.calls if c[0] == "/v2/stocks/bars"]
        self.assertGreater(len(bar_calls), 1)  # 50 bars per page.
        self.assertEqual((bar_calls[0][1]["feed"], bar_calls[0][1]["end"]), ("sip", "2026-10-26T14:44:00Z"))
        calls = len(self.alpaca.calls)
        self.prices.daily(["NVDA"], date(2026, 6, 5))
        self.assertEqual(len(self.alpaca.calls), calls)  # Cached.
        self.assertNotIn(b"182.64", self.store.path.read_bytes())

    def test_portfolio_value_is_rebuilt_from_trades_and_matches_the_report(self):
        self.connect()
        history = self.prices.portfolio(self.ledger)
        days = {d["date"]: d for d in history["days"]}
        self.assertEqual(history["start"], "2026-01-02")
        self.assertEqual(days["2026-01-02"]["value"], 200000.00)   # First deposit, nothing bought yet.
        self.assertEqual(days["2026-01-05"]["value"], 228037.06)   # Second deposit.
        self.assertEqual(days["2026-01-06"]["value"], 228028.86)   # Bought at trade prices; $8.20 commission.
        self.assertEqual(days["2026-10-21"]["value"], 267128.50)   # Same total as the IBKR report.
        self.assertEqual(days["2026-01-05"]["flow"], 28037.06)
        # Deposits are not returns: growth comes only from commissions, dividends and the final price move.
        self.assertAlmostEqual(days["2026-10-21"]["twr"], 267128.50 / 228037.06 - 1, places=9)
        spy = {d: self.alpaca.close("SPY", d) for d in self.alpaca.days}
        self.assertAlmostEqual(days["2026-10-21"]["benchmark"], spy[date(2026, 10, 21)] / spy[date(2026, 1, 2)] - 1, places=9)
        self.assertEqual(history["excluded"], [])

    def test_a_missing_price_skips_the_day_rather_than_undercounting(self):
        self.connect()
        original = self.alpaca.days
        self.alpaca.days = [d for d in original if d != date(2026, 3, 2)] + []
        history = self.prices.portfolio(self.ledger)
        self.assertNotIn("2026-03-02", {d["date"] for d in history["days"]})  # No SPY bar: not a trading day here.


if __name__ == "__main__":
    main()
