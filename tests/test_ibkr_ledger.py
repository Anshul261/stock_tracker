"""Offline ledger normalization and reconciliation tests. Synthetic data only."""
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
import re

from ibkr.__main__ import main as cli_main
from ibkr.flex import FlexError, _date_range
from ibkr.ledger import LedgerError, clean_text, merge, parse_ledger
from ibkr.reconcile import ExpectedHolding, compare_holdings, reconcile

ROOT = Path(__file__).resolve().parents[1]
ACTIVITY = (ROOT / "tests/fixtures/synthetic-activity.xml").read_bytes()
ENVELOPE = (ROOT / "tests/fixtures/synthetic-flex.xml").read_bytes()
D = Decimal


def report(*sections, account="SYN-1", start="20260101", end="20261231", info=""):
    body = "".join(sections)
    return (f'<FlexQueryResponse><FlexStatements count="1"><FlexStatement accountId="{account}" '
            f'fromDate="{start}" toDate="{end}">{info}{body}</FlexStatement></FlexStatements>'
            '</FlexQueryResponse>').encode()


def trade(tid, symbol, quantity, price, conid, commission="-1", day="20260105", clock="100000",
          currency="USD", asset="STK", proceeds=None, pnl=None, commission_currency=None, extra=""):
    q, p = D(quantity), D(price)
    proceeds = D(proceeds) if proceeds is not None else -(q * p)
    net = proceeds + D(commission)
    pnl_attr = f' fifoPnlRealized="{pnl}"' if pnl is not None else ""
    return (f'<Trade accountId="SYN-1" currency="{currency}" assetCategory="{asset}" symbol="{symbol}" '
            f'description="{symbol} SYNTHETIC" conid="{conid}" transactionID="{tid}" tradeDate="{day}" '
            f'dateTime="{day};{clock}" quantity="{quantity}" tradePrice="{price}" proceeds="{proceeds}" taxes="0" '
            f'ibCommission="{commission}" ibCommissionCurrency="{commission_currency or currency}" netCash="{net}" '
            f'buySell="{"BUY" if q > 0 else "SELL"}" levelOfDetail="EXECUTION"{pnl_attr}{extra} />')


def trades(*rows):
    return "<Trades>" + "".join(rows) + "</Trades>"


def cash_tx(tid, kind, amount, day="20260102", currency="USD", conid=""):
    return (f'<CashTransaction accountId="SYN-1" currency="{currency}" symbol="" conid="{conid}" '
            f'description="SYNTHETIC" dateTime="{day}" amount="{amount}" type="{kind}" '
            f'transactionID="{tid}" levelOfDetail="DETAIL" />')


def cash_txs(*rows):
    return "<CashTransactions>" + "".join(rows) + "</CashTransactions>"


def position(symbol, quantity, mark, conid, basis=None, currency="USD", value=None):
    value = value if value is not None else D(quantity) * D(mark)
    basis_attr = f' costBasisMoney="{basis}"' if basis is not None else ""
    return (f'<OpenPosition accountId="SYN-1" currency="{currency}" assetCategory="STK" symbol="{symbol}" '
            f'description="{symbol} SYNTHETIC" conid="{conid}" position="{quantity}" markPrice="{mark}" '
            f'positionValue="{value}"{basis_attr} levelOfDetail="SUMMARY" />')


def positions(*rows):
    return "<OpenPositions>" + "".join(rows) + "</OpenPositions>"


def cash_report(*rows):
    return "<CashReport>" + "".join(
        f'<CashReportCurrency accountId="SYN-1" currency="{c}" levelOfDetail="Currency" '
        f'startingCash="{start}" endingCash="{end}" />' for c, start, end in rows) + "</CashReport>"


def failures(result):
    return [(c.name, c.subject, c.status) for c in result.checks if c.status != "pass"]


def data_js():
    """Read the prototype's synthetic portfolio independently of the ledger code."""
    text = (ROOT / "prototype/data.js").read_text()
    rows = re.findall(r"symbol:'(\w+)'.*?qty:(\d+), cost:([\d.]+), price:([\d.]+)", text)
    cash = D(re.search(r"cashCents = (\d+)", text)[1]) / 100
    return [ExpectedHolding(s, D(q), mark_price=D(p), average_price=D(c)) for s, q, c, p in rows], cash


