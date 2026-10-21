"""Offline contract/security tests. No real token or IBKR account is contacted."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import Mock, patch
import os
import ssl
import urllib.error
import urllib.parse

from ibkr.__main__ import main as cli_main
from ibkr.flex import (
    BASE_URL, FlexClient, FlexError, FlexServiceError, FlexTimeout,
    HttpsTransport, NoRedirect, save_report, validate_report,
)

REPORT = (Path(__file__).parent / "fixtures/synthetic-flex.xml").read_bytes()
TOKEN = "synthetic-secret-never-a-real-token"
SUCCESS = b"<FlexStatementResponse><Status>Success</Status><ReferenceCode>123456</ReferenceCode><url>https://attacker.invalid/steal</url></FlexStatementResponse>"


def failure(code, message="Do not print this sensitive response"):
    return f"<FlexStatementResponse><Status>Fail</Status><ErrorCode>{code}</ErrorCode><ErrorMessage>{message}</ErrorMessage></FlexStatementResponse>".encode()


class Clock:
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeTransport:
    def __init__(self, clock, responses):
        self.clock, self.responses, self.requests = clock, list(responses), []

    def get(self, endpoint, params, timeout):
        self.requests.append((self.clock(), endpoint, params, timeout))
        if not self.responses:
            raise AssertionError("Unexpected request: polling must be bounded")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FlexTests(TestCase):
    def client(self, responses, **kwargs):
        clock = Clock()
        transport = FakeTransport(clock, responses)
        return FlexClient(TOKEN, "98765", transport=transport, clock=clock, sleep=clock.sleep, **kwargs), transport, clock

    def test_official_two_step_flow_uses_reference_and_ignores_response_url(self):
        client, transport, clock = self.client([SUCCESS, REPORT])
        report = client.fetch()
        self.assertEqual(report.content, REPORT)
        self.assertEqual(report.statement_count, 1)
        self.assertEqual([r[1] for r in transport.requests], ["SendRequest", "GetStatement"])
        self.assertEqual([r[2]["q"] for r in transport.requests], ["98765", "123456"])
        self.assertTrue(all(r[2]["v"] == "3" for r in transport.requests))
        self.assertEqual(clock.sleeps, [7.0])
        self.assertNotIn(TOKEN, repr(client))
        self.assertNotIn("SYNTHETIC-ACCOUNT", repr(report))

    def test_report_pending_is_polled_with_pacing(self):
        client, transport, _ = self.client([SUCCESS, failure("1019"), failure("1004"), REPORT])
        client.fetch()
        self.assertEqual([r[0] for r in transport.requests], [0, 7, 14, 21])

    def test_rate_limit_response_does_not_create_another_generation_request(self):
        client, transport, _ = self.client([SUCCESS, failure("1018"), REPORT])
        client.fetch()
        self.assertEqual([r[1] for r in transport.requests], ["SendRequest", "GetStatement", "GetStatement"])

    def test_repeated_fetches_share_the_same_rate_limit(self):
        client, transport, _ = self.client([SUCCESS, REPORT, SUCCESS, REPORT])
        client.fetch()
        client.fetch()
        self.assertEqual([r[0] for r in transport.requests], [0, 7, 14, 21])

    def test_pending_loop_has_a_deadline(self):
        client, transport, _ = self.client([SUCCESS] + [failure("1019")] * 20, max_wait=20)
        with self.assertRaises(FlexTimeout):
            client.fetch()
        self.assertEqual(len(transport.requests), 3)

    def test_expired_or_invalid_tokens_are_not_retried(self):
        for code in ["1012", "1013", "1014", "1015", "1025"]:
            with self.subTest(code=code):
                client, transport, _ = self.client([SUCCESS, failure(code, TOKEN)])
                with self.assertRaises(FlexServiceError) as error:
                    client.fetch()
                self.assertEqual(error.exception.code, code)
                self.assertNotIn(TOKEN, str(error.exception))
                self.assertEqual(len(transport.requests), 2)

    def test_generation_failure_does_not_poll(self):
        client, transport, _ = self.client([failure("1015", TOKEN)])
        with self.assertRaises(FlexServiceError):
            client.fetch()
        self.assertEqual(len(transport.requests), 1)

    def test_unknown_broker_errors_do_not_echo_input(self):
        client, _, _ = self.client([failure("sensitive-code", TOKEN)])
        with self.assertRaises(FlexServiceError) as error:
            client.fetch()
        self.assertEqual(error.exception.code, "unknown")
        self.assertNotIn(TOKEN, str(error.exception))
        self.assertNotIn("sensitive-code", str(error.exception))

    def test_dates_are_validated_before_network_requests(self):
        for start, end in [("20261001", None), (None, "20261020"), ("20260230", "20260301"), ("20261021", "20261001"), ("2026-10-01", "20261020")]:
            with self.subTest(start=start, end=end):
                client, transport, _ = self.client([])
                with self.assertRaises(FlexError):
                    client.fetch(start, end)
                self.assertEqual(transport.requests, [])

    def test_date_override_only_applies_to_generation(self):
        client, transport, _ = self.client([SUCCESS, REPORT])
        client.fetch("20261001", "20261020")
        self.assertEqual(transport.requests[0][2]["fd"], "20261001")
        self.assertEqual(transport.requests[0][2]["td"], "20261020")
        self.assertNotIn("fd", transport.requests[1][2])

    def test_report_reference_is_not_an_arbitrary_url(self):
        client, transport, _ = self.client([SUCCESS.replace(b"123456", b"https://attacker.invalid")])
        with self.assertRaises(FlexError):
            client.fetch()
        self.assertEqual(len(transport.requests), 1)

    def test_xml_entities_and_doctypes_are_rejected(self):
        unsafe = b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><FlexQueryResponse>&x;</FlexQueryResponse>'
        with self.assertRaises(FlexError):
            validate_report(unsafe)

    def test_csv_html_truncated_empty_or_inconsistent_reports_are_rejected(self):
        payloads = [b"", b"symbol,quantity\nMSFT,80", b"<html>Login</html>", REPORT[:-20], REPORT.replace(b'count="1"', b'count="2"'), REPORT.replace(b'count="1"', b'count="' + b'9' * 5000 + b'"'), b'<FlexQueryResponse><FlexStatements count="0"/></FlexQueryResponse>']
        for payload in payloads:
            with self.subTest(payload=payload[:20]):
                with self.assertRaises(FlexError):
                    validate_report(payload)

    def test_private_output_does_not_overwrite_or_follow_a_symlink(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "private" / "report.xml"
            save_report(validate_report(REPORT), output)
            self.assertEqual(output.read_bytes(), REPORT)
            if os.name == "posix":
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
                self.assertEqual(output.parent.stat().st_mode & 0o777, 0o700)
            with self.assertRaises(FlexError):
                save_report(validate_report(REPORT), output)
            self.assertEqual(output.read_bytes(), REPORT)
            link = output.parent / "link.xml"
            if os.name == "posix":
                link.symlink_to(output)
                with self.assertRaises(FlexError):
                    save_report(validate_report(REPORT), link)

    def test_transport_has_fixed_host_tls_and_safe_request_construction(self):
        transport = HttpsTransport()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = REPORT
        transport.opener.open = Mock(return_value=response)
        self.assertEqual(transport.get("SendRequest", {"t": TOKEN, "q": "1", "v": "3"}, 20), REPORT)
        request = transport.opener.open.call_args.args[0]
        parsed = urllib.parse.urlsplit(request.full_url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.hostname, "ndcdyn.interactivebrokers.com")
        self.assertTrue(request.full_url.startswith(BASE_URL + "SendRequest?"))
        self.assertEqual(request.get_method(), "GET")
        with self.assertRaises(FlexError):
            transport.get("../orders", {"t": TOKEN}, 20)
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://attacker.invalid"))
        https = next(h for h in transport.opener.handlers if isinstance(h, __import__('urllib.request', fromlist=['HTTPSHandler']).HTTPSHandler))
        self.assertTrue(https._context.check_hostname)
        self.assertEqual(https._context.verify_mode, ssl.CERT_REQUIRED)

    def test_transport_rejects_large_responses_and_redacts_network_errors(self):
        transport = HttpsTransport(max_bytes=10)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b"x" * 11
        transport.opener.open = Mock(return_value=response)
        with self.assertRaises(FlexError):
            transport.get("GetStatement", {"t": TOKEN}, 20)
        transport.opener.open.side_effect = urllib.error.URLError("Failed at https://example.invalid/?t=" + TOKEN)
        with self.assertRaises(FlexError) as error:
            transport.get("GetStatement", {"t": TOKEN}, 20)
        self.assertNotIn(TOKEN, str(error.exception))

    def test_http_failure_has_no_sensitive_url_or_body(self):
        transport = HttpsTransport()
        transport.opener.open = Mock(side_effect=urllib.error.HTTPError(BASE_URL + "?t=" + TOKEN, 302, TOKEN, {}, None))
        with self.assertRaises(FlexError) as error:
            transport.get("SendRequest", {"t": TOKEN}, 20)
        self.assertIn("302", str(error.exception))
        self.assertNotIn(TOKEN, str(error.exception))

    def test_offline_cli_inspection_prints_no_account_data(self):
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = cli_main(["inspect", str(Path(__file__).parent / "fixtures/synthetic-flex.xml")])
        self.assertEqual(status, 0)
        self.assertIn("1 statement", output.getvalue())
        for value in ["SYNTHETIC-ACCOUNT", "MSFT", "521.38"]:
            self.assertNotIn(value, output.getvalue() + errors.getvalue())

    def test_missing_credentials_do_not_start_network_or_print_token(self):
        output = StringIO()
        with patch.dict(os.environ, {}, clear=True), patch('sys.stdin.isatty', return_value=False), patch.object(HttpsTransport, 'get') as get, redirect_stderr(output):
            result = cli_main(["fetch", "--query-id", "1234"])
        self.assertEqual(result, 1)
        get.assert_not_called()
        self.assertIn("No Flex token configured", output.getvalue())

    def test_cli_refuses_existing_output_before_auth_or_network(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "report.xml"
            output.write_bytes(b"previous private report")
            with patch.dict(os.environ, {}, clear=True), patch.object(HttpsTransport, 'get') as get, redirect_stderr(StringIO()):
                result = cli_main(["fetch", "--query-id", "1234", "--output", str(output)])
            self.assertEqual(result, 1)
            get.assert_not_called()
            self.assertEqual(output.read_bytes(), b"previous private report")


if __name__ == "__main__":
    main()
