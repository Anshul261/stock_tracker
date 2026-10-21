# Still

A fast, considered personal investing workspace. This is a functional UI prototype with synthetic data, not a connected portfolio service.

## Run

```sh
python -m http.server 4173 --bind 127.0.0.1 --directory prototype
```

Open http://127.0.0.1:4173 on the machine running the server. Remote execution loopback is not a public or device-accessible preview.

For a self-contained offline version, run `python build_prototype.py` and open `artifacts/still-prototype.html` in a browser. No installation or build dependencies are needed. Watchlist persistence is best effort; browser file-origin policies vary.

## Try

- Search with Command/Ctrl+K, navigate results with arrow keys and Enter.
- Use Overview, Discover and Research; keyboard shortcuts 1 and 2 select the first two.
- Select a holding, inspect purchase cost and return, and change its chart period.
- Search/sort holdings and filter positive daily moves.
- Use Discover filters, add/remove a watchlist company, and reload to verify persistence.
- Ask about concentration, growth or a 20% semiconductor shock. Inspect the inputs and calculations. Unsupported questions are explicitly declined.
- Press Escape to close a dialog; `/` focuses the holdings search.

All historical charts and prices are illustrative. Monetary position totals use integer cents. Returns exclude dividends, fees, tax and FX. No orders, imports, live feeds or real AI calls exist. The interface makes this explicit.

## Verification

`tests/test_prototype.py` uses Python Playwright and Chromium for functional and responsive browser tests. It checks independent numeric expectations, search, filters, sorting, scenario calculations, watchlist persistence, dialogs, unsupported input, network isolation, console errors and representative viewports. Test tools are development-only and do not ship with the prototype. Run the HTTP server first, then `python tests/test_prototype.py`.

Review `AUTH_DECISION.md` before connecting real financial data. See `IMPLEMENTATION_PLAN.md` and `PRODUCT_BRIEF.md` for the staged product plan.
