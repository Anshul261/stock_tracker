"""Local HTTP server: the workspace UI plus its owner-only API.

Binds to loopback only. Every API route except session, setup, sign-in and
reset needs a signed-in session cookie. Requests that change anything also
need the X-Still-Request header, which a cross-site form or image cannot send.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit
import csv
import io
import json
import mimetypes
import os
import re

from ibkr.flex import MAX_REPORT_BYTES, FlexClient, FlexError
from news.service import NewsError, NewsService

from .auth import COOKIE, Auth, AuthError
from .companies import Directory, SecError, valid_contact
from .portfolio import PortfolioError
from .prices import Prices, PriceError
from .paths import data_dir
from .store import Store
from .sync import Sync, SyncError

ROOT = Path(__file__).resolve().parents[1] / "prototype"
ASSETS = {"/": "index.html", "/index.html": "index.html", **{"/" + p: p for p in (
    "style.css", "data.js", "model.js", "boot.js", "gate.js", "settings.js", "companies.js", "app.js", "news.js", "news-sources.js",
    "assets/charts.js", "assets/public-sans.ttf", "assets/guide/menu.webp", "assets/guide/flex-queries.webp",
    "assets/guide/sections.webp", "assets/guide/delivery.webp", "assets/guide/review.webp", "assets/guide/query-id.webp",
    "assets/guide/token.webp")}}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
       "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
SEARCH_SECRETS = {"searxng": "search.searxng", "brave": "search.brave", "tavily": "search.tavily"}
SEARCH_ENV = {"SEARXNG_URL": "searxng", "BRAVE_SEARCH_API_KEY": "brave", "TAVILY_API_KEY": "tavily"}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class SearchSettings(Mapping):
    """News search configuration read live from the vault. Environment
    variables still override it, for development only."""

    def __init__(self, store: Store, auth: Auth):
        self.store, self.auth = store, auth

    def get(self, name, default=None):
        if name in os.environ:
            return os.environ[name]
        if name in SEARCH_ENV:
            key = self.auth.key
            return self.store.secret(key, SEARCH_SECRETS[SEARCH_ENV[name]]) if key else default
        if name == "STILL_NEWS_USER_AGENT":
            # SEC's fair-access policy asks every app to identify itself with a contact email.
            contact = self.store.setting("secContact")
            return f"Still/0.1 ({contact})" if contact else default
        if name == "STILL_SEARCH_CALL_LIMIT":
            return str((self.store.setting("search") or {}).get("limit", 50))
        return default

    def __getitem__(self, name):
        value = self.get(name)
        if value is None:
            raise KeyError(name)
        return value

    def __iter__(self):
        return iter(SEARCH_ENV)

    def __len__(self):
        return len(SEARCH_ENV)


class App:
    def __init__(self, folder: Path | None = None, *, news: NewsService | None = None, companies: Directory | None = None,
                 prices: Prices | None = None,
                 client_factory=FlexClient,
                 today=date.today):
        self.store = Store(folder or data_dir())
        self.auth = Auth(self.store)
        self.sync = Sync(self.store, self.auth, client_factory=client_factory, today=today)
        self.news = news or NewsService(env=SearchSettings(self.store, self.auth))
        self.companies = companies or Directory(self.store.folder, lambda: self.store.setting("secContact"))
        self.prices = prices or Prices(self.store, self.auth)
        self.server: ThreadingHTTPServer | None = None

    # Session ----------------------------------------------------------------
    def session(self, h, body):
        return {"state": self.auth.state(), "signedIn": h.signed_in, "mode": self.store.setting("mode")
                if h.signed_in else None}

    def setup(self, h, body):
        mode = body.get("mode", "ibkr")
        if mode not in ("ibkr", "demo"):
            raise ApiError(400, "Choose IBKR or demo data.")
        h.cookie = self.auth.setup(body.get("passphrase"))
        self.store.set_setting("mode", mode)
        return {"state": "unlocked", "mode": mode}

    def login(self, h, body):
        h.cookie = self.auth.login(body.get("passphrase"))
        self.sync.rebuild()
        return {"state": "unlocked", "mode": self.store.setting("mode")}

    def logout(self, h, body):
        self.auth.logout(h.token)
        h.cookie = ""
        return {"ok": True}

    def lock(self, h, body):
        self.auth.lock_now()
        self.sync.rebuild()
        h.cookie = ""
        return {"state": "locked"}

    def reset(self, h, body):
        if body.get("confirm") != "RESET":
            raise ApiError(400, "Type RESET to confirm.")
        if self.sync.thread and self.sync.thread.is_alive():
            raise ApiError(409, "Wait for the running sync to finish, then reset.")
        self.auth.reset()
        self.sync.rebuild()
        h.cookie = ""
        return {"state": "setup"}

    def quit(self, h, body):
        self.sync.stop()
        Thread(target=self.server.shutdown, daemon=True).start()
        return {"ok": True}

    # Settings ---------------------------------------------------------------
    def settings(self, h, body):
        return {"mode": self.store.setting("mode"), "autoLockMinutes": self.store.setting("autoLockMinutes"),
                "dataDir": str(self.store.folder), "reports": len(self.store.reports())}

    def save_settings(self, h, body):
        if "mode" in body:
            if body["mode"] not in ("ibkr", "demo"):
                raise ApiError(400, "Choose IBKR or demo data.")
            self.store.set_setting("mode", body["mode"])
        if "autoLockMinutes" in body:
            minutes = body["autoLockMinutes"]
            if not isinstance(minutes, int) or not 5 <= minutes <= 480:
                raise ApiError(400, "Choose an auto-lock time between 5 and 480 minutes.")
            self.store.set_setting("autoLockMinutes", minutes)
        return self.settings(h, body)

    def change_passphrase(self, h, body):
        self.auth.change_passphrase(body.get("current"), body.get("new"))
        return {"ok": True}

    # Portfolio --------------------------------------------------------------
    def portfolio(self, h, body):
        if self.sync.view is None and self.sync.view_error is None and self.store.reports():
            self.sync.rebuild()
        return {"mode": self.store.setting("mode"), "view": self.sync.view, "error": self.sync.view_error,
                "prices": self.prices.configured()}

    def export_holdings(self, h, body):
        view = self.sync.view
        if not view:
            raise ApiError(404, "Import a report first.")
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["symbol", "name", "asset_class", "currency", "quantity", "mark_price", "cost_per_unit",
                         "fx_to_base", "as_of"])
        for p in view["positions"]:
            writer.writerow([p["symbol"], p["name"], p["sector"], p["currency"], p["qty"], p["price"], p["cost"],
                             p["fx"], view["asOf"]])
        for c in view["cash"]:
            writer.writerow(["CASH", c["currency"] + " cash", "Cash", c["currency"], c["amount"], 1, 1, "", view["asOf"]])
        return ("text/csv; charset=utf-8", out.getvalue().encode(), f"still-holdings-{view['asOf']}.csv")

    # IBKR -------------------------------------------------------------------
    def ibkr(self, h, body):
        runs = self.store.runs(20)
        last_ok = next((r for r in runs if r["status"] == "ok"), None)
        last_sync = next((r for r in runs if r["status"] == "ok" and r["kind"] != "upload"), None)
        last = runs[0] if runs else None
        attention = (last or {}).get("summary", {}).get("attention") if last and last["status"] == "failed" else None
        view = self.sync.view
        return {
            "queryIdSaved": self.store.has_secret("ibkr.queryId"), "tokenSaved": self.store.has_secret("ibkr.token"),
            "tokenSavedAt": self.store.setting("tokenSavedAt"), "tokenExpires": self.store.setting("tokenExpires"),
            "fromInception": self.store.setting("fromInception"), "schedule": self.store.setting("schedule"),
            "job": self.sync.status(), "runs": runs, "lastSuccess": last_ok["finished"] if last_ok else None,
            "lastSync": last_sync["finished"] if last_sync else None,
            "attention": attention, "reports": self.store.reports(),
            "reconciliation": view["reconciliation"] if view else None,
            "asOf": view["asOf"] if view else None, "summary": view["summary"] if view else None,
            "coverageStart": view["coverageStart"] if view else None, "firstActivity": view["firstActivity"] if view else None,
            "viewError": self.sync.view_error,
        }

    def save_credentials(self, h, body):
        query, token, expires = body.get("queryId"), body.get("token"), body.get("tokenExpires")
        key = self.auth.key
        if query in (None, "") and self.store.has_secret("ibkr.queryId"):
            query = self.store.secret(key, "ibkr.queryId")
        if not isinstance(query, str) or not re.fullmatch(r"[0-9]{1,32}", query.strip()):
            raise ApiError(400, "The Flex Query ID contains digits only; find it with the query's information button.")
        if token in (None, ""):
            if not self.store.has_secret("ibkr.token"):
                raise ApiError(400, "Paste your Flex Web Service token.")
            token = None
        elif not isinstance(token, str):
            raise ApiError(400, "Paste your Flex Web Service token.")
        if expires not in (None, ""):
            try:
                expires = date.fromisoformat(expires).isoformat()
            except (TypeError, ValueError):
                raise ApiError(400, "Enter the token's expiry as a date.") from None
        if token and (len(token.strip()) > 4096 or any(c.isspace() for c in token.strip())):
            raise ApiError(400, "Paste the token exactly as Client Portal shows it, with no spaces.")
        self.store.set_secret(key, "ibkr.queryId", query.strip())
        if token:
            self.store.set_secret(key, "ibkr.token", token.strip())
            self.store.set_setting("tokenSavedAt", date.today().isoformat())
        self.store.set_setting("tokenExpires", expires or None)
        if self.store.setting("mode") != "ibkr":
            self.store.set_setting("mode", "ibkr")
        return self.ibkr(h, body)

    def save_options(self, h, body):
        if "fromInception" in body:
            if not isinstance(body["fromInception"], bool):
                raise ApiError(400, "Invalid option.")
            self.store.set_setting("fromInception", body["fromInception"])
            self.sync.rebuild()
        if "schedule" in body:
            schedule = body["schedule"]
            if not isinstance(schedule, dict) or not isinstance(schedule.get("enabled"), bool) or \
                    not re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", str(schedule.get("time", ""))):
                raise ApiError(400, "Choose a daily time such as 07:00.")
            self.store.set_setting("schedule", {"enabled": schedule["enabled"], "time": schedule["time"]})
        return self.ibkr(h, body)

    def start_sync(self, h, body):
        return {"job": self.sync.start("sync")}

    def start_history(self, h, body):
        try:
            start = date.fromisoformat(body.get("fromDate") or "")
        except ValueError:
            raise ApiError(400, "Choose the first date to import.") from None
        return {"job": self.sync.start("history", start)}

    def upload(self, h, body):
        return self.sync.upload(body)

    def disconnect(self, h, body):
        key = self.auth.key
        for name in ("ibkr.token", "ibkr.queryId"):
            self.store.set_secret(key, name, None)
        self.store.set_setting("tokenSavedAt", None)
        self.store.set_setting("tokenExpires", None)
        self.store.set_setting("schedule", {**self.store.setting("schedule"), "enabled": False})
        return self.ibkr(h, body)

    def delete_data(self, h, body):
        if body.get("confirm") != "DELETE":
            raise ApiError(400, "Type DELETE to confirm.")
        if self.sync.thread and self.sync.thread.is_alive():
            raise ApiError(409, "Wait for the running sync to finish.")
        self.store.delete_reports()
        self.sync.rebuild()
        return self.ibkr(h, body)

    # News -------------------------------------------------------------------
    def news_config(self, h, body):
        return self.news.config()

    def news_feed(self, h, body):
        result = self.news.feeds()
        return {**result, "sources": [{k: v for k, v in s.items() if not k.startswith("_")} for s in result["sources"]]}

    def news_search(self, h, body):
        if set(body) != {"query", "provider", "period"}:
            raise ApiError(400, "Invalid search request.")
        return self.news.search(body["query"], body["provider"], body["period"])

    def search_settings(self, h, body):
        settings = self.store.setting("search") or {}
        return {"provider": settings.get("provider"), "limit": settings.get("limit", 50),
                "secContact": self.store.setting("secContact"),
                "configured": {p: self.store.has_secret(SEARCH_SECRETS[p]) or bool(os.environ.get(e))
                               for e, p in SEARCH_ENV.items()}}

    def save_search_settings(self, h, body):
        provider, value, limit = body.get("provider"), body.get("value"), body.get("limit")
        settings = dict(self.store.setting("search") or {})
        if "secContact" in body:
            contact = body["secContact"]
            self.store.set_setting("secContact", valid_contact(contact) if contact not in (None, "") else None)
            self.companies.entries = None  # Reload lists with the new identity on next use.
        if provider is not None:
            if provider not in SEARCH_SECRETS:
                raise ApiError(400, "Choose SearXNG, Brave or Tavily.")
            if value not in (None, ""):
                if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value.strip()):
                    raise ApiError(400, "Paste the key or address without spaces.")
                value = value.strip()
                if provider == "searxng":
                    parts = urlsplit(value)
                    local = parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1", "::1")
                    if not (parts.scheme == "https" or local) or not parts.hostname or parts.username or parts.query:
                        raise ApiError(400, "Use an HTTPS SearXNG address, or http:// on this computer only.")
                self.store.set_secret(self.auth.key, SEARCH_SECRETS[provider], value)
            elif not self.store.has_secret(SEARCH_SECRETS[provider]):
                raise ApiError(400, "Paste the key or address for this provider.")
            settings["provider"] = provider
        if limit is not None:
            if not isinstance(limit, int) or not 1 <= limit <= 1000:
                raise ApiError(400, "Choose a search limit between 1 and 1,000.")
            settings["limit"] = limit
        self.store.set_setting("search", settings)
        return self.search_settings(h, body)

    # Companies -------------------------------------------------------------
    def company_search(self, h, body):
        query = (h.query.get("q") or [""])[0]
        if not self.store.setting("secContact"):
            return {"results": [], "needsContact": True}
        return {"results": self.companies.search(query), "needsContact": False}

    def company_profile(self, h, body):
        ticker = (h.query.get("ticker") or [""])[0]
        if not re.fullmatch(r"[A-Za-z0-9.\- ]{1,16}", ticker):
            raise ApiError(400, "Invalid ticker.")
        return self.companies.profile(ticker)

    # Prices ----------------------------------------------------------------
    def price_settings(self, h, body):
        return {"configured": self.prices.configured(), "savedAt": self.store.setting("pricesSavedAt")}

    def save_price_settings(self, h, body):
        quote = self.prices.save_keys(body.get("keyId"), body.get("secret"))
        return {**self.price_settings(h, body), "test": quote}

    def remove_price_settings(self, h, body):
        self.prices.remove_keys()
        return self.price_settings(h, body)

    def price_quotes(self, h, body):
        symbols = [s for s in ",".join(h.query.get("symbols") or []).split(",") if re.fullmatch(r"[A-Za-z0-9.\- ]{1,16}", s)]
        return {"quotes": self.prices.quotes(symbols), "asOf": self.prices.now().isoformat(timespec="seconds")}

    def price_history(self, h, body):
        symbol, range_key = (h.query.get("symbol") or [""])[0], (h.query.get("range") or ["1Y"])[0]
        if not re.fullmatch(r"[A-Za-z0-9.\- ]{1,16}", symbol) or range_key not in ("1M", "3M", "YTD", "1Y", "5Y", "ALL"):
            raise ApiError(400, "Invalid price history request.")
        return {"symbol": symbol, "range": range_key, "bars": self.prices.history(symbol, range_key)}

    def price_portfolio(self, h, body):
        if self.sync.ledger is None and self.store.reports():
            self.sync.rebuild()
        return self.prices.portfolio(self.sync.ledger)

    def remove_search_provider(self, h, body):
        provider = body.get("provider")
        if provider not in SEARCH_SECRETS:
            raise ApiError(400, "Choose SearXNG, Brave or Tavily.")
        self.store.set_secret(self.auth.key, SEARCH_SECRETS[provider], None)
        settings = dict(self.store.setting("search") or {})
        if settings.get("provider") == provider:
            settings["provider"] = None
        self.store.set_setting("search", settings)
        return self.search_settings(h, body)

    def routes(self):
        public = {("GET", "/api/session"): self.session, ("POST", "/api/setup"): self.setup,
                  ("POST", "/api/login"): self.login, ("POST", "/api/reset"): self.reset,
                  ("POST", "/api/logout"): self.logout}
        private = {
            ("POST", "/api/lock"): self.lock, ("POST", "/api/quit"): self.quit,
            ("GET", "/api/settings"): self.settings, ("POST", "/api/settings"): self.save_settings,
            ("POST", "/api/security/passphrase"): self.change_passphrase,
            ("GET", "/api/portfolio"): self.portfolio, ("GET", "/api/export/holdings.csv"): self.export_holdings,
            ("GET", "/api/ibkr"): self.ibkr, ("POST", "/api/ibkr/credentials"): self.save_credentials,
            ("POST", "/api/ibkr/options"): self.save_options, ("POST", "/api/ibkr/sync"): self.start_sync,
            ("POST", "/api/ibkr/history"): self.start_history, ("POST", "/api/ibkr/upload"): self.upload,
            ("POST", "/api/ibkr/disconnect"): self.disconnect, ("POST", "/api/ibkr/delete-data"): self.delete_data,
            ("GET", "/api/news/config"): self.news_config, ("GET", "/api/news/feed"): self.news_feed,
            ("POST", "/api/news/search"): self.news_search,
            ("GET", "/api/search-settings"): self.search_settings,
            ("POST", "/api/search-settings"): self.save_search_settings,
            ("POST", "/api/search-settings/remove"): self.remove_search_provider,
            ("GET", "/api/companies/search"): self.company_search, ("GET", "/api/companies/profile"): self.company_profile,
            ("GET", "/api/prices/settings"): self.price_settings, ("POST", "/api/prices/settings"): self.save_price_settings,
            ("POST", "/api/prices/remove"): self.remove_price_settings, ("GET", "/api/prices/quotes"): self.price_quotes,
            ("GET", "/api/prices/history"): self.price_history, ("GET", "/api/prices/portfolio"): self.price_portfolio,
        }
        return public, private


class Handler(BaseHTTPRequestHandler):
    server_version = "Still"
    sys_version = ""

    def log_message(self, *args):
        pass  # No paths, queries, keys, account data or remote errors in logs.

    @property
    def app(self) -> App:
        return self.server.app

    def permitted(self, path: str) -> bool:
        port = self.server.server_port
        if self.headers.get("Host", "") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self.reply(403, {"error": "Use the local Still address."})
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            self.reply(403, {"error": "Cross-origin requests are not allowed."})
            return False
        # Opening the page from a link elsewhere is fine; calling the API from another site is not.
        navigation = self.command == "GET" and self.headers.get("Sec-Fetch-Mode") == "navigate" and not path.startswith("/api/")
        if self.headers.get("Sec-Fetch-Site") == "cross-site" and not navigation:
            self.reply(403, {"error": "Cross-site requests are not allowed."})
            return False
        return True

    def reply(self, status, data, content_type="application/json; charset=utf-8", filename=None):
        body = json.dumps(data).encode() if isinstance(data, dict) else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        cookie = getattr(self, "cookie", None)
        if cookie is not None:
            # No Secure flag: the app is served over http on loopback only.
            expiry = "; Max-Age=0" if cookie == "" else ""
            self.send_header("Set-Cookie", f"{COOKIE}={cookie}; HttpOnly; SameSite=Strict; Path=/{expiry}")
        self.end_headers()
        self.wfile.write(body)

    def read_token(self) -> str | None:
        try:
            jar = SimpleCookie(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        return jar[COOKIE].value if COOKIE in jar else None

    def handle_api(self, path: str):
        self.cookie, self.token = None, self.read_token()
        self.query = parse_qs(urlsplit(self.path).query, max_num_fields=10)
        self.signed_in = self.app.auth.check(self.token)
        public, private = self.app.routes()
        key = (self.command, path)
        if key not in public and key not in private:
            return self.reply(404, {"error": "Not found."})
        if self.command == "POST" and self.headers.get("X-Still-Request") != "1":
            return self.reply(403, {"error": "Missing request header."})
        if key in private and not self.signed_in:
            return self.reply(401, {"error": "Sign in to Still first.", "state": self.app.auth.state()})
        try:
            body = self.read_body(path) if self.command == "POST" else {}
            result = (public.get(key) or private[key])(self, body)
        except ApiError as error:
            return self.reply(error.status, {"error": str(error)})
        except (AuthError, SyncError, NewsError, FlexError, SecError, PriceError, PortfolioError) as error:
            return self.reply(400, {"error": str(error)})
        except Exception:
            return self.reply(500, {"error": "Something went wrong; nothing was shown or logged. Try again."})
        if isinstance(result, tuple):
            content_type, data, filename = result
            return self.reply(200, data, content_type, filename)
        self.reply(200, result)

    def read_body(self, path: str):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "Invalid request.") from None
        if path == "/api/ibkr/upload":
            if self.headers.get_content_type() not in ("application/xml", "text/xml"):
                raise ApiError(415, "Upload the report as an XML file.")
            if not 0 < length <= MAX_REPORT_BYTES:
                raise ApiError(413, "Choose an XML report under 32 MB.")
            return self.rfile.read(length)
        if length == 0:
            return {}
        if self.headers.get_content_type() != "application/json":
            raise ApiError(415, "Send a JSON request.")
        if not 0 < length <= 8192:
            raise ApiError(413, "Request exceeds the size limit.")
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, UnicodeError):
            raise ApiError(400, "Invalid request.") from None
        if not isinstance(data, dict):
            raise ApiError(400, "Invalid request.")
        return data

    def do_GET(self):
        path = urlsplit(self.path).path
        if not self.permitted(path):
            return
        if path.startswith("/api/"):
            return self.handle_api(path)
        if path in ASSETS:
            file = ROOT / ASSETS[path]
            if file.is_file():
                kind = "image/webp" if file.suffix == ".webp" else mimetypes.guess_type(str(file))[0]
                return self.reply(200, file.read_bytes(), kind or "application/octet-stream")
        self.reply(404, {"error": "Not found."})

    def do_POST(self):
        path = urlsplit(self.path).path
        if self.permitted(path):
            self.handle_api(path)


def create_server(port: int = 4173, app: App | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.app = app or App()
    server.app.server = server
    return server
