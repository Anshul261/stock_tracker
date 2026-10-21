"""Local reporting CLI. Tokens are accepted only through a secret binding or hidden prompt."""
import argparse
import getpass
import os
from pathlib import Path
import sys

from .flex import FlexClient, FlexError, MAX_REPORT_BYTES, save_report, validate_report


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
    args = parser.parse_args(argv)
    try:
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
