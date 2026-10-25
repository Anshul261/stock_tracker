# IBKR: official integration path

Verified against Interactive Brokers documentation on 21 October 2026.

## Decision

Use the **Flex Web Service v3** for the initial analysis-only integration. This official reporting API generates and retrieves the Flex Query reports configured in Client Portal. It uses a Flex reporting token and query ID; ongoing retrieval does not require the app to hold the IBKR username/password or run a brokerage session.

The current Client Portal Gateway documentation requires daily browser reauthentication and does not support automated gateway authentication. Current OAuth 1.0a/2.0 documentation describes registration-based access for specified organizations, advisors, brokers and/or third-party providers. Do not assume an ordinary personal account has a self-service OAuth client. Neither route is needed for the reporting milestone.

Flex supplies reporting snapshots. It is not the app's live price feed. Before displaying imported data, retain its actual statement period and observation date; never mix it silently with the demo's illustrative history or prices.

## Set up the query in IBKR

1. Sign in to **IBKR Client Portal** yourself, including its normal verification.
2. Go to **Reporting → Flex Queries**.
3. Create an **Activity Flex Query**, selecting only the intended account(s), with **XML** output. Choose the desired reporting period in Portal. For the first reconciliation, a completed reporting day is preferable to an incomplete current day.
4. Include the relevant sections below. Keep instrument identifiers, currencies, dates, detail levels and transaction identifiers. Preserve both summary balances and transaction-level history; do not reconstruct cost basis from an incomplete recent trade list.
5. Run/download the XML once through Portal to confirm the report exists and has the intended sections. The CLI can validate its envelope offline.
6. Use the query's information button to obtain its **Query ID**.
7. Open **Flex Web Service Configuration**, enable the service and generate a token. IBKR documents validity from 6 hours to 1 year and optional IP restrictions. Use the shortest practical validity; only restrict by IP when the sync host's outbound IP is known and stable.

The token may retrieve reporting data for linked accounts depending on query/account inclusion. It is not a narrowly scoped per-field API key. Do not infer token authority solely from the account selected in one query. Keep it private, outside browser code, screenshots, Git, logs and AI prompts.

### Sections for the next import/reconciliation stage

| Section | Purpose |
| --- | --- |
| Account Information | Account context and base currency; keep personal identifiers private |
| Open Positions | Instrument ID, currency, quantity, report price/value and reported cost basis |
| Trades | Execution dates, stable trade identifiers, quantities, prices, commissions and currencies |
| Cash Report | Opening/closing balances by currency and appropriate totals |
| Cash Transactions | Dividends, interest, fees and withholding taxes |
| Corporate Actions | Splits and other events that change quantities or cost |
| Transfers / incoming-outgoing position transfers | Opening positions and transfers that are not purchases or investment gains |
| Currency Conversion Rates | Currency conversion context for reconciliation |

Use IBKR's Activity Flex Query Reference to confirm exact fields and available names for your account/query configuration. These are importer requirements, not proof that all exported sections have already been normalized by this client.

## Run locally without exposing the token in a command

From the project folder, on Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install --require-hashes -r requirements-ibkr.txt
.\.venv\Scripts\python -m ibkr inspect path\to\your-export.xml
.\.venv\Scripts\python -m ibkr fetch --query-id YOUR_QUERY_ID --output private-data\ibkr\first-report.xml
```

With [uv](https://docs.astral.sh/uv/) (any OS; `uv sync` installs the pinned dependency from `uv.lock`):

```sh
uv sync
uv run python -m ibkr inspect /path/to/your-export.xml
uv run python -m ibkr fetch --query-id YOUR_QUERY_ID --output private-data/ibkr/first-report.xml
```

On Linux/macOS without uv:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-ibkr.txt
.venv/bin/python -m ibkr inspect /path/to/your-export.xml
.venv/bin/python -m ibkr fetch --query-id YOUR_QUERY_ID --output private-data/ibkr/first-report.xml
```

Replace `YOUR_QUERY_ID` with the numeric ID from Portal. Interactive fetch prompts for the Flex token with input hidden. There is deliberately no `--token` command-line option. A server/secret manager can instead supply `IBKR_FLEX_TOKEN` and `IBKR_FLEX_QUERY_ID`; the program does not load `.env` automatically. Never paste the token into chat.

Optional range override: supply both `--from-date YYYYMMDD` and `--to-date YYYYMMDD`. IBKR's reference documents the date parameters; report availability still depends on IBKR and the account. This client does not promise unlimited historical retrieval. Omit both to use the template's configured period.

The file is created only after validating the XML report envelope. Existing files are never overwritten. Output defaults to Git-ignored `private-data/ibkr/report.xml`. On POSIX, new report files use 0600 and new output directories 0700. On Windows, use a private user directory and confirm its inherited NTFS permissions. Inspection prints counts only, not account identifiers or positions.

## Implemented boundary

`ibkr/flex.py` performs the official sequence:

