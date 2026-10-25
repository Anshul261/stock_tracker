"""IBKR Flex Web Service v3, following IBKR's official two-step protocol.

Tokens and reports are sensitive. No request URL, response body, token or account
identifier is logged. The response's `url` field is deliberately ignored.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Callable, Protocol
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from defusedxml.ElementTree import fromstring
from defusedxml.common import DefusedXmlException

BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/"
MAX_REPORT_BYTES = 32 * 1024 * 1024
ENDPOINTS = frozenset({"SendRequest", "GetStatement"})
MIN_REQUEST_INTERVAL = 7.0  # Conservative: fewer than 10 requests per 60 seconds.
MAX_RANGE_DAYS = 365


class FlexError(Exception):
    """Safe to display: messages are static and never include broker payloads."""


class FlexTimeout(FlexError):
    pass


ERRORS = {
    "1001": "Report generation is temporarily unavailable.",
    "1003": "The requested report is not available.",
    "1004": "The report is not complete yet.",
    "1005": "Settlement data is not ready yet.",
    "1006": "FIFO profit/loss data is not ready yet.",
    "1007": "Mark-to-market data is not ready yet.",
    "1008": "Profit/loss data is not ready yet.",
    "1009": "The reporting service is busy.",
    "1010": "Use an Activity Flex Query; legacy queries are unsupported.",
    "1011": "The reporting service account is inactive.",
    "1012": "The Flex token expired. Generate a new token in Client Portal.",
    "1013": "The Flex token's IP restriction rejected this connection.",
    "1014": "The Flex Query ID is invalid.",
    "1015": "The Flex token is invalid.",
    "1016": "The reporting account is invalid.",
    "1017": "The report reference is invalid.",
    "1018": "The Flex token is rate limited. Avoid concurrent sync workers.",
    "1019": "The report is still generating.",
    "1020": "IBKR could not validate this request.",
    "1021": "The report is temporarily unavailable for retrieval.",
    "1025": "IBKR rejected too many failed attempts. Stop and check configuration.",
}
PENDING_CODES = frozenset({"1001", "1004", "1005", "1006", "1007", "1008", "1009", "1018", "1019", "1021"})


class FlexServiceError(FlexError):
    def __init__(self, code: str):
        # Never echo ErrorMessage or an unknown code supplied by an upstream body.
        self.code = code if code in ERRORS else "unknown"
        super().__init__(ERRORS.get(self.code, "IBKR returned an unrecognized reporting error."))


def parse_xml(data: bytes, limit: int = MAX_REPORT_BYTES) -> ET.Element:
    if not data or len(data) > limit:
        raise FlexError("The XML response is empty or exceeds the report size limit.")
    try:
        return fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (ET.ParseError, DefusedXmlException, ValueError):
        raise FlexError("Expected a safe XML Flex report. Configure the query output as XML.") from None


@dataclass(frozen=True)
class FlexReport:
    content: bytes = field(repr=False)
    statement_count: int


def validate_report(data: bytes) -> FlexReport:
    root = parse_xml(data)
    if root.tag != "FlexQueryResponse":
        raise FlexError("The response is not a Flex Query XML report.")
    statements = root.find("FlexStatements")
    if statements is None:
        raise FlexError("The Flex report contains no statement collection.")
    rows = statements.findall("FlexStatement")
    declared = statements.get("count")
    if declared is not None and (len(declared) > 9 or not declared.isdecimal() or int(declared) != len(rows)):
        raise FlexError("The Flex report statement count does not reconcile.")
    if not rows:
        raise FlexError("The Flex report contains no account statements.")
    return FlexReport(content=data, statement_count=len(rows))


class Transport(Protocol):
    def get(self, endpoint: str, params: dict[str, str], timeout: float) -> bytes: ...


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Credentials are in query parameters under the official Flex protocol.
        # Never let a response redirect them to a different URL or host.
        return None


class HttpsTransport:
    def __init__(self, max_bytes: int = MAX_REPORT_BYTES):
        if not 1 <= max_bytes <= MAX_REPORT_BYTES:
            raise ValueError("Invalid report size limit.")
        self.max_bytes = max_bytes
        self.opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
        )

    def get(self, endpoint: str, params: dict[str, str], timeout: float) -> bytes:
        if endpoint not in ENDPOINTS:
            raise FlexError("Only the two official Flex report endpoints are permitted.")
        url = BASE_URL + endpoint + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={
            "User-Agent": "Still-Portfolio-Reporting/0.1",
            "Accept": "application/xml, text/xml, text/plain",
            "Cache-Control": "no-store",
        }, method="GET")
        try:
            with self.opener.open(request, timeout=timeout) as response:
                content = response.read(self.max_bytes + 1)
        except urllib.error.HTTPError as error:
            status = int(error.code)
            error.close()
            raise FlexError(f"IBKR HTTPS request failed with HTTP status {status}.") from None
        except (urllib.error.URLError, OSError, ValueError):
            raise FlexError("IBKR HTTPS connection failed. Check network access and TLS configuration.") from None
        if len(content) > self.max_bytes:
            raise FlexError("The response exceeds the configured report size limit.")
        return content


def _date_range(from_date: str | None, to_date: str | None) -> dict[str, str]:
    if from_date is None and to_date is None:
        return {}
    if not from_date or not to_date:
        raise FlexError("Supply both --from-date and --to-date, or neither.")
    for value in (from_date, to_date):
        if not re.fullmatch(r"[0-9]{8}", value):
            raise FlexError("Report dates must use YYYYMMDD.")
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError:
            raise FlexError("The report date is invalid.") from None
    if from_date > to_date:
        raise FlexError("The report start date must not follow its end date.")
    # IBKR documents a 365-day maximum for the period parameter; apply the same
    # bound to explicit ranges and import longer histories as several reports.
    span = datetime.strptime(to_date, "%Y%m%d") - datetime.strptime(from_date, "%Y%m%d")
    if span.days + 1 > MAX_RANGE_DAYS:
        raise FlexError(f"Request at most {MAX_RANGE_DAYS} days per report; split longer histories.")
    return {"fd": from_date, "td": to_date}


class FlexClient:
    """One serialized sync worker per token; no brokerage or order endpoints."""

    def __init__(self, token: str, query_id: str, *, transport: Transport | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 max_wait: float = 120.0):
        if not token or len(token) > 4096 or any(c.isspace() for c in token):
            raise FlexError("Supply a valid Flex reporting token through a secure secret binding.")
        if not re.fullmatch(r"[0-9]{1,32}", query_id):
            raise FlexError("The Flex Query ID must contain digits only.")
        if not 1 <= max_wait <= 600:
            raise ValueError("The report wait limit must be between 1 and 600 seconds.")
        self._token, self._query_id = token, query_id
        self._transport = transport or HttpsTransport()
        self._clock, self._sleep = clock, sleep
        self._next_request = 0.0
        self._max_wait = max_wait
        self._lock = Lock()

    def __repr__(self) -> str:
        return "FlexClient(credentials=<redacted>)"

    def _request(self, endpoint: str, query: str, deadline: float,
                 dates: dict[str, str] | None = None) -> bytes:
        now = self._clock()
        wait = max(0.0, self._next_request - now)
        if now + wait >= deadline:
            raise FlexTimeout("Timed out waiting for the Flex report. Retry later.")
        if wait:
            self._sleep(wait)
        now = self._clock()
        if now >= deadline:
            raise FlexTimeout("Timed out waiting for the Flex report. Retry later.")
        self._next_request = now + MIN_REQUEST_INTERVAL
        return self._transport.get(endpoint, {"t": self._token, "q": query, "v": "3", **(dates or {})},
                                   timeout=min(20.0, deadline - now))

    def fetch(self, from_date: str | None = None, to_date: str | None = None) -> FlexReport:
        dates = _date_range(from_date, to_date)
        with self._lock:
            deadline = self._clock() + self._max_wait
            root = parse_xml(self._request("SendRequest", self._query_id, deadline, dates))
            if root.tag != "FlexStatementResponse":
                raise FlexError("Unexpected report-generation response.")
            if root.findtext("Status") != "Success":
                raise FlexServiceError(root.findtext("ErrorCode", "unknown"))
            reference = root.findtext("ReferenceCode", "")
            if not re.fullmatch(r"[0-9]{1,64}", reference):
                raise FlexError("IBKR returned an invalid report reference.")
            # Never follow the <url> field. Official documentation says to ignore it.
            while True:
                payload = self._request("GetStatement", reference, deadline)
                result = parse_xml(payload)
                if result.tag == "FlexQueryResponse":
                    return validate_report(payload)
                if result.tag != "FlexStatementResponse" or result.findtext("Status") != "Fail":
                    raise FlexError("Unexpected report-retrieval response.")
                error = FlexServiceError(result.findtext("ErrorCode", "unknown"))
                if error.code not in PENDING_CODES:
                    raise error


@contextmanager
def single_worker(directory: Path):
    """Hold an exclusive lock so two local processes never share a token's
    1/second, 10/minute limit without sharing the limiter. POSIX only; on
    other systems run one sync process at a time yourself."""
    try:
        import fcntl
    except ImportError:
        yield
        return
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(directory / ".flex-worker.lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise FlexError("Another Flex retrieval is running; wait for it to finish.") from None
        yield
    finally:
        os.close(fd)


def save_report(report: FlexReport, output: Path) -> None:
    """Create a private new file; never silently overwrite a previous report."""
    validate_report(report.content)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(output, flags, 0o600)
    except FileExistsError:
        raise FlexError("The output already exists. Choose a new filename; no report was overwritten.") from None
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(report.content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        output.unlink(missing_ok=True)
        raise
