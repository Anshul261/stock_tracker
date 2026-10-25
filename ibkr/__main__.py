"""Local reporting CLI. Tokens are accepted only through a secret binding or hidden prompt."""
import argparse
import getpass
import os
from pathlib import Path
import sys

from .flex import FlexClient, FlexError, MAX_REPORT_BYTES, save_report, single_worker, validate_report
from .ledger import merge, parse_ledger
from .reconcile import reconcile


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Still: official IBKR Flex reporting client (no trading).")
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="Generate and retrieve an XML Flex report.")
    fetch.add_argument("--query-id", default=os.environ.get("IBKR_FLEX_QUERY_ID"), help="Flex Query ID, or set IBKR_FLEX_QUERY_ID.")
    fetch.add_argument("--output", type=Path, default=Path("private-data/ibkr/report.xml"))
    fetch.add_argument("--from-date", help="Optional first date, YYYYMMDD. Requires --to-date.")
    fetch.add_argument("--to-date", help="Optional last date, YYYYMMDD. Requires --from-date.")
    inspect = commands.add_parser("inspect", help="Validate an already exported XML report, offline.")
    inspect.add_argument("path", type=Path)
    ledger = commands.add_parser("ledger", help="Normalize and reconcile exported XML reports, offline.")
    ledger.add_argument("paths", type=Path, nargs="+", help="One or more Activity Flex XML reports; overlaps are merged.")
    ledger.add_argument("--from-inception", action="store_true",
                        help="The reports cover the account since it opened, so opening positions are zero.")
    ledger.add_argument("--details", action="store_true",
                        help="Print each non-passing check with symbols and amounts. Off by default.")
    args = parser.parse_args(argv)
    try:
        if args.command == "ledger":
            reports = []
            for path in args.paths:
                with path.open("rb") as handle:
                    reports.append(parse_ledger(handle.read(MAX_REPORT_BYTES + 1)))
            combined = merge(*reports)
            result = reconcile(combined, from_inception=args.from_inception)
            summary, counts = combined.summary(), result.counts()
            print("Ledger: " + ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in summary.items()) + ".")
            print(f"Reconciliation: {counts['pass']} passed, {counts['fail']} failed, {counts['unverified']} unverified.")
            for notice in dict.fromkeys(n for s in combined.statements for n in s.notices):
                print("Review: " + notice)
            if args.details:
                for check in result.checks:
                    if check.status != "pass":
                        print(f"{check.status:<10} {check.name:<24} {check.subject:<14} "
                              f"expected {check.expected} actual {check.actual} {check.detail}".rstrip())
            elif counts["fail"] or counts["unverified"]:
                print("Run with --details to list them, including symbols and amounts.")
            return 0 if result.ok else 2
        if args.command == "inspect":
            with args.path.open("rb") as handle:
                report = validate_report(handle.read(MAX_REPORT_BYTES + 1))
            print(f"Valid Flex XML: {report.statement_count} statement(s). Contents and account identifiers withheld.")
            return 0
        if not args.query_id:
            raise FlexError("Set IBKR_FLEX_QUERY_ID or supply --query-id from Client Portal.")
        if args.output.exists() or args.output.is_symlink():
            raise FlexError("The output already exists. Choose a new filename before requesting a report.")
        token = os.environ.get("IBKR_FLEX_TOKEN")
        if not token:
            if not sys.stdin.isatty():
                raise FlexError("No Flex token configured. Use a secure IBKR_FLEX_TOKEN binding or run interactively for a hidden prompt.")
            token = getpass.getpass("IBKR Flex reporting token (hidden): ")
        client = FlexClient(token, args.query_id)
        with single_worker(args.output.parent):
            report = client.fetch(args.from_date, args.to_date)
            save_report(report, args.output)
        print(f"Saved a private XML report: {report.statement_count} statement(s). No account data printed.")
        return 0
    except FlexError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError:
        print("Local report file operation failed. Check its path and permissions.", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("Cancelled. No token or account data was printed.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
