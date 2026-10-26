"""Bounded primary-source feeds and finance-domain search, with injectable transport."""
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler
from defusedxml import ElementTree
import hashlib
import json
import os
import re
import ssl
import threading
import time

CATALOG = json.loads(Path(__file__).with_name('sources.json').read_text())
MAX_BYTES = 2 * 1024 * 1024
TTL, STALE_LIMIT = 600, 21600

class NewsError(Exception):
    """Messages are fixed safe text, never remote response bodies or URLs."""

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)

def plain(value, limit=300):
    parser = Text()
    parser.feed(str(value or '')[:8000])
    return ' '.join(' '.join(parser.parts).split())[:limit]

def approved_url(value, domains):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parts = urlsplit(value)
        host = (parts.hostname or '').lower()
        if parts.scheme != 'https' or parts.username or parts.password or parts.port not in (443, None):
            return None
        if not any(host == d or host.endswith('.'+d) for d in domains):
            return None
        # Feed URLs sometimes carry attribution queries; never retain fragments.
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))
    except ValueError:
        return None

def timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    if dt.tzinfo is None:
        return None
    try:
        return dt.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except (ValueError, OverflowError):
        return None

def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

def canonical(url):
    p = urlsplit(url)
    return (p.hostname or '') + p.path.rstrip('/')

def article(title, url, source, category, published):
    return {'id': hashlib.sha256(canonical(url).encode()).hexdigest()[:20],
            'title': plain(title, 220), 'url': url, 'source': source,
            'category': category, 'publishedAt': timestamp(published)}

def deduplicate(items):
    seen, result = set(), []
    for item in items:
        key = canonical(item['url'])
        if not item['title'] or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return sorted(result, key=lambda x: x['publishedAt'] or '', reverse=True)

def parse_feed(data, source):
    if len(data) > MAX_BYTES:
        raise NewsError('Feed response exceeded the size limit.')
    try:
        root = ElementTree.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except Exception:
        raise NewsError('Source did not return a valid safe XML feed.') from None
    local = lambda el: el.tag.rsplit('}', 1)[-1]
    if local(root) not in ('rss', 'feed', 'RDF'):
        raise NewsError('Source did not return an RSS or Atom feed.')
    items = []
    for entry in [el for el in root.iter() if local(el) in ('item', 'entry')][:100]:
        fields = {}
        links = []
        for child in entry:
            key = local(child)
            if key == 'link':
                if child.get('rel', 'alternate') == 'alternate':
                    links.append(child.get('href') or child.text or '')
            else:
                fields[key] = ''.join(child.itertext())
        url = next((u for link in links if (u := approved_url(link.strip(), source['domains']))), None)
        if url:
            items.append(article(fields.get('title', ''), url, source['name'], source['category'],
                                 fields.get('pubDate') or fields.get('published') or fields.get('updated') or fields.get('date')))
    return deduplicate(items)

def fetch_bytes(url, headers=None, payload=None):
    # Callers supply only fixed feeds, fixed provider hosts, or operator-configured SearXNG.
    request = Request(url, data=payload, headers={'User-Agent': os.environ.get('STILL_NEWS_USER_AGENT', 'StillPersonalReader/1.0'),
                      'Accept-Encoding': 'identity', **(headers or {})})
    opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=8) as response:
            data = response.read(MAX_BYTES+1)
            if len(data) > MAX_BYTES:
                raise NewsError('Provider response exceeded the size limit.')
            return data
    except NewsError:
        raise
    except Exception:
        raise NewsError('Source unavailable or request rejected; retry later.') from None

def search_query(value):
    if not isinstance(value, str):
        raise NewsError('Enter a company or financial topic, up to 160 characters.')
    q = ' '.join(value.split())
    if not 2 <= len(q) <= 160 or not re.fullmatch(r"[\w .,'&%()+?/$-]+", q, flags=re.ASCII):
        raise NewsError('Use plain words, a company name or ticker; search operators are disabled.')
    return q

