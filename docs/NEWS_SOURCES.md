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

## Set up search in the app

Open Still and go to **Settings → News search**.

- **SearXNG:** enter the address of an instance you run, with `json` enabled in its `search.formats` configuration (see the [installation guide](https://docs.searxng.org/admin/installation.html)). Remote instances must use HTTPS; `http://` is accepted only on this computer.
- **Brave or Tavily:** paste your API key.
- **Storage:** keys and addresses are encrypted with your passphrase and never sent back to the browser. The last one you save becomes the default.
- **Search limit:** caps provider calls each time Still starts, as a safeguard against charges. Set hard spending limits with the provider too.

Feeds need no setup. Every News API route, like every other data route, requires the signed-in owner.

For development, the environment variables `SEARXNG_URL`, `BRAVE_SEARCH_API_KEY`, `TAVILY_API_KEY` and `STILL_SEARCH_CALL_LIMIT` override the saved settings. `.env` files are not loaded.

Search provider selection is explicit. There is no paid fallback, autocomplete request or automatic search on page open. Company News tabs prefill only a public company name and ticker; submission is still required. The search service cannot read holdings or broker credentials. The user can still type sensitive text, so the UI explains that a submitted query goes to the selected provider.

### What finance-only means

`news/sources.json` holds the approved domain list. Queries include a fixed financial context. Tavily receives a native `include_domains` restriction; Brave and SearXNG use financial context and the same strict server-side result URL filter. Every provider's returned URL must be HTTPS on an exact approved domain or its subdomain. Unknown hosts, suffix lookalikes, credentials in URLs, unusual ports and unsafe schemes are rejected. A second browser-side URL check protects rendering. This restricts sources; it cannot establish truth or guarantee that every page on a publisher's domain is financially relevant. Filtering can produce fewer results.

Known publication dates are filtered locally for the selected range. Unknown dates remain explicitly unknown; provider freshness filters do not always mean publication time. SearXNG has no week range, so its month range is narrowed locally where dates exist. Publication dates are never replaced with retrieval time.

### Limits and failure handling

- Feeds: fixed, reviewed endpoints only; 8-second request timeout, 2 MiB response cap, no redirects, verified TLS, safe RSS/Atom parsing without DTDs/entities, at most 100 entries/source. Three feeds fetch concurrently.
- Refresh: 10-minute in-process cache shared by concurrent requests. Failed sources retain their last successful data for up to 6 hours, marked stale with the original retrieval time. No fabricated fallback stories.
- Search: 10-minute cache, 64 cached query keys, 2-second spacing, default maximum 50 provider attempts per server run. Change the limit in Settings → News search (1 to 1,000). Failed attempts count too. Restart resets the process limit: this is **not** a monthly billing cap. Set provider-side hard spending limits as well.
- Feed and search errors do not expose remote bodies, credentials or request URLs. Queries use POST to the local API; provider-specific requests follow each provider's API contract.
- No analytics, remote article images, full-text crawling, AI summarization or sentiment trading signals.

If SEC requires an identifying User-Agent, set `STILL_NEWS_USER_AGENT` to your app name and a suitable contact address server-side. Do not impersonate another organization. A provider denial, changed endpoint, invalid feed or rate limit is surfaced as unavailable; it is not bypassed.

## Current verification and deployment boundary

The current Sites preview is static and includes News navigation, source information and direct finance-search links. It cannot execute the Python service. Its news page explicitly explains the missing backend and never presents fixtures as live stories. Live feed retrieval and in-app search run in the local Still app. A later standalone production deployment can implement these same API contracts behind owner authentication.

This development environment currently permits package/repository hosts but not `www.federalreserve.gov`, `www.sec.gov`, `www.bls.gov`, `api.search.brave.com`, `api.tavily.com` or a SearXNG instance. No live publisher/provider call was verified or network policy bypass attempted. No search key is configured. Offline transport and HTTP/browser tests validate parsing, security and UI contracts; real provider availability and account-plan access still need a live smoke test on an allowed network.

Tests:

```sh
uv run python -m unittest discover -s tests -p test_news.py -v
# With the static preview running and development-only Playwright/Chromium installed:
uv run python tests/test_news_ui.py
```

Additional official references: [Brave News API](https://api-dashboard.search.brave.com/documentation/services/news-search), [Tavily search parameters](https://docs.tavily.com/documentation/api-reference/endpoint/search), [Alpha Vantage limits](https://www.alphavantage.co/support/). Runtime dependencies are hash-pinned in `uv.lock` and `requirements.txt`; SearXNG is used through its documented HTTP API.
