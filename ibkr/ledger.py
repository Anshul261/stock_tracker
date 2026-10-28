"""Normalize an Activity Flex XML report into a Decimal ledger.

Strict by design: required fields must be present and well formed, money stays
Decimal with its reported currency, and personal Account Information fields
(name, addresses, date of birth, email) are never read. Error messages name the
section, row and field, never the broker-supplied value.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re
import unicodedata
import xml.etree.ElementTree as ET

from .flex import FlexError, parse_xml, validate_report

ZERO = Decimal(0)

# Normalized (alphanumeric, lower-case) IBKR cash transaction types.
CASH_KINDS = {
    "depositswithdrawals": "deposit_withdrawal",
    "depositsandwithdrawals": "deposit_withdrawal",
    "dividends": "dividend",
    "paymentinlieuofdividends": "payment_in_lieu",
    "withholdingtax": "withholding_tax",
    "871mwithholding": "withholding_tax",
    "brokerinterestreceived": "interest",
    "brokerinterestpaid": "interest",
    "bondinterestreceived": "interest",
    "bondinterestpaid": "interest",
    "otherfees": "fee",
    "advisorfees": "fee",
    "commissionadjustments": "fee",
}
SPLITS = frozenset({"FS", "RS"})  # Forward and reverse splits change quantity, not cost.
# Sections that move positions or cash but are not normalized yet. Their presence
# downgrades affected reconciliation failures to "unverified".
UNMODELED_SECTIONS = {"Transfers": "transfers", "OptionEAE": "option exercises/assignments"}


class LedgerError(FlexError):
    """Safe to display: names the section and field, never the broker value."""


def mask_account(account: str) -> str:
    return "•••" + account[-3:] if len(account) > 3 else "•••"


def clean_text(value: str | None, limit: int = 200) -> str:
    # Broker text is display data: drop control/format characters and collapse
    # whitespace. HTML is left as literal text; the UI escapes it on output.
    kept = "".join(" " if unicodedata.category(c)[0] == "C" else c for c in value or "")
    return " ".join(kept.split())[:limit]


_DATE = re.compile(r"(\d{4})(\d{2})(\d{2})|(\d{4})-(\d{2})-(\d{2})")
_TIME = re.compile(r"(\d{2}):?(\d{2}):?(\d{2})")
_CURRENCY = re.compile(r"[A-Z]{3}")


def _parse_date(value: str) -> date | None:
    match = _DATE.fullmatch(value)
    if not match:
        return None
    parts = [int(p) for p in match.groups() if p is not None]
    try:
        return date(*parts)
    except ValueError:
        return None


class _Row:
    def __init__(self, element: ET.Element, section: str, index: int):
        self.element, self.section, self.index = element, section, index

    def fail(self, name: str, problem: str):
        raise LedgerError(f"{self.section} row {self.index}: {name} {problem}.")

    def raw(self, name: str, required: bool = True) -> str | None:
        value = (self.element.get(name) or "").strip()
        if not value and required:
            self.fail(name, "is missing; include it in the Flex query")
        return value or None

    def text(self, name: str, limit: int = 200) -> str:
        return clean_text(self.element.get(name), limit)

    def decimal(self, name: str, required: bool = True) -> Decimal | None:
        value = self.raw(name, required)
        if value is None:
            return None
        try:
            number = Decimal(value)
        except InvalidOperation:
            self.fail(name, "is not a plain number")
        if not number.is_finite():
            self.fail(name, "is not a finite number")
        return number

    def day(self, name: str, required: bool = True) -> date | None:
        value = self.raw(name, required)
        if value is None:
            return None
        parsed = _parse_date(value)
        if parsed is None:
            self.fail(name, "is not a date; set the Flex query date format to yyyyMMdd or yyyy-MM-dd")
        return parsed

    def moment(self, name: str, required: bool = True) -> tuple[date | None, str | None]:
        """Return (date, 'HH:MM:SS' or None). Times stay in the zone IBKR reported."""
        value = self.raw(name, required)
        if value is None:
            return None, None
        match = re.fullmatch(r"([0-9-]{8,10})(?:[;, T]([0-9:]{6,8}))?", value)
        parsed = _parse_date(match[1]) if match else None
        clock = match[2] if match else None
        time_match = _TIME.fullmatch(clock) if clock else None
        if parsed is None or (clock and not time_match):
            self.fail(name, "is not a date/time; use yyyyMMdd;HHmmss or yyyy-MM-dd;HH:mm:ss")
        if time_match and not (int(time_match[1]) < 24 and int(time_match[2]) < 60 and int(time_match[3]) < 60):
            self.fail(name, "has an invalid time")
        return parsed, ":".join(time_match.groups()) if time_match else None

    def currency(self, name: str = "currency") -> str:
        value = self.raw(name)
        if not _CURRENCY.fullmatch(value):
            self.fail(name, "is not a three-letter currency code")
        return value

    def identifier(self, name: str, required: bool = True) -> str | None:
        value = self.raw(name, required)
        if value is not None and not re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", value):
            self.fail(name, "is not a valid identifier")
        return value


@dataclass(frozen=True)
class Trade:
    account: str = field(repr=False)
    transaction_id: str = field(repr=False)
    conid: str
    symbol: str
    description: str
    asset_class: str
    currency: str
    trade_date: date
    executed_time: str | None
    settle_date: date | None
    side: str
    quantity: Decimal          # Signed: positive buys, negative sells.
    price: Decimal
    multiplier: Decimal
    proceeds: Decimal          # In `currency`; negative for purchases.
    commission: Decimal        # In `commission_currency`; negative for charges.
    commission_currency: str
    taxes: Decimal
    net_cash: Decimal | None   # IBKR's own net cash in `currency`, when included.
    fx_to_base: Decimal | None
    open_close: str | None
    fifo_pnl_realized: Decimal | None
    notes: str


@dataclass(frozen=True)
class CashTransaction:
    account: str = field(repr=False)
    transaction_id: str = field(repr=False)
    kind: str                  # Normalized; see CASH_KINDS. Unrecognized types are "other".
    reported_type: str
    day: date
    settle_date: date | None
    amount: Decimal
    currency: str
    conid: str | None
    symbol: str | None
    description: str
    fx_to_base: Decimal | None


@dataclass(frozen=True)
class Position:
    account: str = field(repr=False)
    conid: str
    symbol: str
    description: str
    asset_class: str
    currency: str
    report_date: date | None
    quantity: Decimal
    mark_price: Decimal
    multiplier: Decimal
    position_value: Decimal
    cost_basis_price: Decimal | None
    cost_basis_money: Decimal | None
    fx_to_base: Decimal | None
    level: str                 # SUMMARY, or LOT for open tax lots.


@dataclass(frozen=True)
class CashBalance:
    account: str = field(repr=False)
    currency: str
    from_date: date | None
    to_date: date | None
    starting: Decimal
    ending: Decimal


@dataclass(frozen=True)
class CorporateAction:
    account: str = field(repr=False)
    transaction_id: str = field(repr=False)
    conid: str
    symbol: str
    description: str
    type: str
    day: date
    quantity: Decimal
    proceeds: Decimal | None
    currency: str


@dataclass(frozen=True)
class FxRate:
    day: date
    from_currency: str
    to_currency: str
    rate: Decimal


@dataclass(frozen=True)
class Statement:
    account: str = field(repr=False)
    from_date: date
    to_date: date
    base_currency: str | None
    trades: tuple[Trade, ...] = ()
    cash_transactions: tuple[CashTransaction, ...] = ()
    positions: tuple[Position, ...] = ()
    lots: tuple[Position, ...] = ()
    cash_balances: tuple[CashBalance, ...] = ()
    corporate_actions: tuple[CorporateAction, ...] = ()
    fx_rates: tuple[FxRate, ...] = ()
    unmodeled: tuple[str, ...] = ()   # Present sections not normalized yet.
    notices: tuple[str, ...] = ()     # Safe, value-free review notes.
    base_cash: Decimal | None = None  # IBKR's own total of all cash, converted to the base currency.
    nav: tuple[tuple[date, Decimal], ...] = ()  # Daily net asset value in base currency, when included.

    @property
    def label(self) -> str:
        return mask_account(self.account)


@dataclass(frozen=True)
class Ledger:
    statements: tuple[Statement, ...]

    def summary(self) -> dict[str, int]:
        """Counts only: safe to print without revealing holdings or amounts."""
        s = self.statements
        return {
            "statements": len(s),
            "trades": sum(len(x.trades) for x in s),
            "cash_transactions": sum(len(x.cash_transactions) for x in s),
            "positions": sum(len(x.positions) for x in s),
            "corporate_actions": sum(len(x.corporate_actions) for x in s),
            "currencies": len({b.currency for x in s for b in x.cash_balances}),
        }


def _rows(statement: ET.Element, section: str, tag: str) -> list[_Row]:
    container = statement.find(section)
    if container is None:
        return []
    return [_Row(el, section, i) for i, el in enumerate(container.findall(tag), 1)]


def _account(row: _Row, account: str) -> str:
    value = row.raw("accountId", required=False)
    if value is not None and value != account:
        row.fail("accountId", "does not match its statement")
    return account


def _unique(items, section: str, key=lambda item: item.transaction_id):
    """Drop exact repeats; refuse rows that reuse an ID with different content."""
    seen: dict = {}
    for item in items:
        k = (item.account, key(item))
        if k in seen and seen[k] != item:
            raise LedgerError(f"{section}: two rows share a transaction ID but differ. "
                              "Review amendments or cancellations before importing.")
        seen.setdefault(k, item)
    return tuple(seen.values())


def _trade(row: _Row, account: str) -> Trade:
    asset = row.raw("assetCategory")
    symbol = row.text("symbol", 64)
    side = row.raw("buySell")
    quantity = row.decimal("quantity")
    if side not in ("BUY", "SELL"):
        row.fail("buySell", "must be BUY or SELL")
    if quantity == 0 or (quantity > 0) != (side == "BUY"):
        row.fail("quantity", "sign does not match buySell")
    if asset == "CASH" and not re.fullmatch(r"[A-Z]{3}\.[A-Z]{3}", symbol):
        row.fail("symbol", "must be a currency pair such as EUR.USD for a CASH trade")
    currency = row.currency()
    if asset == "CASH" and symbol.split(".")[1] != currency:
        row.fail("currency", "must be the quote currency of a CASH trade")
    day, clock = row.moment("dateTime", required=False)
    return Trade(
        account=_account(row, account), transaction_id=row.identifier("transactionID"),
        conid=row.identifier("conid"), symbol=symbol, description=row.text("description"),
        asset_class=asset, currency=currency, trade_date=row.day("tradeDate"),
        executed_time=clock, settle_date=row.day("settleDateTarget", required=False),
        side=side, quantity=quantity, price=row.decimal("tradePrice"),
        multiplier=row.decimal("multiplier", required=False) or Decimal(1),
        proceeds=row.decimal("proceeds"), commission=row.decimal("ibCommission"),
        commission_currency=row.currency("ibCommissionCurrency"),
        taxes=row.decimal("taxes", required=False) or ZERO,
        net_cash=row.decimal("netCash", required=False),
        fx_to_base=row.decimal("fxRateToBase", required=False),
        open_close=row.raw("openCloseIndicator", required=False),
        fifo_pnl_realized=row.decimal("fifoPnlRealized", required=False),
        notes=row.text("notes", 64),
    )


def _cash(row: _Row, account: str) -> CashTransaction:
    reported = row.text("type", 80)
    if not reported:
        row.fail("type", "is missing; include it in the Flex query")
    day, _ = row.moment("dateTime")
    return CashTransaction(
        account=_account(row, account), transaction_id=row.identifier("transactionID"),
        kind=CASH_KINDS.get(re.sub(r"[^a-z0-9]", "", reported.lower()), "other"),
        reported_type=reported, day=day, settle_date=row.day("settleDate", required=False),
        amount=row.decimal("amount"), currency=row.currency(),
        conid=row.identifier("conid", required=False), symbol=row.text("symbol", 64) or None,
        description=row.text("description"), fx_to_base=row.decimal("fxRateToBase", required=False),
    )


def _position(row: _Row, account: str) -> Position:
    return Position(
        account=_account(row, account), conid=row.identifier("conid"),
        symbol=row.text("symbol", 64), description=row.text("description"),
        asset_class=row.raw("assetCategory", required=False) or "",
        currency=row.currency(), report_date=row.day("reportDate", required=False),
        quantity=row.decimal("position"), mark_price=row.decimal("markPrice"),
        multiplier=row.decimal("multiplier", required=False) or Decimal(1),
        position_value=row.decimal("positionValue"),
        cost_basis_price=row.decimal("costBasisPrice", required=False),
        cost_basis_money=row.decimal("costBasisMoney", required=False),
        fx_to_base=row.decimal("fxRateToBase", required=False),
        level=row.raw("levelOfDetail", required=False) or "SUMMARY",
    )


def _corporate_action(row: _Row, account: str) -> CorporateAction:
    day, _ = row.moment("dateTime", required=False)
    return CorporateAction(
        account=_account(row, account), transaction_id=row.identifier("transactionID"),
        conid=row.identifier("conid"), symbol=row.text("symbol", 64),
        description=row.text("description"), type=row.text("type", 8),
        day=day or row.day("reportDate"), quantity=row.decimal("quantity"),
        proceeds=row.decimal("proceeds", required=False), currency=row.currency(),
    )


def _statement(element: ET.Element, index: int) -> Statement:
    head = _Row(element, "FlexStatement", index)
    account = head.identifier("accountId")
    from_date, to_date = head.day("fromDate"), head.day("toDate")
    if from_date > to_date:
        head.fail("fromDate", "follows toDate")
    # Account Information carries name, addresses, date of birth and email.
    # Only the base currency is read; everything else is deliberately ignored.
    info = element.find("AccountInformation")
    base = _Row(info, "AccountInformation", 1).currency() if info is not None and info.get("currency") else None
    notices: list[str] = []

    trade_rows = _rows(element, "Trades", "Trade") + _rows(element, "Trades", "Order")
    levels = {(r.element.get("levelOfDetail") or "EXECUTION") for r in trade_rows}
    # EXECUTION rows are the most granular; ORDER rows aggregate them, so never mix.
    keep = "EXECUTION" if "EXECUTION" in levels else "ORDER"
    trades = [_trade(r, account) for r in trade_rows if (r.element.get("levelOfDetail") or "EXECUTION") == keep]
    if levels - {keep}:
        notices.append("Trades: summary and closed-lot rows were skipped; executions are used.")

    cash_rows = _rows(element, "CashTransactions", "CashTransaction")
    if any((r.element.get("levelOfDetail") or "DETAIL") != "DETAIL" for r in cash_rows):
        if not any((r.element.get("levelOfDetail") or "DETAIL") == "DETAIL" for r in cash_rows):
            raise LedgerError("CashTransactions: set the section's level of detail to Detail; summary rows lack transaction IDs.")
        notices.append("CashTransactions: summary rows were skipped; detail rows are used.")
    cash = [_cash(r, account) for r in cash_rows if (r.element.get("levelOfDetail") or "DETAIL") == "DETAIL"]
    if any(c.kind == "other" for c in cash):
        notices.append("CashTransactions: some types are not classified yet; they count toward cash but need review.")

    positions = [_position(r, account) for r in _rows(element, "OpenPositions", "OpenPosition")]
    summary = [p for p in positions if p.level == "SUMMARY"]
    lots = [p for p in positions if p.level == "LOT"]
    if lots and not summary:
        raise LedgerError("OpenPositions: include Summary rows; lots alone are not reconciled.")

    balances, base_cash = [], None
    for row in _rows(element, "CashReport", "CashReportCurrency"):
        # The BaseCurrency row is IBKR's converted total of the per-currency rows. It is kept
        # separately: it converts cash even when the report has no conversion rates.
        if row.element.get("levelOfDetail") == "BaseCurrency" or row.element.get("currency") == "BASE_SUMMARY":
            base_cash = row.decimal("endingCash", required=False)
            continue
        balances.append(CashBalance(
            account=_account(row, account), currency=row.currency(),
            from_date=row.day("fromDate", required=False), to_date=row.day("toDate", required=False),
            starting=row.decimal("startingCash"), ending=row.decimal("endingCash"),
        ))
    if len({b.currency for b in balances}) != len(balances):
        raise LedgerError("CashReport: each currency must appear once.")

    actions = [_corporate_action(r, account) for r in _rows(element, "CorporateActions", "CorporateAction")]
    if any(a.type not in SPLITS for a in actions):
        notices.append("CorporateActions: only splits are modeled; other actions need review.")

    # "Net Asset Value (NAV) in Base": IBKR's total account value for each day of the period.
    nav = {}
    for row in _rows(element, "EquitySummaryInBase", "EquitySummaryByReportDateInBase"):
        nav[row.day("reportDate")] = row.decimal("total")

    rates = []
    for row in _rows(element, "ConversionRates", "ConversionRate"):
        rate = row.decimal("rate")
        if rate <= 0:
            row.fail("rate", "must be positive")
        rates.append(FxRate(row.day("reportDate"), row.currency("fromCurrency"), row.currency("toCurrency"), rate))

    unmodeled = tuple(label for section, label in UNMODELED_SECTIONS.items()
                      if (found := element.find(section)) is not None and len(found))
    return Statement(
        account=account, from_date=from_date, to_date=to_date, base_currency=base,
        trades=_unique(trades, "Trades"), cash_transactions=_unique(cash, "CashTransactions"),
        positions=_unique(summary, "OpenPositions", key=lambda p: p.conid), lots=tuple(lots),
        cash_balances=tuple(balances), corporate_actions=_unique(actions, "CorporateActions"),
        fx_rates=tuple(rates), unmodeled=unmodeled, notices=tuple(notices), base_cash=base_cash,
        nav=tuple(sorted(nav.items())),
    )


def parse_ledger(data: bytes) -> Ledger:
    validate_report(data)
    statements = parse_xml(data).find("FlexStatements").findall("FlexStatement")
    return Ledger(tuple(_statement(el, i) for i, el in enumerate(statements, 1)))


def merge(*ledgers: Ledger) -> Ledger:
    """Combine reimports and overlapping periods into one statement per account.

    Exact repeats are dropped (reimports are idempotent); a reused transaction ID
    with different content is refused. Periods must overlap or touch: a gap would
    silently lose activity. Positions and ending balances come from the latest report.
    """
    by_account: dict[str, list[Statement]] = {}
    for ledger in ledgers:
        for s in ledger.statements:
            by_account.setdefault(s.account, []).append(s)
    merged = []
    for account, items in by_account.items():
        items.sort(key=lambda s: (s.from_date, s.to_date))
        covered = items[0].to_date
        for s in items[1:]:
            if s.from_date > covered + timedelta(days=1):
                raise LedgerError("Reports for one account leave a gap between periods; import the missing dates.")
            covered = max(covered, s.to_date)
        latest = max(items, key=lambda s: s.to_date)
        bases = {s.base_currency for s in items if s.base_currency}
        if len(bases) > 1:
            raise LedgerError("Reports for one account disagree on its base currency.")
        balances = {}
        for b in sorted((b for s in items for b in s.cash_balances), key=lambda b: (b.from_date or date.min)):
            start = balances.get(b.currency, b)
            balances[b.currency] = replace(b, from_date=start.from_date, starting=start.starting)
        for b in latest.cash_balances:
            balances[b.currency] = replace(balances[b.currency], to_date=b.to_date, ending=b.ending)
        merged.append(Statement(
            account=account, from_date=items[0].from_date, to_date=covered,
            base_currency=next(iter(bases), None),
            trades=_unique([t for s in items for t in s.trades], "Trades"),
            cash_transactions=_unique([c for s in items for c in s.cash_transactions], "CashTransactions"),
            positions=latest.positions, lots=latest.lots, cash_balances=tuple(balances.values()),
            corporate_actions=_unique([a for s in items for a in s.corporate_actions], "CorporateActions"),
            fx_rates=tuple(dict.fromkeys(r for s in items for r in s.fx_rates)),
            unmodeled=tuple(dict.fromkeys(u for s in items for u in s.unmodeled)),
            notices=tuple(dict.fromkeys(n for s in items for n in s.notices)), base_cash=latest.base_cash,
            # Overlapping reports: the later report's value for a day wins.
            nav=tuple(sorted({d: v for s in sorted(items, key=lambda s: s.to_date) for d, v in s.nav}.items())),
        ))
    return Ledger(tuple(merged))