class NewsService:
    def __init__(self, transport=fetch_bytes, clock=time.monotonic, env=None):
        self.transport, self.clock = transport, clock
        # A provided mapping is read live, so settings saved in the app apply without a restart.
        self.env = dict(os.environ) if env is None else env
        self.feed_lock, self.search_lock = threading.Lock(), threading.Lock()
        self.feed_cache, self.search_cache = None, OrderedDict()
        self.last_attempt, self.last_search = float('-inf'), float('-inf')
        self.calls = 0

    def config(self):
        providers = []
        for p in CATALOG['providers']:
            configured = bool(self.env.get({'searxng':'SEARXNG_URL', 'brave':'BRAVE_SEARCH_API_KEY', 'tavily':'TAVILY_API_KEY'}[p['id']]))
            providers.append({**p, 'configured': configured})
        return {**CATALOG, 'providers': providers, 'cacheSeconds': TTL,
                'searchesRemainingThisRun': max(0, self.budget()-self.calls)}

    def budget(self):
        try:
            return max(0, min(1000, int(self.env.get('STILL_SEARCH_CALL_LIMIT', '50'))))
        except ValueError:
            return 0

    def feeds(self):
        with self.feed_lock:
            now = self.clock()
            if self.feed_cache and now-self.last_attempt < TTL:
                return self.feed_cache
            self.last_attempt = now
            previous = {s['id']:s for s in (self.feed_cache or {}).get('sources', [])}
            def one(source):
                try:
                    items = parse_feed(self.transport(source['url']), source)
                    return {'id':source['id'], 'name':source['name'], 'status':'ok', 'items':items,
                            'fetchedAt':utc_now(), '_success':now}
                except Exception:
                    old = previous.get(source['id'])
                    if old and now-old.get('_success', float('-inf')) < STALE_LIMIT:
                        return {**old, 'status':'stale'}
                    return {'id':source['id'], 'name':source['name'], 'status':'unavailable',
                            'items':[], 'fetchedAt':None}
            with ThreadPoolExecutor(max_workers=3) as pool:
                sources = list(pool.map(one, CATALOG['feeds']))
            self.feed_cache = {'items':deduplicate([i for s in sources for i in s['items']])[:150],
                               'sources':sources, 'checkedAt':utc_now()}
            return self.feed_cache

    def search(self, query, provider, period):
        q = search_query(query)
        if provider not in ('brave', 'searxng', 'tavily') or period not in ('day','week','month'):
            raise NewsError('Choose a supported search provider and date range.')
        key = (provider, period, q.casefold())
        with self.search_lock:
            now = self.clock()
            if key in self.search_cache and now-self.search_cache[key][0] < TTL:
                return {**self.search_cache[key][1], 'cached':True}
            settings = self.config()
            if not next(p['configured'] for p in settings['providers'] if p['id'] == provider):
                raise NewsError('This search provider is not configured on the server.')
            if self.calls >= self.budget():
                raise NewsError('Search allowance for this server run reached. Change the server limit to continue.')
            if now-self.last_search < 2:
                raise NewsError('Please wait two seconds before another search.')
            # Never auto-fallback to a paid provider; count attempted calls conservatively.
            self.calls += 1
            self.last_search = now
            domains = CATALOG['searchDomains']
            # Keep the query within provider length limits; the URL allowlist below is authoritative.
            scoped = f"({q}) (earnings OR stock OR markets OR economy OR investing)"
            if provider == 'brave':
                url = 'https://api.search.brave.com/res/v1/news/search?' + urlencode({
                    'q':scoped, 'count':20, 'freshness':{'day':'pd','week':'pw','month':'pm'}[period], 'search_lang':'en'})
                raw = self.transport(url, headers={'X-Subscription-Token':self.env['BRAVE_SEARCH_API_KEY'], 'Accept':'application/json'})
            elif provider == 'tavily':
                body = json.dumps({'query':scoped, 'topic':'news', 'search_depth':'basic',
                    'max_results':20, 'time_range':{'day':'day','week':'week','month':'month'}[period],
                    'include_domains':domains, 'include_domains_mode':'restrict', 'include_published_date':True, 'include_answer':False, 'include_raw_content':False}).encode()
                raw = self.transport('https://api.tavily.com/search', payload=body,
                    headers={'Authorization':'Bearer '+self.env['TAVILY_API_KEY'], 'Content-Type':'application/json'})
            else:
                base = self.env['SEARXNG_URL'].rstrip('/')
                parsed = urlsplit(base)
                if (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost','127.0.0.1','::1'))) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise NewsError('Configure SearXNG with HTTPS, or HTTP on loopback only.')
                raw = self.transport(base+'/search', payload=urlencode({'q':scoped, 'categories':'news',
                    'format':'json', 'language':'en', 'time_range':{'day':'day','week':'month','month':'month'}[period]}).encode(),
                    headers={'Content-Type':'application/x-www-form-urlencoded'})
            try:
                parsed = json.loads(raw)
                rows = parsed['results']
                if not isinstance(rows, list):
                    raise ValueError()
            except Exception:
                raise NewsError('Search provider returned an invalid response.') from None
            items = []
            now_utc = datetime.now(timezone.utc)
            max_days = {'day':1,'week':7,'month':31}[period]
            for row in rows[:100]:
                if not isinstance(row, dict):
                    continue
                url = approved_url(row.get('url'), domains)
                if not url:
                    continue
                published = row.get('page_age') or row.get('publishedDate') or row.get('published_date')
                item = article(row.get('title'), url, urlsplit(url).hostname, 'Search result', published)
                # Some engines ignore time_range; enforce known dates locally. Missing stays explicit.
                if item['publishedAt']:
                    delta = (now_utc-datetime.fromisoformat(item['publishedAt'].replace('Z','+00:00'))).total_seconds()
                    if delta > max_days*86400 or delta < -86400:
                        continue
                items.append(item)
            result = {'items':deduplicate(items)[:20], 'provider':provider, 'retrievedAt':utc_now(),
                      'cached':False, 'query':q, 'period':period,
                      'searchesRemainingThisRun':max(0,self.budget()-self.calls)}
            self.search_cache[key] = (now, result)
            if len(self.search_cache) > 64:
                self.search_cache.popitem(last=False)
            return result
