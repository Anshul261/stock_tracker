# Still workspace redesign

Source skill: Leonxlnx/taste-skill, commit 6010f91a9935f1c167dfc500fb1a475681892e6b.
App direction: data-terminal, seed 125807515. No redraws. The user's sketch overrides template composition: a 56px rail, persistent document tabs, a searchable context list and an adjustable full-width work area. The list is part of the workspace, never a modal or dimmed overlay.

Data inventory: eight synthetic equities/ETF positions, one opening purchase per holding, USD prices and costs, share counts, previous close, illustrative history, USD cash, explicit sectors, local watchlist preferences. The same cents-based dataset drives every view. No live broker or model requests. The owner inspects holdings, filters a universe and tests scenarios in long desktop sessions; phone navigation must remain usable.

Questions: Portfolio—what is my account worth and which positions explain it? Discover—which instrument meets the visible filters? Stock—how has its price changed relative to my purchase cost? Research—what does my exposure imply under an explicit shock?

Face: Public Sans genuinely bundled locally, neutral terminal surfaces, one blue line on selections and the main plot. The product's signature is the purchase-to-current comparison, backed by the same ledger as the position view. Symbols and figures are tabular. The top document tabs preserve an instrument and its context while the user switches tasks.

Grid: at 1440px, 56 rail + 300 list + 8 separator + 1076 canvas = 1440. Canvas gutters are 24px on each side. The split is keyboard and pointer adjustable. At phone widths the rail becomes bottom navigation and instrument details use the whole work area. Search and tab navigation stay outside scrolling content.

Acceptance: no stock/research dialogs; persistent visible search; no retained document scroll hiding Discover controls; browser back/forward; closable stock tabs; position/research subtabs; resize by mouse and keyboard; watchlist persistence; source calculations; responsive widths 320/390/768/1440; original portfolio totals retained; no external requests.


Settings update: the screen answers “Is IBKR connected, and how can I stop its access?” first. Keep the existing data-terminal direction and Public Sans. A flat connection summary, three truthful status facts, and inline disclosures carry the task. No simulated connected state or ineffective disconnect button. IBKR setup and broker-wide disabling lead to the official Portal; data/privacy stays on a page tab. No token entry until an owner-authorized server credential service exists.

News inventory: primary-source release headlines, publisher, publication date, retrieval time, source status and approved search domains. Personal owner uses the same document canvas and stock subtabs. First question: “What has been published, and where can I verify it?” Keep the existing data-terminal/Public Sans direction. Feed/Search/Sources are in-page tabs, with a visible query field and provider/range controls on Search. Source provenance is the signature element, not invented sentiment KPIs. No automatic portfolio-query expansion, copied articles, photography, overlays or side drawers. Source directory and direct search links remain usable in the static preview; backend absence is explicit rather than filled with mock news.
