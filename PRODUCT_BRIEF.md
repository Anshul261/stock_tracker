# Product brief: a personal investing workspace with taste

User direction: speed, ease of use and taste are the highest product priorities. Financial correctness and privacy remain requirements. Status: design direction and acceptance targets; implementation and measurements are pending.

## Workspace revision after user review

The user rejected modal stock/research drawers and hidden navigation. Their sketch is the controlling composition: a thin utility rail, persistent document tabs, a searchable instrument pane and an adjustable main work area. Stocks open as closable tabs; their Overview, Position and Research sections live in the main canvas. Portfolio, Discover and Research are always reachable through labeled top tabs. Research uses Exposure, Scenarios and Performance tabs. Search stays visible outside the scrolling instrument list; global search is an ordinary visible input with Ctrl/Cmd+K as an additional route. On phones, the main canvas uses the full width and the rail becomes labeled bottom navigation. No stock or research dialog dims the application.

The implementation follows Leonxlnx/taste-skill's Data terminal app direction, seed 125807515, with locally bundled Public Sans, neutral surfaces and restrained blue selection lines. This revision supersedes the earlier warm-green visual direction below. See `.taste-skill/design-notes.md` and `.taste-skill/review.md` for the reviewed design and checks.

## The experience

Open the app and understand how the portfolio is doing immediately. Select a holding and see its chart, purchase history and return without losing place. Ask a question in context and get an inspectable answer alongside the relevant view.

The terminal screenshot supplies ideas for linked information. The initial experience should use deliberate hierarchy and progressive disclosure: overview first, detail on selection, deeper research when requested.

## Three destinations

- Portfolio: value, gain/loss with a clearly named period and calculation basis, performance chart, and a compact holdings table. Monetary changes and percentage returns must be clearly distinguished. Selecting a holding opens its details while preserving scroll, filters and selection.
- Discover: a searchable watchlist and screener. Filters update a local result set immediately when possible. Natural-language requests become visible editable filter chips. Missing coverage and empty results explain the next action.
- Research: saved analyses and cited documents, with an assistant available within each destination. Answers can open the relevant chart or filtered view; sources are expandable alongside claims.

## Visual direction

Use a restrained dark palette with warm neutral surfaces, strong typography, tabular numerals, generous spacing and one accent color. Reserve gain/loss colors for financial meaning; accompany color with signs or labels. Keep charts quiet, with clear hover values and optional benchmark overlays. Use concise labels and a consistent precision policy for prices, money and percentages.

Give each screen one dominant task. Show fewer metrics with stronger hierarchy. Use subtle transitions only when they communicate a state change; honor reduced-motion preferences. Avoid decorative motion, stock imagery, dense widget walls and mandatory chat as the way to navigate.

## Interaction contract

- Command/Ctrl+K searches instruments and actions from anywhere; ordinary visible controls expose the same functions.
- Keyboard navigation supports search results, holdings, dialogs and detail panels. Focus remains visible and returns to the initiating control after dismissal.
- Preserve navigation context, chart period and filter state. Save useful screens and questions locally.
- Display cached results immediately with observation time; refresh in the background and mark stale or failed data explicitly. Never imply cached data is live.
- Keep imports, sync and AI asynchronous. Show progress, cancellation and retry without blocking navigation.
- Use optimistic updates only for reversible UI preferences and watchlists, with rollback on failure. Financial imports and calculations require confirmed results.
- Provide intentional loading, empty, stale, error and offline states. Explain failures at the affected component rather than replacing the whole application.
- Support narrow screens, accessible contrast, labeled controls and zoom. Hover must not be the only way to discover essential information.

## Proposed performance budgets

Measure production builds with a synthetic portfolio of 250 holdings and 10,000 transactions on a documented device/browser and deployment topology. Record both cold and warm paths, p50/p95, and whether results came from cache. These are targets, not observed results.

| Interaction | Target |
| --- | --- |
| Visible acknowledgement of an input | Within 100 ms |
| Warm navigation or cached holding detail | p95 within 200 ms |
| Search/filter over already loaded holdings | p95 within 100 ms |
| Warm local analytics response for the reference dataset | p95 within 300 ms |
| Initial primary content, cold load | Within 2 seconds on the documented reference connection |
| AI request | Immediate acknowledgement; independent progress/cancel state; measure provider-dependent time to useful output separately |

Meet budgets through small payloads, indexed queries, cached calculations keyed by data version, background refresh, request cancellation and selective prefetching. Virtualize long lists when measurements justify it. A model call is never a dependency for opening a screen or computing standard financial metrics.

## First prototype and review

Build a polished vertical slice: open Portfolio, search a stock, inspect purchase-to-current performance, change the chart period, and open a clearly labeled synthetic example of an AI explanation. Exercise keyboard, mobile, empty, stale and error states. Review visual hierarchy and measure the interactions before expanding features. Synthetic explanations must never appear to be live model research.

Reuse charting, accessibility primitives and portfolio services wherever they meet the brief. Keep the custom surface small enough to preserve fast delivery and maintainability. The Ghostfolio component trial must establish whether required data can be accessed through supported interfaces; an unsuitable integration should be reconsidered before building a large adapter.
