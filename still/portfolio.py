"""Turn stored Flex reports into the portfolio view the workspace renders."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from ibkr.ledger import Ledger, Statement, merge, parse_ledger
from ibkr.reconcile import reconcile

ASSET_LABELS = {"STK": "Stocks & ETFs", "OPT": "Options", "FUT": "Futures", "FOP": "Futures options",
                "BOND": "Bonds", "BILL": "Bills", "FUND": "Funds", "CASH": "Currency", "CRYPTO": "Crypto",
                "WAR": "Warrants", "CFD": "CFDs"}


class PortfolioError(Exception):
    """Safe to display."""


def _rates(s: Statement, base: str) -> dict[str, Decimal]:
    """Currency → base-currency rate on the statement's last date."""
    rates = {base: Decimal(1)}
    for r in sorted(s.fx_rates, key=lambda r: r.day):
        if r.to_currency == base:
            rates[r.from_currency] = r.rate
    for p in s.positions:
        if p.fx_to_base is not None:
            rates.setdefault(p.currency, p.fx_to_base)
    return rates


def _base_currency(statements) -> str:
    bases = {s.base_currency for s in statements if s.base_currency}
    if len(bases) > 1:
        raise PortfolioError("These accounts use different base currencies; Still combines one base currency for now.")
    if bases:
        return bases.pop()
    currencies = {p.currency for s in statements for p in s.positions} | {b.currency for s in statements for b in s.cash_balances}
    if len(currencies) == 1:
        return currencies.pop()
    raise PortfolioError("Add Account Information (base currency) to the Flex query so values can be combined.")


def _snapshot(statements: list[Statement], base: str):
    """Positions and cash for one report date, aggregated across accounts."""
    positions: dict[str, dict] = {}
    cash: dict[str, Decimal] = {}
    missing_rates: set[str] = set()
    for s in statements:
        rates = _rates(s, base)
        for p in s.positions:
            fx = p.fx_to_base if p.fx_to_base is not None else rates.get(p.currency)
            if fx is None:
                missing_rates.add(p.currency)
            row = positions.setdefault(p.conid, {"p": p, "qty": Decimal(0), "basis": Decimal(0), "basisKnown": True, "fx": fx})
            row["qty"] += p.quantity
            if p.cost_basis_money is None:
                row["basisKnown"] = False
            else:
                row["basis"] += p.cost_basis_money
        for b in s.cash_balances:
            cash[b.currency] = cash.get(b.currency, Decimal(0)) + b.ending
    value = Decimal(0)
    rates = {}
    for s in statements:
        rates.update(_rates(s, base))
    for row in positions.values():
        if row["fx"] is not None:
            value += row["qty"] * row["p"].mark_price * row["p"].multiplier * row["fx"]
    unconverted = {c for c in cash if c not in rates}
    totals = [s.base_cash for s in statements]
    if unconverted and totals and all(t is not None for t in totals):
        # No rate for some currency: use IBKR's own base-currency cash total instead.
        cash_base = sum(totals, Decimal(0))
    else:
        cash_base = sum((a * rates[c] for c, a in cash.items() if c in rates), Decimal(0))
        missing_rates |= unconverted
    return positions, cash, rates, value + cash_base, missing_rates, cash_base


def _trading_day(day: date) -> date:
    """Weekend report dates carry Friday's prices; compare them as Friday."""
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _seed(conid: str) -> int:
    return sum(ord(c) * (i + 1) for i, c in enumerate(conid)) % 997 + 3