class SyntheticFixtureTests(TestCase):
    def test_fixture_reconciles_internally_from_inception(self):
        ledger = parse_ledger(ACTIVITY)
        self.assertEqual(ledger.summary(), {"statements": 1, "trades": 8, "cash_transactions": 5,
                                            "positions": 8, "corporate_actions": 0, "currencies": 1})
        result = reconcile(ledger, from_inception=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.counts(), {"pass": 33, "fail": 0, "unverified": 0})

    def test_fixture_matches_the_prototype_portfolio(self):
        expected, cash = data_js()
        self.assertEqual(len(expected), 8)
        result = compare_holdings(parse_ledger(ACTIVITY).statements[0], expected, {"USD": cash})
        self.assertEqual(failures(result), [])
        self.assertEqual(result.counts()["pass"], 8 * 3 + 1)

    def test_reference_comparison_catches_differences(self):
        expected, cash = data_js()
        changed = [ExpectedHolding(e.symbol, e.quantity + (1 if e.symbol == "AAPL" else 0), e.mark_price)
                   for e in expected if e.symbol != "COST"]
        result = compare_holdings(parse_ledger(ACTIVITY).statements[0], changed, {"USD": cash + D("0.01")})
        self.assertEqual(sorted(failures(result)), [("reference_cash", "USD", "fail"),
                                                    ("reference_quantity", "AAPL", "fail"),
                                                    ("reference_quantity", "COST", "fail")])

    def test_unknown_opening_is_unverified_not_pass(self):
        result = reconcile(parse_ledger(ACTIVITY))
        statuses = {(c.name, c.status) for c in result.checks}
        self.assertIn(("quantity", "unverified"), statuses)
        self.assertIn(("cost_basis", "unverified"), statuses)
        self.assertNotIn(("quantity", "pass"), statuses)
        self.assertIn(("cash", "pass"), statuses)  # The Cash Report supplies its own opening balance.

    def test_tampered_reports_fail_the_affected_checks(self):
        cases = {
            b'endingCash="14820.50" endingSettledCash': [("cash", "USD", "fail")],
            b'positionValue="43833.60"': [("position_value", "NVDA", "fail")],
            b'costBasisMoney="35001.00"': [("cost_basis", "MSFT", "fail")],
        }
        replacements = {b'endingCash="14820.50" endingSettledCash': b'endingCash="14820.49" endingSettledCash',
                        b'positionValue="43833.60"': b'positionValue="43843.60"',
                        b'costBasisMoney="35001.00"': b'costBasisMoney="35000.00"'}
        for original, expected in cases.items():
            with self.subTest(original=original):
                self.assertIn(original, ACTIVITY)
                ledger = parse_ledger(ACTIVITY.replace(original, replacements[original]))
                self.assertEqual(failures(reconcile(ledger, from_inception=True)), expected)

    def test_a_missing_trade_breaks_quantity_cash_and_cost(self):
        rows = ACTIVITY.split(b"\n")
        without = b"\n".join(r for r in rows if b'transactionID="8100004"' not in r)
        names = {(n, s) for n, s, _ in failures(reconcile(parse_ledger(without), from_inception=True))}
        self.assertEqual(names, {("quantity", "GOOGL"), ("cost_basis", "GOOGL"), ("cash", "USD")})

    def test_personal_account_information_is_not_retained(self):
        ledger = parse_ledger(ACTIVITY)
        text = repr(ledger)
        for secret in ("Synthetic Person", "Synthetic Way", "19700101", "example.invalid", "SYNTHETIC-7"):
            self.assertNotIn(secret, text)
        self.assertEqual(ledger.statements[0].base_currency, "USD")
        self.assertEqual(ledger.statements[0].label, "•••C-7")

    def test_cash_types_are_classified(self):
        kinds = [c.kind for c in parse_ledger(ACTIVITY).statements[0].cash_transactions]
        self.assertEqual(sorted(kinds), ["deposit_withdrawal", "deposit_withdrawal", "dividend", "dividend",
                                         "withholding_tax"])

    def test_values_are_decimal_and_dates_are_typed(self):
        t = parse_ledger(ACTIVITY).statements[0].trades[0]
        self.assertIsInstance(t.price, Decimal)
        self.assertEqual(t.price, D("128.40"))
        self.assertEqual(t.trade_date.isoformat(), "2026-01-06")
        self.assertEqual(t.executed_time, "09:35:10")

    def test_minimal_envelope_fixture_still_parses(self):
        ledger = parse_ledger(ENVELOPE)
        self.assertEqual(ledger.summary()["positions"], 1)
        names = {(c.name, c.status) for c in reconcile(ledger).checks}
        self.assertIn(("position_value", "pass"), names)


