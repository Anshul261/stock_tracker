# Still

A fast, considered personal investing workspace for your Interactive Brokers account. Still runs only on your computer and opens in your browser. Setup, the IBKR connection, syncing, reconciliation review, news search keys, locking and deleting data all happen in the app; no terminal is needed after installation.

## Install once

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and download this folder.
2. Open Still with the launcher for your system, from the `launchers` folder:
   - **Windows:** `Still.bat`. If the folder lives inside WSL, use `Still (WSL).bat` instead.
   - **macOS:** `Still.command`.
   - **Linux:** `still.sh`.

   You can copy a shortcut to your desktop. The first launch downloads Still's two pinned Python dependencies.
3. Still opens in your browser at `http://127.0.0.1:4173` (another free port if that one is busy). It listens on this computer only.

## First run

1. **Create a passphrase.** It encrypts your IBKR token, search keys and every imported report. There is no recovery; a forgotten passphrase means resetting Still, which deletes its saved data but never touches your IBKR account.
2. **Choose IBKR or demo data.** Demo data is a clearly labelled synthetic portfolio, and you can switch at any time in Settings → Data & privacy.
3. **Settings → IBKR connection** walks through the rest:
   1. **Prepare Flex in IBKR.** Step-by-step Client Portal instructions for an Activity Flex Query (XML) and a Flex Web Service token.
   2. **Connect.** Paste the Query ID and token. The token is stored encrypted, never shown again, and sent only to IBKR's Flex service over HTTPS.
   3. **Import.** Choose **Sync now**, **Import history** (fetched a year at a time, as IBKR requires) or **Upload** a report you downloaded from Client Portal. Upload needs no token.
   4. **Reconciliation.** Still rebuilds positions, cash and FIFO cost basis from the report's own transactions and compares them with IBKR's totals. Every check is passed, failed or *unverified*. Unverified means the report alone can't settle it, and it is never counted as passed.
   5. **Daily sync.** Optional. It runs while Still is open and unlocked, and catches up on missed days.
   6. **Stop access.** Disconnect (forgets the token), delete imported reports, and IBKR's own steps to switch Flex off.

Portfolio, Discover and Research then show your imported holdings, with the report date in the status bar. Day-over-day change and value history appear once there are reports for two or more dates.

**Other settings**
- **Prices:** your own free Alpaca API key. It adds:
  - live quotes (IEX) for holdings and any company you open, refreshed every 30 seconds while Still is open
  - daily price history from all US exchanges
  - your portfolio's value for every trading day, rebuilt from your IBKR trades
  - a time-weighted return compared with the S&P 500 (SPY), with deposits kept out of returns
- **News & data:** a contact email for SEC (search every US-listed company and fund, read their filings), and a SearXNG address or a Brave or Tavily key for news search, plus a per-run search limit.
- **Security:** auto-lock time, lock now, change passphrase, quit Still.
- **Data & privacy:** where data is stored, export holdings as CSV, switch between IBKR and demo data, reset Still.

## Safety and IBKR's rules

- **Read-only.** Flex can only produce reports. It cannot trade, move money or change your account. Still has no order interface.
- **Local and encrypted.**
  - Everything lives in a per-user folder, shown in Settings → Data & privacy.
  - The token, search keys and reports are encrypted with AES-GCM under a key derived from your passphrase (scrypt).
  - Files are private to your user account, and nothing is logged.
- **Owner sign-in.**
  - Every data route needs a signed-in session: an HttpOnly, SameSite=Strict cookie with an idle timeout.
  - Requests that change anything also need a custom header, and requests from other sites or hosts are refused.
- **Your account, your machine.** This is IBKR's documented use of Flex. Read [staying within IBKR's Flex rules](docs/IBKR_SETUP.md#staying-within-ibkrs-flex-rules) before offering Still to anyone else.

## The workspace

- **Layout:** a thin navigation rail, persistent Portfolio/Discover/Research/News tabs, closable stock tabs, a searchable instrument list and a resizable main canvas.
- **Navigation:** search is always visible (Ctrl/Cmd+K, `/`), shortcuts 1–4 switch tabs, and browser back/forward work. Phones get the full canvas with labelled bottom navigation.
- **Research:** exposure by asset class and currency, a price shock on holdings you choose, and returns against IBKR cost basis. Every figure shows its inputs and calculation.
- **News:** primary-source feeds (Federal Reserve, SEC, BLS) and finance-domain search. See [news sources](docs/NEWS_SOURCES.md).

Visual direction and the vendored SVG chart helper come from [taste-skill](https://github.com/Leonxlnx/taste-skill), MIT, upstream commit `6010f91a9935f1c167dfc500fb1a475681892e6b`. The chart helper has two local changes: it disconnects old resize observers when switching tabs, and it escapes every label it writes as HTML. Public Sans is bundled under the SIL OFL. Both licenses ship with the source.

## For developers

- **Run from source:** `uv sync`, then `uv run python -m still` (`--port`, `--no-browser`). `STILL_DATA_DIR` points it at a scratch data folder. `python serve.py` is equivalent.
- **Without uv:** `python -m pip install --require-hashes -r requirements.txt`. That file is exported from `uv.lock`.
- **Code layout:**
  - `still/`: the local app (vault, store, auth, sync, portfolio view, HTTP server).
  - `ibkr/`: the Flex client, ledger and reconciliation.
  - `news/`: feeds and search.
  - `prototype/`: the browser UI.
- **Offline tests:** run `uv run python -m unittest discover -s tests -p PATTERN` with each of these patterns:
  - `'test_[aic]*.py'`: app, IBKR and companies
  - `test_prices.py`: prices
  - `test_news.py`: news

  They need no network, browser or credentials; SEC, Alpaca and IBKR are replaced by fakes.
- **Browser scripts:** `tests/test_prototype.py`, `test_settings.py`, `test_news_ui.py` and `test_ui_escaping.py` run against the static demo preview. Start it with `uv run python -m http.server 4173 --bind 127.0.0.1 --directory prototype`. Set `STILL_CHROMIUM` to a Chromium binary.
- **Command-line tools:** `python -m ibkr inspect | fetch | ledger` still exist for debugging; see [IBKR setup](docs/IBKR_SETUP.md#developer-command-line).
- **Offline demo build:** `uv run python build_prototype.py` writes a demo-only standalone HTML file to `artifacts/still-prototype.html`.

See `AUTH_DECISION.md`, `IMPLEMENTATION_PLAN.md` and `PRODUCT_BRIEF.md` for design decisions and the staged plan.
