"""Reconcile a normalized ledger against itself and against a reference snapshot.

Every check is one of: pass, fail, or unverified (inputs are incomplete, or the
report holds activity that is not modeled yet). Unverified is never shown as pass.
Cost basis is recomputed with FIFO lots, IBKR's default tax-lot method.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping

from .ledger import SPLITS, ZERO, Ledger, Statement

CENT = Decimal("0.01")
HALF_CENT = Decimal("0.005")


@dataclass(frozen=True)
class Check:
    name: str                 # position_value, trade_net_cash, quantity, cash, cost_basis, realized_pnl, reference_*
    subject: str              # Symbol or currency, prefixed with a masked account when several exist.
    status: str               # pass, fail or unverified
    expected: Decimal | None = None
    actual: Decimal | None = None
    detail: str = ""

    @property
    def difference(self) -> Decimal | None:
        if self.expected is None or self.actual is None:
            return None
        return self.actual - self.expected


@dataclass(frozen=True)
class Reconciliation:
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return not any(c.status == "fail" for c in self.checks)

    def counts(self) -> dict[str, int]:
        result = {"pass": 0, "fail": 0, "unverified": 0}
        for c in self.checks:
            result[c.status] += 1
        return result


@dataclass(frozen=True)
class ExpectedHolding:
    """An independent reference, e.g. a statement the owner trusts. Matched by symbol."""
    symbol: str
    quantity: Decimal
    mark_price: Decimal | None = None
    average_price: Decimal | None = None   # Mean purchase price, excluding fees.


def _half_unit(value: Decimal) -> Decimal:
    return Decimal(1).scaleb(value.as_tuple().exponent) / 2


def _compare(name, subject, expected, actual, tolerance, doubt="", detail="") -> Check:
    if expected is None or actual is None:
        return Check(name, subject, "unverified", expected, actual, detail or "A required value is missing.")
    if abs(actual - expected) <= tolerance:
        return Check(name, subject, "pass", expected, actual, detail)
    if doubt:
        return Check(name, subject, "unverified", expected, actual, f"Differs, but the report includes {doubt}.")
    return Check(name, subject, "fail", expected, actual, detail)


def _symbols(s: Statement) -> dict[str, str]:
    names: dict[str, str] = {}
    for row in (*s.trades, *s.corporate_actions, *s.positions):
        names.setdefault(row.conid, row.symbol)
    return names


def _events(s: Statement):
    """Trades and splits in time order; same-day splits apply before trades."""
    rows = [(a.day, "", 0, i, a) for i, a in enumerate(s.corporate_actions)]
    rows += [(t.trade_date, t.executed_time or "", 1, i, t) for i, t in enumerate(s.trades) if t.asset_class != "CASH"]
    return [row[-1] for row in sorted(rows, key=lambda r: r[:4])]


def reconcile_statement(s: Statement, *, from_inception: bool = False,
                        opening: Mapping[str, Decimal] | None = None, prefix: str = "") -> list[Check]:
    """Check one statement. Without from_inception or opening quantities, the
    quantity and cost-basis checks are unverified: the starting holdings are unknown."""
    if from_inception and opening:
        raise ValueError("Use from_inception or opening quantities, not both.")
    known_opening = {} if from_inception else opening
    doubt = ", ".join(s.unmodeled)
    names = _symbols(s)
    checks: list[Check] = []

    for p in s.positions:
        tolerance = Decimal("0.005") + abs(p.quantity * p.multiplier) * _half_unit(p.mark_price)
        checks.append(_compare("position_value", prefix + p.symbol, p.quantity * p.mark_price * p.multiplier,
                               p.position_value, tolerance))

    for t in s.trades:
        if t.net_cash is not None and t.commission_currency == t.currency:
            checks.append(_compare("trade_net_cash", prefix + t.symbol, t.proceeds + t.taxes + t.commission,
                                   t.net_cash, CENT, detail="Net cash should equal proceeds + taxes + commission."))

    # Quantity rollforward: opening + trades + splits = closing.
    flows: dict[str, Decimal] = defaultdict(Decimal)
    other_actions = set()
    for event in _events(s):
        if hasattr(event, "side"):
            flows[event.conid] += event.quantity
        elif event.type in SPLITS:
            flows[event.conid] += event.quantity
        else:
            other_actions.add(event.conid)
    closing = {p.conid: p.quantity for p in s.positions}
    for conid in sorted(set(flows) | set(closing)):
        subject = prefix + names.get(conid, conid)
        if conid in other_actions:
            checks.append(Check("quantity", subject, "unverified", detail="A corporate action that is not a split affects this instrument."))
        elif known_opening is None:
            checks.append(Check("quantity", subject, "unverified", None, closing.get(conid, ZERO),
                                "Opening position unknown; pass from_inception or opening quantities."))
        else:
            checks.append(_compare("quantity", subject, known_opening.get(conid, ZERO) + flows[conid],
                                   closing.get(conid, ZERO), ZERO, doubt))

    # Cash rollforward per currency: starting + movements = ending.
    movement: dict[str, Decimal] = defaultdict(Decimal)
    for t in s.trades:
        if t.asset_class == "CASH":
            base, quote = t.symbol.split(".")
            movement[base] += t.quantity
            movement[quote] += t.proceeds + t.taxes
        else:
            movement[t.currency] += t.proceeds + t.taxes
        movement[t.commission_currency] += t.commission
    for c in s.cash_transactions:
        movement[c.currency] += c.amount
    for a in s.corporate_actions:
        movement[a.currency] += a.proceeds or ZERO
    balances = {b.currency: b for b in s.cash_balances}
    for currency in sorted(set(movement) | set(balances)):
        b = balances.get(currency)
        if b is None:
            checks.append(Check("cash", prefix + currency, "unverified", detail="No Cash Report row for this currency."))
            continue
        # Rows can carry sub-cent commissions while balances are rounded to cents.
        checks.append(_compare("cash", prefix + currency, b.starting + movement[currency], b.ending, HALF_CENT, doubt))

    checks += _cost_basis(s, known_opening, other_actions, doubt, names, prefix)
    return checks


def _cost_basis(s, known_opening, other_actions, doubt, names, prefix) -> list[Check]:
    if known_opening is None:
        return [Check("cost_basis", prefix + p.symbol, "unverified", None, p.cost_basis_money,
                      "Purchase history before the report is unknown.") for p in s.positions]
    lots: dict[str, list[list[Decimal]]] = defaultdict(list)   # conid -> [[quantity, cost]]
    sells: dict[str, int] = defaultdict(int)
    broken: dict[str, str] = {c: "A corporate action that is not a split affects this instrument." for c in other_actions}
    for conid, quantity in known_opening.items():
        if quantity:
            broken[conid] = "Opening lots have no recorded cost."
    checks: list[Check] = []
    for event in _events(s):
        conid = event.conid
        if conid in broken:
            continue
        held = sum(q for q, _ in lots[conid])
        if not hasattr(event, "side"):
            if event.type in SPLITS:
                if held <= 0:
                    broken[conid] = "Split recorded without an open long position."
                    continue
                ratio = (held + event.quantity) / held
                lots[conid] = [[q * ratio, cost] for q, cost in lots[conid]]
            continue
        if event.commission_currency != event.currency:
            broken[conid] = "Commission is charged in a different currency."
            continue
        # IBKR sign convention: purchases have negative proceeds; charges are negative.
        cash = event.proceeds + event.taxes + event.commission
        if event.quantity > 0:
            lots[conid].append([event.quantity, -cash])
            continue
        if -event.quantity > held:
            broken[conid] = "Short positions are not modeled."
            continue
        remaining, removed = -event.quantity, ZERO
        while remaining and lots[conid]:
            quantity, cost = lots[conid][0]
            take = min(quantity, remaining)
            share = cost * take / quantity
            removed += share
            remaining -= take
            if take == quantity:
                lots[conid].pop(0)
            else:
                lots[conid][0] = [quantity - take, cost - share]
        sells[conid] += 1
        if event.fifo_pnl_realized is not None:
            checks.append(_compare("realized_pnl", prefix + event.symbol, cash - removed,
                                   event.fifo_pnl_realized, CENT, doubt))
    for p in s.positions:
        subject = prefix + p.symbol
        if p.conid in broken:
            checks.append(Check("cost_basis", subject, "unverified", None, p.cost_basis_money, broken[p.conid]))
            continue
        computed = sum((cost for _, cost in lots[p.conid]), ZERO)
        checks.append(_compare("cost_basis", subject, computed, p.cost_basis_money,
                               CENT * (1 + sells[p.conid]), doubt))
    return checks


def reconcile(ledger: Ledger, *, from_inception: bool = False) -> Reconciliation:
    several = len(ledger.statements) > 1
    checks: list[Check] = []
    for s in ledger.statements:
        checks += reconcile_statement(s, from_inception=from_inception,
                                      prefix=f"{s.label} " if several else "")
    return Reconciliation(tuple(checks))


def compare_holdings(s: Statement, expected: Iterable[ExpectedHolding],
                     cash: Mapping[str, Decimal] | None = None) -> Reconciliation:
    """Compare a statement with an independent snapshot, by symbol."""
    expected = list(expected)
    by_symbol: dict[str, list] = defaultdict(list)
    for p in s.positions:
        by_symbol[p.symbol].append(p)
    checks: list[Check] = []
    for e in expected:
        found = by_symbol.get(e.symbol, [])
        if len(found) != 1:
            checks.append(Check("reference_quantity", e.symbol, "fail", e.quantity, None,
                                "Missing from the report." if not found else "Symbol matches several instruments."))
            continue
        p = found[0]
        checks.append(_compare("reference_quantity", e.symbol, e.quantity, p.quantity, ZERO))
        if e.mark_price is not None:
            checks.append(_compare("reference_price", e.symbol, e.mark_price, p.mark_price, ZERO))
        if e.average_price is not None:
            buys = [t for t in s.trades if t.conid == p.conid and t.quantity > 0]
            bought = sum((t.quantity for t in buys), ZERO)
            average = sum((t.quantity * t.price for t in buys), ZERO) / bought if bought else None
            checks.append(_compare("reference_average_price", e.symbol, e.average_price, average,
                                   _half_unit(e.average_price)))
    listed = {e.symbol for e in expected}
    for symbol in sorted(set(by_symbol) - listed):
        checks.append(Check("reference_quantity", symbol, "fail", None, by_symbol[symbol][0].quantity,
                            "In the report but not in the reference."))
    balances = {b.currency: b.ending for b in s.cash_balances}
    for currency, amount in (cash or {}).items():
        checks.append(_compare("reference_cash", currency, amount, balances.get(currency), ZERO))
    return Reconciliation(tuple(checks))