class AccountingTests(TestCase):
    def test_partial_sale_uses_fifo_lots_and_checks_realized_pnl(self):
        # Lots: 100 @ 10 (+1 fee) = 1001, 100 @ 12 (+1) = 1201. Selling 150 removes
        # 1001 + 600.50; proceeds 2250 - 1 fee - 1601.50 = 647.50 realized.
        xml = report(
            cash_report(("USD", "0", "7000")),
            cash_txs(cash_tx(1, "Deposits/Withdrawals", "6953")),
            trades(trade(11, "ABC", "100", "10", 501), trade(12, "ABC", "100", "12", 501, day="20260106"),
                   trade(13, "ABC", "-150", "15", 501, day="20260107", pnl="647.50")),
            positions(position("ABC", "50", "15", 501, basis="600.50")))
        result = reconcile(parse_ledger(xml), from_inception=True)
        self.assertEqual(failures(result), [])
        self.assertIn(("realized_pnl", "ABC", "pass"), {(c.name, c.subject, c.status) for c in result.checks})
        wrong = reconcile(parse_ledger(xml.replace(b'fifoPnlRealized="647.50"', b'fifoPnlRealized="650"')),
                          from_inception=True)
        self.assertEqual(failures(wrong), [("realized_pnl", "ABC", "fail")])

    def test_forward_split_changes_quantity_not_cost(self):
        split = ('<CorporateActions><CorporateAction accountId="SYN-1" currency="USD" symbol="ABC" conid="501" '
                 'description="ABC SPLIT 4 FOR 1" type="FS" dateTime="20260301;202500" quantity="30" proceeds="0" '
                 'transactionID="21" /></CorporateActions>')
        xml = report(cash_report(("USD", "0", "0")), cash_txs(cash_tx(1, "Deposits/Withdrawals", "1001")),
                     trades(trade(11, "ABC", "10", "100", 501)), split,
                     positions(position("ABC", "40", "26", 501, basis="1001")))
        self.assertEqual(failures(reconcile(parse_ledger(xml), from_inception=True)), [])

    def test_unmodeled_corporate_action_is_unverified(self):
        merger = ('<CorporateActions><CorporateAction accountId="SYN-1" currency="USD" symbol="ABC" conid="501" '
                  'description="ABC MERGED" type="TC" dateTime="20260301" quantity="-10" transactionID="21" />'
                  '</CorporateActions>')
        xml = report(trades(trade(11, "ABC", "10", "100", 501)), merger)
        ledger = parse_ledger(xml)
        self.assertIn("CorporateActions: only splits are modeled; other actions need review.",
                      ledger.statements[0].notices)
        quantity = [c for c in reconcile(ledger, from_inception=True).checks if c.name == "quantity"]
        self.assertEqual([c.status for c in quantity], ["unverified"])

    def test_currency_conversion_and_foreign_purchase(self):
        # USD 10,000 deposit; buy EUR 5,000 at 1.10 (USD 2 fee); buy 10 SAP at EUR 200 (EUR 1.25 fee).
        xml = report(
            cash_report(("USD", "0", "4498"), ("EUR", "0", "2998.75")),
            cash_txs(cash_tx(1, "Deposits/Withdrawals", "10000")),
            trades(trade(11, "EUR.USD", "5000", "1.10", 12087792, commission="-2", asset="CASH"),
                   trade(12, "SAP", "10", "200", 777, commission="-1.25", currency="EUR", day="20260106")),
            positions(position("SAP", "10", "210", 777, basis="2001.25", currency="EUR")))
        result = reconcile(parse_ledger(xml), from_inception=True)
        self.assertEqual(failures(result), [])
        self.assertEqual({c.subject for c in result.checks if c.name == "cash"}, {"USD", "EUR"})
        self.assertNotIn("EUR.USD", {c.subject for c in result.checks if c.name == "quantity"})

    def test_commission_in_another_currency_is_unverified_for_cost(self):
        xml = report(trades(trade(12, "SAP", "10", "200", 777, currency="EUR", commission_currency="USD")),
                     positions(position("SAP", "10", "200", 777, basis="2001", currency="EUR")))
        cost = [c for c in reconcile(parse_ledger(xml), from_inception=True).checks if c.name == "cost_basis"]
        self.assertEqual(cost[0].status, "unverified")

    def test_transfers_downgrade_mismatches_to_unverified(self):
        transfers = '<Transfers><Transfer accountId="SYN-1" symbol="ABC" conid="501" quantity="5" /></Transfers>'
        xml = report(trades(trade(11, "ABC", "10", "100", 501)), transfers,
                     positions(position("ABC", "15", "100", 501, basis="1001")))
        ledger = parse_ledger(xml)
        self.assertEqual(ledger.statements[0].unmodeled, ("transfers",))
        quantity = [c for c in reconcile(ledger, from_inception=True).checks if c.name == "quantity"][0]
        self.assertEqual(quantity.status, "unverified")
        self.assertIn("transfers", quantity.detail)

    def test_net_cash_must_match_its_components(self):
        xml = report(trades(trade(11, "ABC", "10", "100", 501).replace('netCash="-1001"', 'netCash="-1000"')))
        self.assertEqual(failures(reconcile(parse_ledger(xml))), [("trade_net_cash", "ABC", "fail"),
                                                                 ("quantity", "ABC", "unverified"),
                                                                 ("cash", "USD", "unverified")])


