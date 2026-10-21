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

On Linux/macOS:

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

This is a retrieval client and offline envelope validator, **not** a reconciled portfolio importer or a hosted backend. It does not validate every financial field, calculate live returns or establish application authentication. No order, cancellation or transfer API exists in it.

## Current readiness

- Offline client/security contract tests: 20 passed, using synthetic fixtures and fake transport.
- Real account connection: not verified; no token/query ID is configured in this environment.
- Managed environment egress: the enforced allowlist does not currently include `ndcdyn.interactivebrokers.com`; enable that exact HTTPS destination through environment configuration before a live test here. No denied connection was attempted or bypassed.
- Hosted page: remains the synthetic-data prototype. No broker credential or private report is deployed to it.
- Next gate: validate a real report locally, normalize the ledger with explicit currency/detail handling, reconcile positions/cash/cost basis to IBKR, then connect an owner-authorized application data route. Keep synthetic histories out of real-account views.

## Official sources

- Flex overview: https://www.interactivebrokers.com/docs/web-api/flex-web-service/introduction
- Credential model: https://www.interactivebrokers.com/docs/web-api/flex-web-service/client-portal-configuration
- Token validity, linked accounts and IP restrictions: https://www.interactivebrokers.com/docs/web-api/flex-web-service/client-portal-configuration/enable-and-create-access-token
- Query ID: https://www.interactivebrokers.com/docs/web-api/flex-web-service/client-portal-configuration/create-a-flex-query
- Generation, pacing and instruction to ignore response URL: https://www.interactivebrokers.com/docs/web-api/flex-web-service/using-flex-web-service/generate-the-report
- Parameter reference: https://www.interactivebrokers.com/docs/web-api/api-reference/send-request
- Retrieval: https://www.interactivebrokers.com/docs/web-api/flex-web-service/using-flex-web-service/retrieve-the-report
- Error codes: https://www.interactivebrokers.com/docs/web-api/flex-web-service/error-codes
- Query field reference: https://www.ibkrguides.com/reportingreference/reportguide/activity%20flex%20query%20reference.htm
- Gateway reauthentication: https://www.interactivebrokers.com/docs/web-api/authentication/cpgw/client-portal-gateway-faq
- OAuth 2.0 eligibility: https://www.interactivebrokers.com/docs/web-api/authentication/oauth-2/introduction
- OAuth 1.0a eligibility: https://www.interactivebrokers.com/docs/web-api/authentication/oauth-1a/introduction

XML parser upstream: https://github.com/tiran/defusedxml . It is a supporting dependency, not an IBKR SDK or an authentication provider.