1. HTTPS GET `SendRequest` with token, Query ID and version 3.
2. Validate Success and the returned numeric ReferenceCode.
3. HTTPS GET `GetStatement` using that ReferenceCode as `q`.
4. Poll documented pending responses with a deadline, then validate the XML statement collection before saving.

The returned `<url>` is ignored, as IBKR instructs. Only the fixed official `ndcdyn.interactivebrokers.com` host and the two reporting paths are supported. Redirects are rejected. TLS verification is enabled. Requests are at least 7 seconds apart within a client, conservatively below the documented 1 request/second and 10 requests/minute/token limits. Run one sync worker per token; separate processes would otherwise share the same IBKR limit without sharing our limiter.

HTTP/network/service errors omit URLs, tokens, raw broker messages and report contents. XML DTDs and entities are forbidden with pinned `defusedxml`. Response size is capped at 32 MiB. Report generation is not automatically retried after an ambiguous network failure.

This is a retrieval client and offline envelope validator, not a hosted backend. It does not calculate live returns or establish application authentication. No order, cancellation or transfer API exists in it.

## Ledger and reconciliation (offline)

`ibkr/ledger.py` turns a saved Activity Flex XML report into typed records: trades, cash transactions, open positions (summary and lots), per-currency cash balances, splits and conversion rates. Money is `Decimal` in its reported currency. `ibkr/reconcile.py` then checks the ledger against itself:

| Check | What must hold |
| --- | --- |
| `position_value` | quantity × mark price × multiplier = reported position value, within the mark price's rounding |
| `trade_net_cash` | proceeds + taxes + commission = IBKR's net cash |
| `quantity` | opening + trades + splits = closing quantity, per IBKR contract ID |
| `cash` | starting cash + trades + commissions + cash transactions + corporate-action cash = ending cash, per currency (FX conversions move both currencies) |
| `cost_basis` | FIFO lots rebuilt from the trades (fees included, splits applied) = reported cost basis |
| `realized_pnl` | FIFO realized profit on each sale = IBKR's `fifoPnlRealized`, when the field is included |

Each check passes, fails or is **unverified**. Unverified means the inputs cannot settle it: the opening holdings are unknown, the report has transfers or option exercises (not modeled yet), a corporate action other than a split occurred, or commissions were charged in another currency. Unverified is never counted as a pass.

Run it locally; by default it prints counts only, with no symbols, amounts or account identifiers:

```sh
uv run python -m ibkr ledger private-data/ibkr/first-report.xml
uv run python -m ibkr ledger private-data/ibkr/2025.xml private-data/ibkr/2026.xml --from-inception --details
```

Pass `--from-inception` only when the reports start at the account's opening, so opening positions are zero; otherwise quantity and cost-basis checks stay unverified. Several reports for one account are merged: exact repeats are dropped, so reimports are idempotent; a reused transaction ID with different content is refused for review; a gap between periods is refused. `--details` lists each non-passing check with symbols and amounts. The exit status is 2 when any check fails.

Import rules that keep the ledger honest:

- Include `transactionID` for trades and cash transactions; rows without it are refused rather than guessed at.
- Configure dates as `yyyyMMdd` or `yyyy-MM-dd` (date/time `yyyyMMdd;HHmmss`). Ambiguous formats such as `MM/dd/yyyy` are refused. Times are kept as reported, without assuming a time zone.
- Trades use EXECUTION rows; ORDER, summary and closed-lot rows are skipped so nothing is double counted. Cash transactions need Detail level.
- Account Information is read only for the base currency. Name, addresses, date of birth and email are never retained. Ledger representations mask account IDs.
- Broker text such as descriptions is stripped of control characters and kept as literal text. The UI escapes it when rendering.
- Unrecognized cash types are kept in the cash rollforward and flagged for review rather than dropped.

Cost basis assumes FIFO, IBKR's default tax-lot method. If your account uses another method, `cost_basis` can fail even though IBKR is right. `tests/fixtures/synthetic-activity.xml` is a synthetic report of the prototype's demo portfolio; the tests reconcile it from inception and against `prototype/data.js`.

## Staying within IBKR's Flex rules

Checked on 26 October 2026 against IBKR's Web API documentation (the `.md` versions of the pages below).

| IBKR documents | How this client follows it |
| --- | --- |
| `SendRequest` is limited to 1 request per second and 10 per minute per token; error 1018 when exceeded | Requests are at least 7 seconds apart within a client. The CLI holds an exclusive lock (POSIX) so two local processes cannot share a token's limit. 1018 waits rather than generating another report |
| Use version 3 | Every request sends `v=3` |
| Ignore the `<url>` returned by `SendRequest` | The field is never read; only the fixed `ndcdyn.interactivebrokers.com` host is used and redirects are refused |
| The period parameter covers at most 365 days | Explicit `--from-date/--to-date` ranges are capped at 365 days too (our conservative assumption; IBKR does not state a limit for `fd`/`td`). Import longer histories as several reports and merge them |
| Tokens last 6 hours to 1 year, can be IP-restricted, and generating a new one invalidates the old one | Setup recommends the shortest practical validity and IP restriction where the sync host is stable. Expiry (1012), IP rejection (1013), invalid token (1015) and too many failed attempts (1025) stop immediately without retrying |
| A token can retrieve data for all linked accounts included in a query | The token is treated as account-wide. IBKR's protocol puts it in the request URL, so it travels only over verified HTTPS to IBKR. It is never logged, printed, accepted as a command-line option, stored in the browser or passed to AI tools |