class ImportSafetyTests(TestCase):
    def test_exact_duplicate_rows_are_dropped(self):
        row = trade(11, "ABC", "10", "100", 501)
        self.assertEqual(len(parse_ledger(report(trades(row, row))).statements[0].trades), 1)

    def test_reused_transaction_id_with_different_content_is_refused(self):
        xml = report(trades(trade(11, "ABC", "10", "100", 501), trade(11, "ABC", "10", "101", 501)))
        with self.assertRaisesRegex(LedgerError, "share a transaction ID but differ"):
            parse_ledger(xml)

    def test_overlapping_reimports_are_idempotent(self):
        # The May purchase appears in both reports; the July dividend only in the second.
        buy = trade(11, "ABC", "10", "100", 501, day="20260515")
        dividend = cash_tx(2, "Dividends", "5", day="20260701", conid="501")
        first = report(cash_report(("USD", "0", "0")), cash_txs(cash_tx(1, "Deposits/Withdrawals", "1001")),
                       trades(buy), start="20260101", end="20260630")
        second = report(cash_report(("USD", "1001", "5")), cash_txs(dividend), trades(buy),
                        positions(position("ABC", "10", "100", 501, basis="1001")),
                        start="20260501", end="20261231")
        once = merge(parse_ledger(first), parse_ledger(second))
        twice = merge(parse_ledger(first), parse_ledger(second), parse_ledger(second))
        self.assertEqual(once, twice)
        s = once.statements[0]
        self.assertEqual((s.from_date.isoformat(), s.to_date.isoformat()), ("2026-01-01", "2026-12-31"))
        self.assertEqual(len(s.trades), 1)
        self.assertEqual((s.cash_balances[0].starting, s.cash_balances[0].ending), (D("0"), D("5")))
        self.assertEqual(failures(reconcile(once, from_inception=True)), [])

    def test_a_gap_between_reports_is_refused(self):
        first = report(start="20260101", end="20260331")
        second = report(start="20260501", end="20260630")
        with self.assertRaisesRegex(LedgerError, "gap"):
            merge(parse_ledger(first), parse_ledger(second))

    def test_strict_fields_fail_without_echoing_values(self):
        good = trade(11, "ABC", "10", "100", 501)
        cases = {
            "transactionID": good.replace('transactionID="11"', ""),
            "tradePrice": good.replace('tradePrice="100"', 'tradePrice="1,0SECRETVALUE"'),
            "tradeDate": good.replace('tradeDate="20260105"', 'tradeDate="01/05/2026"'),
            "quantity": good.replace('quantity="10"', 'quantity="-10"'),
            "currency": good.replace('currency="USD"', 'currency="usdollar"', 1),
            "dateTime": good.replace('dateTime="20260105;100000"', 'dateTime="20260105;250000"'),
        }
        for name, row in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(LedgerError) as caught:
                    parse_ledger(report(trades(row)))
                message = str(caught.exception)
                self.assertIn(name, message)
                self.assertNotIn("SECRETVALUE", message)
                self.assertNotIn("usdollar", message)

    def test_rows_from_another_account_are_refused(self):
        row = trade(11, "ABC", "10", "100", 501).replace('accountId="SYN-1"', 'accountId="OTHER"')
        with self.assertRaisesRegex(LedgerError, "accountId does not match"):
            parse_ledger(report(trades(row)))

    def test_order_rows_are_not_double_counted_with_executions(self):
        order = trade(99, "ABC", "10", "100", 501).replace('levelOfDetail="EXECUTION"', 'levelOfDetail="ORDER"')
        s = parse_ledger(report(trades(trade(11, "ABC", "10", "100", 501), order))).statements[0]
        self.assertEqual([t.transaction_id for t in s.trades], ["11"])
        self.assertTrue(s.notices)

    def test_summary_only_cash_transactions_are_refused(self):
        row = cash_tx(1, "Dividends", "5").replace('levelOfDetail="DETAIL"', 'levelOfDetail="SUMMARY"')
        with self.assertRaisesRegex(LedgerError, "level of detail to Detail"):
            parse_ledger(report(cash_txs(row)))

    def test_broker_text_is_cleaned_but_html_stays_literal(self):
        self.assertEqual(clean_text("A\x00B‮  <img src=x onerror=alert(1)>\n"),
                         "A B <img src=x onerror=alert(1)>")
        row = trade(11, "ABC", "10", "100", 501).replace('description="ABC SYNTHETIC"',
                                                          'description="&lt;script&gt;x&lt;/script&gt;&#10;CORP"')
        self.assertEqual(parse_ledger(report(trades(row))).statements[0].trades[0].description,
                         "<script>x</script> CORP")

    def test_unknown_cash_types_are_kept_and_flagged(self):
        s = parse_ledger(report(cash_txs(cash_tx(1, "Mystery Credit", "3")))).statements[0]
        self.assertEqual(s.cash_transactions[0].kind, "other")
        self.assertTrue(any("not classified" in n for n in s.notices))


