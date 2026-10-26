# Private stock research workspace

Research date: 21 October 2026. Current status (26 October 2026): local app with in-app setup, encrypted storage and IBKR import; see the local product milestone below. No live IBKR account has been connected yet. Browser checks passed at widths 320, 390, 768, 1024 and 1440. The prototype uses synthetic data and deterministic research templates; production performance budgets and accessibility audit remain pending.

The reviewed UI now uses persistent page and stock tabs, in-page research, visible search and an adjustable instrument/main split. This supersedes the original drawer-based prototype. IBKR integration, application authentication and live AI remain unimplemented.

IBKR component update: the official Flex v3 retrieval client and offline XML envelope validator are implemented under `ibkr/`, with 20 passing offline tests. Stage 2 has started (26 October 2026): `ibkr/ledger.py` normalizes Activity Flex XML into a Decimal ledger and `ibkr/reconcile.py` checks positions, cash, quantities and FIFO cost basis, with 31 more passing offline tests on synthetic reports, including a report that matches the prototype portfolio. The UI now escapes broker-supplied text. Transfers and non-split corporate actions are reported as unverified rather than modeled. Real-account reconciliation, application authentication and UI integration are still pending. The current environment has no broker secret bindings or IBKR egress grant. See `docs/IBKR_SETUP.md` for the official path and setup.

Private prototype: https://still-investing-workspace.anshulraj.chatgpt.site . The hosting platform enforces owner-only access. Application-level authentication is not implemented; see AUTH_DECISION.md before connecting real data.

## Decision

Product priority: exceptional interaction quality and perceived speed. Follow [PRODUCT_BRIEF.md](PRODUCT_BRIEF.md) for the experience and performance acceptance criteria.

Prototype the core experience with synthetic data before committing to the portfolio interface. Evaluate self-hosted Ghostfolio as the reusable portfolio foundation, with a small Python/FastAPI companion for imports, deterministic analytics and AI workflows. Use its existing interface only if it meets the experience brief; otherwise build a small custom frontend over supported service interfaces, without forking the full application. Validate the required read interfaces and licensing in the component trial before committing to that integration. Keep upstream upgrades independent of the companion service. Use PostgreSQL, with separate application ownership and permissions.

IBKR remains the source for personal transactions and account statements, not the only source for security research. Start with exported Activity Flex XML; automate report retrieval later. Use separate market-data adapters for quotes, adjusted history and FX, and primary filings for research. Default to end-of-day analysis; streaming data adds subscriptions, session handling and operational work without being necessary for the initial use cases.

## Stages and completion gates

| Stage | Deliverable | Complete when |
| --- | --- | --- |
| 0. Experience prototype | Portfolio overview, searchable holdings and one stock detail view with synthetic data; reusable visual tokens | Core tasks work by mouse and keyboard, responsive and accessible states are reviewed, and measured interaction timings meet the product brief on a documented reference device |
| 1. Private foundation and component trial | Pinned Ghostfolio release, companion skeleton, private networking, authentication, secret separation, synthetic portfolio and backup process | Unauthenticated requests fail, database is not publicly reachable, backup restores, dependency/advisory review is recorded, and Ghostfolio can represent the synthetic transactions through supported interfaces |
| 2. Reliable portfolio ledger | Activity Flex importer; retained original reports; duplicate prevention; trades, fees, dividends, withholding, cash, FX and corporate actions; purchase lots and cost basis | Reimports are idempotent; malformed XML is rejected safely; partial sales, splits and multicurrency examples pass; balances reconcile with a reference statement. Real-account reconciliation requires a user export |
| 3. Screener and conventional analysis | Holdings/watchlist filters, price charts, realized/unrealized P&L, total return, allocations, drawdown, time-weighted return and money-weighted return/XIRR where data supports them | Calculations pass independent reference examples; every value shows source, currency and observation date; stale/missing data is visible; deposits are not reported as investment gains |
| 4. AI research assistance | Natural-language screening, portfolio exposure questions and filing summaries through a small allowlist of read-only tools | Numeric claims come from calculation outputs, research claims link to supporting passages, unsupported questions can abstain, and evaluation cases check accuracy, latency, cost, privacy and prompt injection resistance |
| 5. Scenarios and projections | Explicit price/FX shocks, recurring contributions, inflation/fees assumptions, historical scenarios and Monte Carlo ranges | Results reproduce with fixed inputs/seeds; assumptions and limitations are visible; backtests account for point-in-time availability and relevant biases |

Deliver an independently usable result after each stage. Add scheduled IBKR Flex retrieval after manual imports are reconciled. Add remote access only when needed, through a private VPN with MFA and application authentication. Do not create any brokerage order interface.

## Financial correctness

Use decimal arithmetic for money and explicit currency units. Map instruments using IBKR identifiers plus exchange/currency rather than ticker alone. Record transaction time, price time, market timezone and FX time. Handle amendments/cancellations separately from duplicates. Reconcile quantities and cash first; document cost-basis conventions because economic P&L and tax reports can differ. Preserve opening positions when complete purchase history is unavailable, and label historical returns as incomplete.

## Privacy and AI boundary

Development uses synthetic data. Real data should live on the user's computer or chosen private host; this managed cloud environment is not equivalent to local-only storage. Hosted models receive submitted inputs, so disable external transmission of private portfolio data by default. Start hosted-model experiments with public filings; use local models for private questions unless an explicit data-sharing choice is made later.