def build(reports: list[bytes], *, from_inception: bool = False) -> dict | None:
    if not reports:
        return None
    ledgers = [parse_ledger(data) for data in reports]
    combined: Ledger = merge(*ledgers)
    base = _base_currency(combined.statements)
    latest = list(combined.statements)
    as_of = max(s.to_date for s in latest)
    positions, cash, rates, value, missing, cash_base = _snapshot(latest, base)

    # History: one point per report end date; the latest report for a date wins.
    by_date: dict[date, list[Statement]] = {}
    for ledger in ledgers:
        end = max(s.to_date for s in ledger.statements)
        by_date[end] = list(ledger.statements)
    by_date[as_of] = latest
    history, marks = [], {}
    previous_marks, previous_date = {}, None
    for day in sorted(by_date):
        snap_positions, _, _, snap_value, snap_missing, _ = _snapshot(by_date[day], base)
        if not snap_missing:
            history.append({"date": day.isoformat(), "value": float(snap_value)})
        for conid, row in snap_positions.items():
            marks.setdefault(conid, []).append({"date": day.isoformat(), "price": float(row["p"].mark_price)})
        if _trading_day(day) < _trading_day(as_of):
            previous_marks = {conid: row["p"].mark_price for conid, row in snap_positions.items()}
            previous_date = day.isoformat()

    # Prefer IBKR's daily net asset value; fall back to one point per report.
    nav: dict[date, Decimal] = {}
    for s in latest:
        for day, total in s.nav:
            nav[day] = nav.get(day, Decimal(0)) + total
    history_source = "reports"
    if len(nav) >= 2:
        history = [{"date": d.isoformat(), "value": float(v)} for d, v in sorted(nav.items())]
        history_source = "nav"

    trades_by_conid: dict[str, list] = {}
    for s in latest:
        for t in sorted(s.trades, key=lambda t: (t.trade_date, t.executed_time or "")):
            trades_by_conid.setdefault(t.conid, []).append({
                "date": t.trade_date.isoformat(), "side": "Buy" if t.quantity > 0 else "Sell",
                "qty": float(abs(t.quantity)), "price": float(t.price), "currency": t.currency,
                "amount": float(-(t.proceeds + t.taxes + t.commission)) if t.commission_currency == t.currency else float(-t.proceeds),
            })
    rows = []
    def base_value(row):
        return -(row["qty"] * row["p"].mark_price * row["p"].multiplier * (row["fx"] or 0))
    for conid, row in sorted(positions.items(), key=lambda kv: (base_value(kv[1]), kv[1]["p"].symbol)):
        p, qty = row["p"], row["qty"]
        units = qty * p.multiplier
        rows.append({
            "symbol": p.symbol, "name": p.description or p.symbol, "legalName": p.description or p.symbol,
            "sector": ASSET_LABELS.get(p.asset_class, p.asset_class or "Other"), "exchange": "",
            "currency": p.currency, "conid": conid, "qty": float(qty), "price": float(p.mark_price),
            "previous": float(previous_marks[conid]) if conid in previous_marks else None,
            "cost": float(row["basis"] / units) if row["basisKnown"] and units else None,
            "multiplier": float(p.multiplier), "fx": float(row["fx"]) if row["fx"] is not None else None,
            "seed": _seed(conid), "history": marks.get(conid, []), "trades": trades_by_conid.get(conid, []),
        })
    trades = [t for s in latest for t in s.trades if t.quantity > 0]
    first_activity = min([t.trade_date for s in latest for t in s.trades] +
                         [c.day for s in latest for c in s.cash_transactions], default=None)
    result = reconcile(combined, from_inception=from_inception)
    warnings = []
    if missing:
        warnings.append("Some currencies have no conversion rate to " + base +
                        "; include Currency Conversion Rates in the Flex query. Those amounts are left out of totals.")
    return {
        "source": "ibkr", "baseCurrency": base, "asOf": as_of.isoformat(), "previousDate": previous_date,
        "accounts": [s.label for s in latest],
        "positions": rows,
        "cash": [{"currency": c, "amount": float(a), "base": float(a * rates[c]) if c in rates else None}
                 for c, a in sorted(cash.items())],
        "cashBase": float(cash_base),
        "value": float(value),
        "firstPurchase": min((t.trade_date for t in trades), default=min(s.from_date for s in latest)).isoformat(),
        "coverageStart": min(s.from_date for s in latest).isoformat(),
        "firstActivity": first_activity.isoformat() if first_activity else None,
        "history": history, "historySource": history_source,
        "reconciliation": {
            "counts": result.counts(),
            "checks": [{"name": c.name, "subject": c.subject, "status": c.status,
                        "expected": None if c.expected is None else str(c.expected),
                        "actual": None if c.actual is None else str(c.actual), "detail": c.detail}
                       for c in result.checks if c.status != "pass"],
            "notices": list(dict.fromkeys(n for s in latest for n in s.notices)),
            "fromInception": from_inception,
        },
        "warnings": warnings,
        "summary": combined.summary(),
    }