What we did not find: the Flex pages describe the service as the account holder's way to retrieve their own reports, and say nothing about sharing a token with someone else's service. IBKR's third-party integration pages route portfolio and reporting vendors through its **Reporting Integration** team rather than through customer Flex tokens.

The rule for this product follows from that:

- **Supported:** you run Still for your own accounts, with your own token, on a machine you control. This is the documented use.
- **Not supported without IBKR's agreement:** a hosted, multi-user service where customers paste Flex tokens into Still's servers. Before building that, contact IBKR's Reporting Integration team (see the third-party integration link below) and confirm the permitted route, data use and any redistribution limits.
- **Market data:** mark prices in a Flex report are IBKR's. Showing them to the account owner is what the report is for. We have not reviewed terms that would allow redistributing them to anyone else, so don't.

## Current readiness

- Offline client/security contract tests: 20 passed, using synthetic fixtures and fake transport.
- Offline ledger/reconciliation tests: 31 passed, covering partial sales, splits, currency conversion, reimports, malformed fields and privacy (`uv run python -m unittest discover -s tests -p 'test_ibkr_*.py'`).
- Real account connection: not verified; no token/query ID is configured in this environment.
- Managed environment egress: the enforced allowlist does not currently include `ndcdyn.interactivebrokers.com`; enable that exact HTTPS destination through environment configuration before a live test here. No denied connection was attempted or bypassed.
- Hosted page: remains the synthetic-data prototype. No broker credential or private report is deployed to it.
- Real-report reconciliation: not done. The ledger has only seen synthetic reports; field names follow IBKR's Activity Flex conventions but need confirming against your export.
- Next gate: run `ibkr ledger` on a real export, resolve any fail or unverified checks (transfers and non-split corporate actions are the expected gaps), then connect an owner-authorized application data route. Keep synthetic histories out of real-account views.

## Connection settings in the app

Open `#settings/ibkr` for current status, setup steps, and official stop-access instructions. The hosted prototype remains disconnected and deliberately has no token-entry form. The local client described above is separate from this UI.

To disable future Flex retrieval globally, use Client Portal → Reporting → Flex Queries → Flex Web Service Configuration, switch the service off, and save. This affects other Flex consumers too and does not delete reports already retrieved. The official guide documents this Portal control; we have not found a documented remote disable/revoke endpoint.

App-only pause, disconnect (remove its saved credential) and imported-data deletion belong to the future owner-authorized backend. Do not substitute localStorage flags for stopping a server sync worker or deleting server data.

## Official sources

- Flex overview: https://www.interactivebrokers.com/docs/web-api/flex-web-service/introduction
- Credential model: https://www.interactivebrokers.com/docs/web-api/flex-web-service/client-portal-configuration
- Token validity, linked accounts and IP restrictions: https://www.interactivebrokers.com/docs/web-api/flex-web-service/client-portal-configuration/enable-and-create-access-token
- Query ID: https://www.interactivebrokers.com/docs/web-api/flex-web-service/client-portal-configuration/create-a-flex-query
- Generation, pacing and instruction to ignore response URL: https://www.interactivebrokers.com/docs/web-api/flex-web-service/using-flex-web-service/generate-the-report
- Parameter reference: https://www.interactivebrokers.com/docs/web-api/api-reference/send-request
- Retrieval: https://www.interactivebrokers.com/docs/web-api/flex-web-service/using-flex-web-service/retrieve-the-report
- Error codes: https://www.interactivebrokers.com/docs/web-api/flex-web-service/error-codes
- Third-party reporting integration: https://www.interactivebrokers.com/en/trading/third-party-integration.php
- Third-party connection list and Reporting Integration note: https://www.interactivebrokers.com/docs/third-party-integrations/available-integrations
- Query field reference: https://www.ibkrguides.com/reportingreference/reportguide/activity%20flex%20query%20reference.htm
- Gateway reauthentication: https://www.interactivebrokers.com/docs/web-api/authentication/cpgw/client-portal-gateway-faq
- OAuth 2.0 eligibility: https://www.interactivebrokers.com/docs/web-api/authentication/oauth-2/introduction
- OAuth 1.0a eligibility: https://www.interactivebrokers.com/docs/web-api/authentication/oauth-1a/introduction

XML parser upstream: https://github.com/tiran/defusedxml . It is a supporting dependency, not an IBKR SDK or an authentication provider.

- Disable Flex access in Client Portal: https://www.ibkrguides.com/advisorportal/ug/flex-web-service.htm
