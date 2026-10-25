"""Run Still independently: python serve.py (local access only)."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import argparse
import getpass
import os
import json
import mimetypes

from news.service import NewsService, NewsError

ROOT = Path(__file__).resolve().parent / 'prototype'
ASSETS = {'/': 'index.html', '/index.html':'index.html', **{'/'+p:p for p in (
    'style.css','data.js','app.js','news.js','news-sources.js','assets/charts.js','assets/public-sans.ttf')}}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # No queries, keys, account information or raw remote errors in logs.

    def permitted(self):
        host = self.headers.get('Host', '')
        port = self.server.server_port
        if host not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            self.reply(403, {'error':'Use the local Still address.'})
            return False
        origin = self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
            self.reply(403, {'error':'Cross-origin requests are not allowed.'})
            return False
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self.reply(403, {'error':'Cross-site requests are not allowed.'})
            return False
        return True

    def reply(self, status, data, content_type='application/json; charset=utf-8'):
        body = json.dumps(data).encode() if isinstance(data, dict) else data
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.permitted():
            return
        path = urlsplit(self.path).path
        if path == '/api/news/config':
            return self.reply(200,self.server.news.config())
        if path == '/api/news/feed':
            result = self.server.news.feeds()
            public = {**result, 'sources':[{k:v for k,v in s.items() if not k.startswith('_')} for s in result['sources']]}
            return self.reply(200,public)
        if path in ASSETS:
            file = ROOT / ASSETS[path]
            if file.is_file():
                return self.reply(200,file.read_bytes(),mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
        self.reply(404, {'error':'Not found.'})

    def do_POST(self):
        if not self.permitted():
            return
        if self.path != '/api/news/search':
            return self.reply(404, {'error':'Not found.'})
        if self.headers.get_content_type() != 'application/json':
            return self.reply(415, {'error':'Send a JSON request.'})
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 2048:
                return self.reply(413, {'error':'Request exceeds the size limit.'})
            data = json.loads(self.rfile.read(length))
            if not isinstance(data,dict) or set(data) != {'query','provider','period'}:
                raise ValueError()
        except (ValueError, UnicodeError):
            return self.reply(400, {'error':'Invalid search request.'})
        try:
            self.reply(200,self.server.news.search(data['query'],data['provider'],data['period']))
        except NewsError as error:
            self.reply(400, {'error':str(error)})
        except Exception:
            self.reply(502, {'error':'Search unavailable; retry later.'})

def create_server(port=4173, service=None):
    server = ThreadingHTTPServer(('127.0.0.1',port), Handler)
    server.news = service or NewsService()
    return server

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=4173)
    parser.add_argument('--search-provider', choices=('brave','tavily'), help='Prompt for its API key without echo; kept in memory for this run.')
    args = parser.parse_args()
    config = dict(os.environ)
    if args.search_provider:
        key = getpass.getpass(args.search_provider.title()+' API key (hidden): ')
        if not key.strip():
            parser.error('API key cannot be empty.')
        config[{'brave':'BRAVE_SEARCH_API_KEY','tavily':'TAVILY_API_KEY'}[args.search_provider]] = key.strip()
    with create_server(args.port, NewsService(env=config)) as server:
        print(f'Still: http://127.0.0.1:{server.server_port} (local access only)',flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