The ingestion service owns brokerage report credentials. Models receive neither credentials nor arbitrary database/shell/network access. Keep ingestion write permissions separate from AI read permissions. Ghostfolio's experimental MCP supports both read and manage permissions: use only the required view permission if adopting it, and verify the pinned release's actual behavior. Treat filings, news and tool outputs as untrusted content, never instructions. Redact sensitive logs and keep raw imports and backups out of Git.

Jev is optional for routing or tagging public documents. Evaluate it against simple rules and the chosen LLM before introducing a second mandatory model. Its confidence is not proof that an investment claim is true. Code computes financial results; models interpret intent and explain evidence.

## Reuse and source policy

- Ghostfolio: preferred portfolio application; upstream AGPLv3, container distribution and portfolio interfaces. Pin a reviewed version and image digest at implementation time; review licensing before distributing modifications.
- Portfolio Performance: credible desktop alternative and useful independent reconciliation tool, with documented IBKR Flex imports. Prefer it if desktop portfolio accounting becomes the primary requirement.
- TradingView Lightweight Charts: reuse for custom research charts, observing license and attribution requirements. The chart library does not supply market data.
- OpenBB: evaluate selected data connectors only if they save work; do not make the full platform a prerequisite. Provider coverage, keys and licenses remain separate.
- SEC EDGAR and company investor-relations pages: primary filing sources for covered issuers. EDGAR does not provide complete global fundamentals or a price feed. Respect SEC fair-access rules.
- Select the price/fundamentals provider after confirming held exchanges, asset coverage and budget. Verify splits, dividends, adjusted history, FX, timestamps, quotas and personal-use rights with official documentation. No paid subscriptions are selected or purchased in this plan.

Upstream provenance is a starting point, not a security audit. Before execution, review release artifacts, security advisories, direct/transitive dependencies, credentials, outbound destinations and update strategy. Use official upstream repositories; avoid unreviewed IBKR sync scripts and unofficial Jev gateways handling credentials.

## Environment and remaining inputs

The workspace now contains the prototype, its standalone HTML build, verification script and screenshots. Runtime inspection found no configured broker/model secrets or outbound identities. The enforced outbound policy permits repositories/package registries but does not currently list IBKR, SEC or model/provider hosts. Live integration needs those specific destinations enabled through environment configuration. Synthetic-data development can proceed independently.

Later inputs: a user-generated Activity Flex export for reconciliation, preferred reporting currency, covered markets, and a deployment target. These do not block stage 1. Never request an IBKR password in chat.

## Primary sources reviewed

- IBKR API overview: https://www.interactivebrokers.com/docs/
- IBKR Flex configuration and credential model: https://www.interactivebrokers.com/docs/web-api/flex-web-service/client-portal-configuration
- IBKR Flex report generation: https://www.interactivebrokers.com/docs/web-api/flex-web-service/using-flex-web-service/generate-the-report
- Ghostfolio upstream, self-hosting, license and MCP permissions: https://github.com/ghostfolio/ghostfolio
- Ghostfolio security policy: https://github.com/ghostfolio/ghostfolio/security
- Ghostfolio release observed during research: https://github.com/ghostfolio/ghostfolio/releases/tag/3.88.0
- Portfolio Performance upstream: https://github.com/portfolio-performance/portfolio
- Portfolio Performance IBKR importer: https://help.portfolio-performance.info/en/reference/file/import/ibflex-import/
- TradingView chart upstream: https://github.com/tradingview/lightweight-charts
- OpenBB upstream entry point: https://github.com/OpenBB-finance/OpenBB (redirects to openbq-org/OpenBB at research time)
- OpenBB provider documentation: https://docs.openbb.co/odp/v4/python/extensions/providers
- SEC EDGAR API documentation: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- Jev official documentation: https://docs.typesafe.ai/introduction

## News milestone — 25 October 2026

Implemented: independent loopback web server; public feed adapters for Fed/SEC/BLS; explicit SearXNG, Brave and Tavily search; post-filtered finance-domain results; timestamps/staleness; caches and process attempt caps; full-page News and stock News section. Static Sites preview retains source links and external finance searches, with an explicit backend-needed state.

Next: smoke-test real feeds and one selected provider with allowed egress and the user's own account; validate freshness/coverage against user needs; deploy a production backend with owner authentication, managed secrets, shared quotas and no account data in logs. Company-specific EDGAR/IR feeds can follow after these basic contracts are verified. No full-text redistribution or AI sentiment pipeline is enabled.

## Local product milestone — 26 October 2026

Implemented: Still now runs as a local app (`python -m still`, or the launchers in `launchers/`) with everything set up in the UI:
- **Access:** first-run passphrase, unlock screen, lock, auto-lock, passphrase change, reset and quit.
- **Storage:** an encrypted vault for the IBKR token, Query ID, search keys and reports.
- **IBKR connection in Settings:** credentials, Sync now, chunked history import, upload, daily schedule, reconciliation review, sync history, disconnect and delete data.
- **Search providers in Settings.**
- **Workspace views:** Portfolio, Discover and Research render imported IBKR data (base-currency values, report dates, change since the previous report, report-date history, trade history per holding), with demo data clearly separated.
- **Tests:** 23 new offline tests cover the vault, sign-in, API guards, the sync worker (fake IBKR transport) and the portfolio view.
- **Manual check:** the in-app flow was checked end to end in Chrome with synthetic reports.

Next:
1. Run a live sync and reconciliation with the owner's own IBKR export, and fix field-name or section differences.
2. Model transfers and non-split corporate actions.
3. Package single-file installers before any distribution.
4. Have counsel review terms before selling (see `docs/IBKR_SETUP.md`).
