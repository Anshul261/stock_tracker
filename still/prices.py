"""Market prices from Alpaca's market data API, with the owner's own keys.

Alpaca's free plan gives real-time quotes from the IEX exchange and daily bars
from all US exchanges (the consolidated "SIP" feed) once they are at least 15
minutes old. Keys stay in the encrypted vault and go only to data.alpaca.markets.
Fetched prices are cached encrypted too: the list of symbols reveals holdings.

Daily portfolio value is rebuilt from the IBKR ledger: holdings and cash on each
day are worked back from the latest report through every trade, split and cash
movement, then valued at that day's closing price. Deposits and withdrawals are
kept apart so the time-weighted return and the S&P 500 comparison exclude them.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from threading import RLock
from typing import Callable
from urllib.parse import urlencode
import json
import re
import ssl
import time
import urllib.error
import urllib.request

from ibkr.ledger import SPLITS, ZERO, Ledger

from .portfolio import _base_currency, _rates

BASE = "https://data.alpaca.markets"
MAX_BYTES = 8 * 1024 * 1024
QUOTE_TTL, BARS_TTL = 15.0, 6 * 3600.0
BENCHMARK = "SPY"
PRICEABLE = frozenset({"STK"})  # US-listed stocks and ETFs; Alpaca has no bonds, options or funds data here.
RANGES = {"1M": 31, "3M": 92, "1Y": 366, "5Y": 5 * 366}
ERRORS = {401: "Alpaca rejected the API key ID or secret. Check them in Settings → Prices.",
          403: "Alpaca's plan for these keys doesn't allow this request.",
          422: "Alpaca couldn't serve this request.",
          429: "Alpaca's rate limit was reached; prices refresh again shortly."}


class PriceError(Exception):
    """Safe to display: never includes keys or response bodies."""


def alpaca_symbol(symbol: str) -> str:
    """IBKR writes share classes as "BRK B" and SEC as "BRK-B"; Alpaca uses "BRK.B"."""
    return re.sub(r"[\s/-]+", ".", (symbol or "").strip().upper())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def fetch(path: str, params: dict, key_id: str, secret: str) -> bytes:
    request = urllib.request.Request(BASE + path + "?" + urlencode(params), headers={
        "APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret, "Accept": "application/json", "User-Agent": "Still/0.1"})
    opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=15) as response:
            data = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        raise PriceError(ERRORS.get(status, f"Alpaca returned an error (HTTP {status}); try again later.")) from None
    except Exception:
        raise PriceError("Alpaca could not be reached; check your internet connection.") from None
    if len(data) > MAX_BYTES:
        raise PriceError("Alpaca sent more data than expected.")
    return data


def valid_key(value, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9]{8,128}", value.strip()):
        raise PriceError(f"Paste your Alpaca {label} exactly as shown, without spaces.")
    return value.strip()


class Prices:
    def __init__(self, store, auth, *, transport: Callable = fetch, clock: Callable[[], float] = time.time,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.store, self.auth = store, auth
        self.transport, self.clock, self.now = transport, clock, now
        self.lock = RLock()
        self.cache: dict | None = None
        self.quote_cache: dict[tuple, tuple[float, dict]] = {}

    # Keys -------------------------------------------------------------------
    def configured(self) -> bool:
        return self.store.has_secret("prices.alpaca.key") and self.store.has_secret("prices.alpaca.secret")

    def _keys(self) -> tuple[str, str]:
        key = self.auth.key
        if key is None:
            raise PriceError("Unlock Still first.")
        key_id, secret = self.store.secret(key, "prices.alpaca.key"), self.store.secret(key, "prices.alpaca.secret")
        if not key_id or not secret:
            raise PriceError("Add your Alpaca API key in Settings → Prices to see live prices and history.")
        return key_id, secret

    def _get(self, path: str, params: dict, keys: tuple[str, str] | None = None) -> dict:
        try:
            data = json.loads(self.transport(path, params, *(keys or self._keys())))
        except ValueError:
            raise PriceError("Alpaca sent an unexpected response.") from None
        if not isinstance(data, dict):
            raise PriceError("Alpaca sent an unexpected response.")
        return data

    def save_keys(self, key_id, secret) -> dict:
        keys = (valid_key(key_id, "API key ID"), valid_key(secret, "secret key"))
        quote = self._snapshots([BENCHMARK], keys)  # Prove the keys work before saving them.
        self.store.set_secret(self.auth.key, "prices.alpaca.key", keys[0])
        self.store.set_secret(self.auth.key, "prices.alpaca.secret", keys[1])
        self.store.set_setting("pricesSavedAt", date.today().isoformat())
        self.quote_cache.clear()
        return quote.get(BENCHMARK, {})

    def remove_keys(self) -> None:
        for name in ("prices.alpaca.key", "prices.alpaca.secret", "prices.cache"):
            self.store.set_secret(self.auth.key, name, None)
        self.store.set_setting("pricesSavedAt", None)
        self.cache, self.quote_cache = None, {}

    # Live quotes ------------------------------------------------------------
    def _snapshots(self, symbols: list[str], keys=None) -> dict:
        mapping = {alpaca_symbol(s): s for s in symbols}
        data = self._get("/v2/stocks/snapshots", {"symbols": ",".join(mapping), "feed": "iex"}, keys)
        result = {}
        for symbol, snap in data.items():
            original = mapping.get(symbol)
            if not original or not isinstance(snap, dict):
                continue
            trade, previous = snap.get("latestTrade") or {}, snap.get("prevDailyBar") or {}
            price = trade.get("p")
            if not isinstance(price, (int, float)) or price <= 0:
                continue
            prev_close = previous.get("c")
            result[original] = {
                "price": float(price), "time": trade.get("t") if isinstance(trade.get("t"), str) else None,
                "previousClose": float(prev_close) if isinstance(prev_close, (int, float)) and prev_close > 0 else None,
                "previousDate": previous.get("t", "")[:10] if isinstance(previous.get("t"), str) else None,
                "source": "IEX",
            }
        return result

    def quotes(self, symbols) -> dict:
        symbols = sorted({s for s in symbols if isinstance(s, str) and s.strip()})[:100]
        if not symbols:
            return {}
        key = tuple(symbols)
        with self.lock:
            hit = self.quote_cache.get(key)
            if hit and self.clock() - hit[0] < QUOTE_TTL:
                return hit[1]
        result = self._snapshots(symbols)
        with self.lock:
            self.quote_cache[key] = (self.clock(), result)
            if len(self.quote_cache) > 32:
                self.quote_cache.pop(next(iter(self.quote_cache)))
        return result

    # Daily bars, cached encrypted --------------------------------------------
    def _load(self) -> dict:
        if self.cache is None:
            raw = self.store.secret(self.auth.key, "prices.cache") if self.auth.key else None
            try:
                self.cache = json.loads(raw) if raw else {}
            except ValueError:
                self.cache = {}
        return self.cache

    def daily(self, symbols, start: date, adjustment: str = "raw") -> dict[str, dict[str, float]]:
        """Closing price by ISO date for each symbol, from `start` to the latest completed bar."""
        with self.lock:
            cache = self._load().setdefault(adjustment, {})
            need = [s for s in dict.fromkeys(symbols)
                    if s not in cache or cache[s]["start"] > start.isoformat() or self.clock() - cache[s]["fetched"] > BARS_TTL]
            if need:
                begin = min([start] + [date.fromisoformat(cache[s]["start"]) for s in need if s in cache])
                end = self.now() - timedelta(minutes=16)  # The free plan serves SIP data that is 15+ minutes old.
                mapping = {alpaca_symbol(s): s for s in need}
                params = {"symbols": ",".join(mapping), "timeframe": "1Day", "start": begin.isoformat(),
                          "end": end.isoformat(timespec="seconds").replace("+00:00", "Z"),
                          "adjustment": adjustment, "feed": "sip", "limit": 10000, "sort": "asc"}
                bars: dict[str, dict[str, float]] = defaultdict(dict)
                for _ in range(100):
                    data = self._get("/v2/stocks/bars", params)
                    for symbol, rows in (data.get("bars") or {}).items():
                        for row in rows or []:
                            if isinstance(row, dict) and isinstance(row.get("c"), (int, float)) and isinstance(row.get("t"), str):
                                bars[mapping.get(symbol, symbol)][row["t"][:10]] = float(row["c"])
                    token = data.get("next_page_token")
                    if not token:
                        break
                    params["page_token"] = token
                else:  # Never chart a silently truncated history.
                    raise PriceError("Alpaca returned more price history than Still can load at once.")
                for s in need:
                    cache[s] = {"start": begin.isoformat(), "fetched": self.clock(), "bars": bars.get(s, {})}
                self.store.set_secret(self.auth.key, "prices.cache", json.dumps(self.cache))
            return {s: cache[s]["bars"] for s in symbols if s in cache}

    def history(self, symbol: str, range_key: str) -> list[dict]:
        today = self.now().date()
        start = (date(today.year, 1, 1) if range_key == "YTD" else date(2016, 1, 1) if range_key == "ALL"
                 else today - timedelta(days=RANGES.get(range_key, 366)))
        closes = self.daily([symbol], start, "split").get(symbol, {})
        return [{"date": d, "close": c} for d, c in sorted(closes.items()) if d >= start.isoformat()]

    def portfolio(self, ledger: Ledger | None) -> dict:
        if ledger is None or not ledger.statements:
            raise PriceError("Import an IBKR report first.")
        timeline = Timeline(ledger)
        if timeline.start is None:
            raise PriceError("The imported reports have no trades or cash movements to chart yet.")
        raw = self.daily(timeline.symbols(), timeline.start, "raw")
        benchmark = self.daily([BENCHMARK], timeline.start, "all").get(BENCHMARK, {})
        return timeline.values(raw, benchmark)


class Timeline:
    """Holdings and cash on any day, worked back from the latest report."""

    def __init__(self, ledger: Ledger):
        self.base = _base_currency(ledger.statements)
        self.instruments: dict[str, tuple] = {}      # conid -> (symbol, multiplier, currency, asset class)
        self.end_qty: dict[str, Decimal] = defaultdict(Decimal)
        self.qty_moves: dict[str, list] = defaultdict(list)
        self.cash_end: dict[str, Decimal] = defaultdict(Decimal)
        self.cash_moves: dict[str, list] = defaultdict(list)
        self.flows: list[tuple[date, str, Decimal]] = []
        self.rates: dict[str, Decimal] = {}
        days = []
        for s in ledger.statements:
            self.rates.update(_rates(s, self.base))
            for p in s.positions:
                self.instruments[p.conid] = (p.symbol, p.multiplier, p.currency, p.asset_class)
                self.end_qty[p.conid] += p.quantity
            for t in s.trades:
                days.append(t.trade_date)
                if t.asset_class == "CASH":
                    bought, paid = t.symbol.split(".")
                    self.cash_moves[bought].append((t.trade_date, t.quantity))
                    self.cash_moves[paid].append((t.trade_date, t.proceeds + t.taxes))
                else:
                    self.instruments.setdefault(t.conid, (t.symbol, t.multiplier, t.currency, t.asset_class))
                    self.qty_moves[t.conid].append((t.trade_date, t.quantity))
                    self.cash_moves[t.currency].append((t.trade_date, t.proceeds + t.taxes))
                self.cash_moves[t.commission_currency].append((t.trade_date, t.commission))
            for c in s.cash_transactions:
                days.append(c.day)
                self.cash_moves[c.currency].append((c.day, c.amount))
                if c.kind == "deposit_withdrawal":
                    self.flows.append((c.day, c.currency, c.amount))
            for a in s.corporate_actions:
                if a.type in SPLITS:
                    self.qty_moves[a.conid].append((a.day, a.quantity))
                if a.proceeds:
                    self.cash_moves[a.currency].append((a.day, a.proceeds))
            for b in s.cash_balances:
                self.cash_end[b.currency] += b.ending
        # A currency without a conversion rate: derive it from IBKR's own base-currency cash total.
        missing = [c for c, amount in self.cash_end.items() if c not in self.rates and amount]
        totals = [s.base_cash for s in ledger.statements]
        if len(missing) == 1 and totals and all(t is not None for t in totals):
            known = sum((amount * self.rates[c] for c, amount in self.cash_end.items() if c in self.rates), ZERO)
            self.rates[missing[0]] = (sum(totals, ZERO) - known) / self.cash_end[missing[0]]
        self.start = min(days) if days else None

    def priceable(self, conid: str) -> bool:
        _, _, currency, asset = self.instruments[conid]
        return asset in PRICEABLE and currency == "USD"

    def symbols(self) -> list[str]:
        return sorted({self.instruments[c][0] for c in self.instruments if self.priceable(c)})

    @staticmethod
    def _at(end: Decimal, moves: list, day: date) -> Decimal:
        return end - sum((q for d, q in moves if d > day), ZERO)

    def values(self, closes: dict[str, dict[str, float]], benchmark: dict[str, float]) -> dict:
        days = sorted(d for d in benchmark if d >= self.start.isoformat())
        if not days:
            raise PriceError("Alpaca returned no S&P 500 prices for this period.")
        excluded = sorted({self.instruments[c][0] for c in self.instruments
                           if not self.priceable(c) and (self.end_qty[c] or self.qty_moves[c])})
        unrated = sorted(c for c in self.cash_moves if c not in self.rates)
        last: dict[str, float] = {}
        points, index, previous, bench_start = [], Decimal(1), None, None
        for iso in days:
            day = date.fromisoformat(iso)
            for symbol, series in closes.items():
                if iso in series:
                    last[symbol] = series[iso]
            value, complete = ZERO, True
            for conid, (symbol, multiplier, currency, _) in self.instruments.items():
                quantity = self._at(self.end_qty[conid], self.qty_moves[conid], day)
                if not quantity or not self.priceable(conid):
                    continue
                if symbol not in last:
                    complete = False  # Held before Alpaca has a price for it.
                    continue
                value += quantity * Decimal(str(last[symbol])) * multiplier
            for currency in set(self.cash_end) | set(self.cash_moves):
                if currency in self.rates:
                    value += self._at(self.cash_end[currency], self.cash_moves[currency], day) * self.rates[currency]
            flow = sum((amount * self.rates[c] for d, c, amount in self.flows if d == day and c in self.rates), ZERO)
            if not complete:
                continue
            if previous and previous > 0:
                index *= (value - flow) / previous
            if bench_start is None and value > 0:
                bench_start = Decimal(str(benchmark[iso]))
            if value > 0 or previous:
                points.append({"date": iso, "value": float(round(value, 2)), "flow": float(round(flow, 2)),
                               "twr": float(index - 1) if bench_start else 0.0,
                               "benchmark": float(Decimal(str(benchmark[iso])) / bench_start - 1) if bench_start else 0.0})
                previous = value
        if not points:
            raise PriceError("There isn't enough price data to chart your portfolio yet.")
        return {"days": points, "excluded": excluded, "unratedCurrencies": unrated, "benchmark": BENCHMARK,
                "baseCurrency": self.base, "start": points[0]["date"], "end": points[-1]["date"]}
