# Still

A fast, considered personal investing workspace. This is a functional UI prototype with synthetic data, not a connected portfolio service.

Private preview: https://still-investing-workspace.anshulraj.chatgpt.site (owner sign-in required). No WorkOS setup is needed for this demo's hosting access gate.

## Run

```sh
python -m http.server 4173 --bind 127.0.0.1 --directory prototype
```

Open http://127.0.0.1:4173 on the machine running the server. Remote execution loopback is not a public or device-accessible preview.

For a self-contained offline version, run `python build_prototype.py` and open `artifacts/still-prototype.html` in a browser. No installation or build dependencies are needed. Watchlist persistence is best effort; browser file-origin policies vary.

## Tabbed workspace

The current prototype follows the user's single-screen sketch: a thin navigation rail, persistent Portfolio/Discover/Research tabs, closable stock tabs, a searchable instrument list, and a resizable main canvas. Stock details and research results use in-page tabs, without modal drawers or a blurred background. Search is always visibly available; keyboard shortcuts are optional accelerators. Browser back/forward and open stock tabs are supported.

The split can be resized by pointer or with Left/Right, Home and End while the separator is focused. The layout button hides or restores the instrument list. Phones use the full main canvas and labeled bottom navigation.

Visual direction and the vendored SVG chart helper come from [taste-skill](https://github.com/Leonxlnx/taste-skill), MIT, upstream commit `6010f91a9935f1c167dfc500fb1a475681892e6b`. Public Sans is bundled from the official Google Fonts repository under SIL OFL. Both licenses ship with the source and standalone HTML. The chart helper has one local lifecycle change to disconnect old resize observers when switching tabs.

## Try

- Use the visible global search, or Command/Ctrl+K; navigate its results with arrow keys and Enter.
- Use Portfolio, Discover and Research; shortcuts 1, 2 and 3 select them. Open several stocks and switch their document tabs.
- Open a holding tab, inspect its Overview, Position and Research sections, and change its chart period.
- Search/sort holdings, filter by sector or positive daily moves, and switch between all companies and your watchlist.
- Use Discover filters, add/remove a watchlist company, and reload to verify persistence.
- Ask about concentration, growth or a 20% semiconductor shock. Inspect the inputs and calculations. Unsupported questions are explicitly declined.
- Press Escape to dismiss search suggestions. `/` focuses instrument search (Discover search on a phone).

All historical charts and prices are illustrative. Monetary position totals use integer cents. Returns exclude dividends, fees, tax and FX. No orders, imports, live feeds or real AI calls exist. The interface makes this explicit.

## Verification

`tests/test_prototype.py` uses Python Playwright and Chromium for functional and responsive browser tests. It checks independent numeric expectations, search, filters, sorting, scenario calculations, watchlist persistence, dialogs, unsupported input, network isolation, console errors and representative viewports. Test tools are development-only and do not ship with the prototype. Run the HTTP server first, then `python tests/test_prototype.py`.

Review `AUTH_DECISION.md` before connecting real financial data. See `IMPLEMENTATION_PLAN.md` and `PRODUCT_BRIEF.md` for the staged product plan.