class ComplianceAndCliTests(TestCase):
    def test_requested_ranges_are_capped_at_365_days(self):
        self.assertEqual(_date_range("20250101", "20251231"), {"fd": "20250101", "td": "20251231"})
        with self.assertRaisesRegex(FlexError, "at most 365 days"):
            _date_range("20250101", "20260101")

    def run_cli(self, *args):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_ledger_command_prints_counts_only_by_default(self):
        code, out, err = self.run_cli("ledger", str(ROOT / "tests/fixtures/synthetic-activity.xml"), "--from-inception")
        self.assertEqual(code, 0, err)
        self.assertIn("Reconciliation: 33 passed, 0 failed, 0 unverified.", out)
        for private in ("NVDA", "14820", "SYNTHETIC-7", "Synthetic Person"):
            self.assertNotIn(private, out)

    def test_ledger_command_reports_failures_with_opt_in_details(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "tampered.xml"
            path.write_bytes(ACTIVITY.replace(b'positionValue="43833.60"', b'positionValue="43843.60"'))
            code, out, _ = self.run_cli("ledger", str(path), "--from-inception")
            self.assertEqual(code, 2)
            self.assertNotIn("NVDA", out)
            code, out, _ = self.run_cli("ledger", str(path), "--from-inception", "--details")
            self.assertEqual(code, 2)
            self.assertRegex(out, r"fail\s+position_value\s+NVDA")

    def test_ledger_command_rejects_malformed_xml_safely(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "bad.xml"
            path.write_bytes(b"<FlexQueryResponse><FlexStatements count='1'>")
            code, out, err = self.run_cli("ledger", str(path))
            self.assertEqual((code, out), (1, ""))
            self.assertIn("safe XML Flex report", err)


if __name__ == "__main__":
    main()
