# News and finance search

Reviewed against official documentation on 25 October 2026. This component has no ChatGPT API, plugin, or broker dependency.

## Recommended sources

| Source | Free access / constraints | Decision |
| --- | --- | --- |
| [Federal Reserve feeds](https://www.federalreserve.gov/feeds/feeds.htm) | Public RSS releases, no API key | Included for policy, banking and macro news |
| [SEC feeds](https://www.sec.gov/about/rss-feeds) | Public RSS; access controls and fair-access requirements apply | Included for regulatory announcements; not a replacement for company-specific EDGAR ingestion |
| [BLS feeds](https://www.bls.gov/help/hlp_rss.htm) | Public RSS, no API key | Included for economic releases |
| [SearXNG](https://docs.searxng.org/dev/search_api.html) | Free/open source; self-hosting has operating costs; upstream engine limits still apply | Best option for avoiding a commercial search API. Use your own JSON-enabled instance, not random public instances |
| [Tavily](https://www.tavily.com/pricing) | Currently lists 1,000 free credits/month without a card; basic search uses one credit | Optional hosted search, with an explicit server key and local attempt cap |
| [Brave Search](https://brave.com/search/api/) | Hosted API, account/key and a limited free allowance; pricing pages may change | Optional news index; verify your actual account plan rather than assuming unlimited free usage |
| [Alpha Vantage](https://www.alphavantage.co/documentation/#news-sentiment) | News/sentiment endpoint exists; free service generally limited to 25 calls/day for most datasets; endpoint availability depends on plan | Consider later for ticker-linked coverage. Not wired into this milestone |
| [DuckDuckGo Instant Answer API](https://github.com/duckduckgo/duckduckgo-publisher/blob/master/share/site/duckduckgo/api.tx) | Not a full search-results API | Do not scrape HTML or rely on it as a free full finance-search backend |

The included feeds are primary-source releases, not a comprehensive breaking-market newswire. Search can discover reporting from Reuters, FT, WSJ, Bloomberg, CNBC and other approved domains, but does not bypass paywalls or grant redistribution rights. Search access is not a publisher license. News titles link to the original publisher; the app does not fetch, summarize, or reproduce full articles. Review terms before a public or commercial release. No scraped commercial feed was enabled based solely on a third-party list of RSS URLs.

## Run the independent web app

Python 3.10+; Windows, macOS or Linux. From the repository root:

```sh
python -m venv .venv
# Windows:
.venv\Scripts\python -m pip install --require-hashes -r requirements-ibkr.txt
.venv\Scripts\python serve.py
# macOS / Linux:
.venv/bin/python -m pip install --require-hashes -r requirements-ibkr.txt
.venv/bin/python serve.py
```

Open `http://127.0.0.1:4173/#news/feed`. The existing requirement file contains the shared pinned `defusedxml` dependency; installing it does not connect IBKR. The server reads UI assets directly, so `build_prototype.py` is only needed for the standalone static preview bundle and source catalog generation.

The server binds only to loopback. It has a strict asset allowlist, Host/Origin checks, no CORS and no request logging. It is a personal local web app, **not an authenticated public hosting server**. Do not expose it with a tunnel or reverse proxy. Public hosting requires a production server and owner authentication/authorization, TLS, a shared quota/rate limiter and reviewed secrets handling. No real portfolio data is served by this server.

### Enable hosted search without putting a key in a command

```sh
python serve.py --search-provider tavily
# or
python serve.py --search-provider brave
```

Enter your own provider API key at the hidden prompt. It stays in process memory for that run; it is not written to the browser, Git, a config file or logs. Never enter an IBKR token here. Trusted server deployments may instead bind `TAVILY_API_KEY` or `BRAVE_SEARCH_API_KEY` through a secret manager. `.env` files are not loaded automatically.

For self-hosted SearXNG, enable `json` in its `search.formats` configuration and set the server-side `SEARXNG_URL` to your instance, for example `http://127.0.0.1:8888` for a local instance. Remote instances must use HTTPS. Follow the [official installation guide](https://docs.searxng.org/admin/installation.html) and [upstream repository](https://github.com/searxng/searxng); no SearXNG service was provisioned here. The instance URL is operator-controlled and cannot be supplied through the API/browser. We do not forward user credentials or keys to arbitrary remote instances.

Search provider selection is explicit. There is no paid fallback, autocomplete request or automatic search on page open. Company News tabs prefill only a public company name and ticker; submission is still required. The search service cannot read holdings or broker credentials. The user can still type sensitive text, so the UI explains that a submitted query goes to the selected provider.

### What finance-only means

`news/sources.json` holds the approved domain list. Queries include a fixed financial context. Tavily receives a native `include_domains` restriction; Brave and SearXNG use financial context and the same strict server-side result URL filter. Every provider's returned URL must be HTTPS on an exact approved domain or its subdomain. Unknown hosts, suffix lookalikes, credentials in URLs, unusual ports and unsafe schemes are rejected. A second browser-side URL check protects rendering. This restricts sources; it cannot establish truth or guarantee that every page on a publisher's domain is financially relevant. Filtering can produce fewer results.

Known publication dates are filtered locally for the selected range. Unknown dates remain explicitly unknown; provider freshness filters do not always mean publication time. SearXNG has no week range, so its month range is narrowed locally where dates exist. Publication dates are never replaced with retrieval time.

### Limits and failure handling

- Feeds: fixed, reviewed endpoints only; 8-second request timeout, 2 MiB response cap, no redirects, verified TLS, safe RSS/Atom parsing without DTDs/entities, at most 100 entries/source. Three feeds fetch concurrently.
- Refresh: 10-minute in-process cache shared by concurrent requests. Failed sources retain their last successful data for up to 6 hours, marked stale with the original retrieval time. No fabricated fallback stories.
- Search: 10-minute cache, 64 cached query keys, 2-second spacing, default maximum 50 provider attempts per server run. Set `STILL_SEARCH_CALL_LIMIT=0` to disable outbound searches or a lower/higher integer up to 1,000. Failed attempts count too. Restart resets the process limit: this is **not** a monthly billing cap. Set provider-side hard spending limits as well.
- Feed and search errors do not expose remote bodies, credentials or request URLs. Queries use POST to the local API; provider-specific requests follow each provider's API contract.
- No analytics, remote article images, full-text crawling, AI summarization or sentiment trading signals.

If SEC requires an identifying User-Agent, set `STILL_NEWS_USER_AGENT` to your app name and a suitable contact address server-side. Do not impersonate another organization. A provider denial, changed endpoint, invalid feed or rate limit is surfaced as unavailable; it is not bypassed.

## Current verification and deployment boundary

The current Sites preview is static and includes News navigation, source information and direct finance-search links. It cannot execute the Python service. Its news page explicitly explains the missing backend and never presents fixtures as live stories. Live feed retrieval and in-app search run through `serve.py` independently of Sites. A later standalone production deployment can implement these same API contracts behind owner authentication.

This development environment currently permits package/repository hosts but not `www.federalreserve.gov`, `www.sec.gov`, `www.bls.gov`, `api.search.brave.com`, `api.tavily.com` or a SearXNG instance. No live publisher/provider call was verified or network policy bypass attempted. No search key is configured. Offline transport and HTTP/browser tests validate parsing, security and UI contracts; real provider availability and account-plan access still need a live smoke test on an allowed network.

Tests:

```sh
python -m unittest discover -s tests -p test_news.py -v
# With the local server running and development-only Playwright/Chromium installed:
python tests/test_news_ui.py
```

Additional official references: [Brave News API](https://api-dashboard.search.brave.com/documentation/services/news-search), [Tavily search parameters](https://docs.tavily.com/documentation/api-reference/endpoint/search), [Alpha Vantage limits](https://www.alphavantage.co/support/). The only runtime dependency is the existing hash-pinned [defusedxml](https://github.com/tiran/defusedxml); SearXNG is used through its documented HTTP API.
