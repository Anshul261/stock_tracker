# Still

A fast, considered personal investing workspace. This is a functional UI prototype with synthetic data, not a connected portfolio service.

Private preview: https://still-investing-workspace.anshulraj.chatgpt.site (owner sign-in required). No WorkOS setup is needed for this demo's hosting access gate.

## Run

For the independent web app with news APIs (Python 3.10+):

```sh
python -m pip install --require-hashes -r requirements-ibkr.txt
python serve.py
```

Use a virtual environment; Windows/macOS/Linux steps and provider setup are in [news setup](docs/NEWS_SOURCES.md). A UI-only static preview can still use `python -m http.server 4173 --bind 127.0.0.1 --directory prototype`; it cannot run the news APIs.

Open http://127.0.0.1:4173 on the machine running the server. Remote execution loopback is not a public or device-accessible preview.

For a self-contained offline version, run `python build_prototype.py` and open `artifacts/still-prototype.html` in a browser. No installation or build dependencies are needed. Watchlist persistence is best effort; browser file-origin policies vary.

## Tabbed workspace

The current prototype follows the user's single-screen sketch: a thin navigation rail, persistent Portfolio/Discover/Research/News tabs, closable stock tabs, a searchable instrument list, and a resizable main canvas. Stock details and research results use in-page tabs, without modal drawers or a blurred background. Search is always visibly available; keyboard shortcuts are optional accelerators. Browser back/forward and open stock tabs are supported.

The split can be resized by pointer or with Left/Right, Home and End while the separator is focused. The layout button hides or restores the instrument list. Phones use the full main canvas and labeled bottom navigation.

Visual direction and the vendored SVG chart helper come from [taste-skill](https://github.com/Leonxlnx/taste-skill), MIT, upstream commit `6010f91a9935f1c167dfc500fb1a475681892e6b`. Public Sans is bundled from the official Google Fonts repository under SIL OFL. Both licenses ship with the source and standalone HTML. The chart helper has one local lifecycle change to disconnect old resize observers when switching tabs.

## Try

- Use the visible global search, or Command/Ctrl+K; navigate its results with arrow keys and Enter.
- Use Portfolio, Discover, Research and News; shortcuts 1–4 select them. Open several stocks and switch their document tabs.
- Open a holding tab, inspect its Overview, Position and Research sections, and change its chart period.
- Search/sort holdings, filter by sector or positive daily moves, and switch between all companies and your watchlist.
- Use Discover filters, add/remove a watchlist company, and reload to verify persistence.
- Ask about concentration, growth or a 20% semiconductor shock. Inspect the inputs and calculations. Unsupported questions are explicitly declined.
- Press Escape to dismiss search suggestions. `/` focuses instrument search (Discover search on a phone).

All historical charts and prices are illustrative. Monetary position totals use integer cents. Returns exclude dividends, fees, tax and FX. No orders, broker imports, live portfolio prices or real AI calls exist. Public news is separate and uses the standalone server. The interface makes this explicit.

## Verification

`tests/test_prototype.py` uses Python Playwright and Chromium for functional and responsive browser tests. It checks independent numeric expectations, search, filters, sorting, scenario calculations, watchlist persistence, dialogs, unsupported input, network isolation, console errors and representative viewports. Test tools are development-only and do not ship with the prototype. Run the HTTP server first, then `python tests/test_prototype.py`.

Review `AUTH_DECISION.md` before connecting real financial data. See `IMPLEMENTATION_PLAN.md` and `PRODUCT_BRIEF.md` for the staged product plan.

## IBKR reporting client

The first broker component now follows the official **Flex Web Service v3** reporting path. It is a local Python client, separate from the hosted synthetic UI. See [IBKR setup](docs/IBKR_SETUP.md) for official sources, Portal configuration, hidden token entry, network requirements and Windows/Linux commands.

Install with `python -m pip install --require-hashes -r requirements-ibkr.txt`, then use `python -m ibkr inspect <export.xml>` to validate an exported report offline, or `python -m ibkr fetch --query-id <id>` to request one (the token is prompted invisibly). A hosted worker can use secure environment bindings instead. No credentials have been configured and no live IBKR call has been validated here.

The client retrieves/validates the report envelope; normalizing and reconciling its financial fields remains a separate implementation gate. It does not wire private holdings into the demo UI or provide application sign-in. Run the offline contract/security suite with `python -m unittest discover -s tests -p test_ibkr_flex.py -v` after installing the pinned dependency.

## Independent news web app

Run `python serve.py` after installing the existing pinned XML dependency to open Still in an ordinary browser, independently of ChatGPT. News contains primary-source feeds (Federal Reserve, SEC and BLS), a finance-source search view and a source/provider directory. Stock tabs include a News section. Search supports self-hosted SearXNG, Tavily and Brave through server-side configuration, with no automatic transmission of portfolio data or paid-provider fallback.

For hidden key entry, run `python serve.py --search-provider tavily` (or `brave`). The local server is loopback-only and does not implement public hosting or real portfolio APIs. The existing Sites preview is static: its direct search links and source directory work, but live feed/search APIs require this server. See [news setup, source research and limits](docs/NEWS_SOURCES.md), including network restrictions and unverified live-provider availability.
