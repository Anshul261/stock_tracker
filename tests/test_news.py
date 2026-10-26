"""Offline contracts: fixtures and fake transports only, no publisher or search calls."""
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from news.service import (CATALOG, MAX_BYTES, NewsService, NewsError, NoRedirect,
                          approved_url, parse_feed, timestamp, fetch_bytes)
from tempfile import TemporaryDirectory
from still.server import App, create_server

FEED=b'''<rss><channel><item><title>Policy &amp; rates</title><link>https://www.federalreserve.gov/releases/policy.htm?utm_source=rss</link><pubDate>Fri, 23 Oct 2026 12:00:00 GMT</pubDate></item><item><title>Duplicate</title><link>https://www.federalreserve.gov/releases/policy.htm</link></item><item><title>Bad link</title><link>https://federalreserve.gov.evil.test/a</link></item><item><title>Unsafe</title><link>javascript:alert(1)</link></item></channel></rss>'''
ATOM=b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>&lt;img src=x onerror=alert(1)&gt;Economic release</title><link href="https://www.bls.gov/news.release/x.htm"/><published>2026-10-23T12:00:00Z</published></entry></feed>'''
class Clock:
    value=1000
    def __call__(self):return self.value

class ServiceTests(unittest.TestCase):
    def test_feed_date_dedup_and_host_filter(self):
        rows=parse_feed(FEED,CATALOG['feeds'][0])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['title'],'Policy & rates')
        self.assertEqual(rows[0]['publishedAt'],'2026-10-23T12:00:00Z')
    def test_atom_and_html_plaintext(self):
        rows=parse_feed(ATOM,CATALOG['feeds'][2])
        self.assertEqual(rows[0]['title'],'Economic release')
    def test_invalid_dates_not_fabricated(self):
        for value in ('nonsense','2026-10-23',None,''):
            self.assertIsNone(timestamp(value))
    def test_xml_entities_dtd_html_and_oversize_rejected(self):
        for body in (b'<!DOCTYPE rss [<!ENTITY x "bad">]><rss/>',b'<html>no</html>',b'<rss',b'x'*(MAX_BYTES+1)):
            with self.assertRaises(NewsError):parse_feed(body,CATALOG['feeds'][0])
    def test_bad_urls_rejected(self):
        for value in ('http://sec.gov/a','https://sec.gov.evil.test/a','https://sec.gov@evil.test/a','https://a@sec.gov/a','https://sec.gov:444/a','//sec.gov/a',{},None):
            self.assertIsNone(approved_url(value,['sec.gov']))
        self.assertTrue(approved_url('https://www.sec.gov/a',['sec.gov']))
    def test_config_does_not_disclose_credentials(self):
        s=NewsService(env={'BRAVE_SEARCH_API_KEY':'private-key','SEARXNG_URL':'https://secret.example'})
        out=json.dumps(s.config())
        self.assertNotIn('private-key',out)
        self.assertNotIn('secret.example',out)
    def test_cache_failures_stale_then_expiry(self):
        clock=Clock();calls=[];fail=[False]
        def fetch(url,**kwargs):
            calls.append(url)
            if fail[0]:raise RuntimeError('sensitive-body')
            return FEED
        service=NewsService(fetch,clock,env={})
        first=service.feeds()
        self.assertEqual(len(calls),3)
        service.feeds();self.assertEqual(len(calls),3)
        fail[0]=True;clock.value+=601
        stale=service.feeds()
        self.assertEqual(stale['sources'][0]['status'],'stale')
        self.assertEqual(stale['sources'][0]['fetchedAt'],first['sources'][0]['fetchedAt'])
        self.assertNotIn('sensitive-body',json.dumps(stale))
        clock.value+=21601
        expired=service.feeds()
        self.assertEqual(expired['items'],[])
        self.assertEqual(expired['sources'][0]['status'],'unavailable')
    def test_failed_feed_retry_is_paced(self):
        calls=[]
        def bad(url):calls.append(url);raise NewsError('bad')
        service=NewsService(bad,env={})
        service.feeds();service.feeds()
        self.assertEqual(len(calls),3)
    def test_concurrent_requests_share_feed_fetch(self):
        from concurrent.futures import ThreadPoolExecutor
        calls=[]
        service=NewsService(lambda url:(calls.append(url) or FEED),env={})
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:service.feeds(),range(4)))
        self.assertEqual(len(calls),3)
    def test_no_credentials_no_network(self):
        calls=[]
        service=NewsService(lambda *a,**k:calls.append(a),env={})
        for p in ('brave','searxng','tavily'):
            with self.assertRaises(NewsError):service.search('Nvidia earnings',p,'week')
        self.assertEqual(calls,[])
    def test_search_input_operators_rejected(self):
        service=NewsService(env={'BRAVE_SEARCH_API_KEY':'key'})
        for q in ('x','site:evil.test','!google NVDA','<script>', 'a'*161,{},None):
            with self.assertRaises(NewsError):service.search(q,'brave','week')
    def test_all_providers_scope_and_filter(self):
        for provider in ('brave','searxng','tavily'):
            calls=[]
            def transport(url,**kwargs):
                calls.append((url,kwargs))
                return json.dumps({'results':[{'title':'Allowed market report','url':'https://www.reuters.com/markets/example'}, {'title':'Excluded','url':'https://unknown.example/a'}, {'title':'Suffix attack','url':'https://reuters.com.evil.test/a'}, {'title':'Unsafe','url':'javascript:alert(1)'}]}).encode()
            service=NewsService(transport,env={'BRAVE_SEARCH_API_KEY':'private-brave','TAVILY_API_KEY':'private-tavily','SEARXNG_URL':'http://127.0.0.1:8888'})
            result=service.search('Nvidia earnings',provider,'week')
            self.assertEqual(len(result['items']),1)
            self.assertIsNone(result['items'][0]['publishedAt'])
            self.assertNotIn('private-',json.dumps(result))
            url, options=calls[0]
            query=parse_qs(urlsplit(url).query)['q'][0] if provider=='brave' else json.loads(options['payload'])['query'] if provider=='tavily' else parse_qs(options['payload'].decode())['q'][0]
            self.assertIn('earnings OR stock',query)
            self.assertLessEqual(len(query),400)
            if provider=='tavily':self.assertIn('sec.gov',json.loads(options['payload'])['include_domains'])
    def test_credential_headers_and_no_broker_fields(self):
        calls=[]
        service=NewsService(lambda url,**kw:(calls.append((url,kw)) or b'{"results":[]}'),env={'BRAVE_SEARCH_API_KEY':'private'})
        service.search('Nvidia','brave','day')
        url,options=calls[0]
        self.assertNotIn('private',url)
        self.assertEqual(options['headers']['X-Subscription-Token'],'private')
        self.assertEqual(set(parse_qs(urlsplit(url).query)),{'q','count','freshness','search_lang'})
    def test_search_cache_cooldown_and_budget(self):
        clock=Clock();calls=[]
        service=NewsService(lambda *a,**k:(calls.append(a) or b'{"results":[]}'),clock,env={'TAVILY_API_KEY':'key','STILL_SEARCH_CALL_LIMIT':'1'})
        service.search('Nvidia','tavily','week')
        self.assertTrue(service.search('nvidia','tavily','week')['cached'])
        clock.value+=3
        with self.assertRaises(NewsError):service.search('Microsoft','tavily','week')
        self.assertEqual(len(calls),1)
    def test_search_cooldown_counts_no_extra_requests(self):
        clock=Clock();calls=[]
        service=NewsService(lambda *a,**k:(calls.append(a) or b'{"results":[]}'),clock,env={'TAVILY_API_KEY':'key'})
        service.search('Nvidia','tavily','week')
        with self.assertRaises(NewsError):service.search('Microsoft','tavily','week')
        self.assertEqual(len(calls),1)
    def test_invalid_provider_json_no_remote_body(self):
        service=NewsService(lambda *a,**k:b'{"secret":"bad response"}',env={'TAVILY_API_KEY':'key'})
        with self.assertRaisesRegex(NewsError,'invalid response'):service.search('Nvidia','tavily','week')
    def test_old_search_dates_excluded(self):
        service=NewsService(lambda *a,**k:b'{"results":[{"title":"Old","url":"https://sec.gov/a","published_date":"2001-01-01T00:00:00Z"}]}',env={'TAVILY_API_KEY':'key'})
        self.assertEqual(service.search('Nvidia','tavily','day')['items'],[])
    def test_searxng_non_loopback_http_rejected(self):
        service=NewsService(env={'SEARXNG_URL':'http://insecure.example'})
        with self.assertRaisesRegex(NewsError,'HTTPS'):service.search('Nvidia','searxng','day')
    def test_transport_redacts_and_disallows_redirect(self):
        with patch('news.service.build_opener') as opener:
            opener.return_value.open.side_effect=Exception('key-in-sensitive-url')
            with self.assertRaises(NewsError) as error:fetch_bytes('https://example.test/')
            self.assertNotIn('key-in-sensitive-url',str(error.exception))
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://other.test'))

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=TemporaryDirectory()
        cls.server=create_server(0,App(Path(cls.folder.name),news=NewsService(lambda *a,**k:FEED,env={})))
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        # News routes need a signed-in owner, like every other data route.
        setup=urlopen(Request(cls.base+'/api/setup',data=b'{"passphrase":"synthetic test passphrase","mode":"demo"}',
                              headers={'Content-Type':'application/json','X-Still-Request':'1'}),timeout=10)
        cls.cookie=setup.headers['Set-Cookie'].split(';')[0]
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.server.app.store.close();cls.folder.cleanup()
    def status(self,path,headers=None,**kw):
        headers={'Cookie':self.cookie,'X-Still-Request':'1',**(headers or {})}
        try:return urlopen(Request(self.base+path,headers=headers,**kw),timeout=3)
        except HTTPError as e:return e
    def test_static_only_allowlist_and_headers(self):
        response=self.status('/')
        self.assertEqual(response.status,200)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertIn('frame-ancestors',response.headers['Content-Security-Policy'])
        for path in ('/private-data/report.xml','/.env','/.git/config','/ibkr/flex.py','/../README.md'):
            self.assertEqual(self.status(path).status,404)
    def test_dns_rebinding_and_cross_origin_rejected(self):
        self.assertEqual(self.status('/api/news/config',headers={'Host':'evil.example'}).status,403)
        self.assertEqual(self.status('/api/news/config',headers={'Origin':'https://evil.example'}).status,403)
        self.assertEqual(self.status('/api/news/config',headers={'Sec-Fetch-Site':'cross-site'}).status,403)
        self.assertEqual(self.status('/api/news/config',headers={'Cookie':''}).status,401)
    def test_search_shape_size_and_type(self):
        self.assertEqual(self.status('/api/news/search',data=b'{}').status,415)
        for payload in (b'[]',b'{"query":"x","holdings":"private"}',b'a'*2049):
            self.assertIn(self.status('/api/news/search',data=payload,headers={'Content-Type':'application/json'}).status,(400,413))
    def test_public_status_and_feed_envelope(self):
        data=json.load(self.status('/api/news/feed'))
        self.assertEqual(len(data['sources']),3)
        self.assertTrue(all('_success' not in s for s in data['sources']))
        config=json.load(self.status('/api/news/config'))
        self.assertTrue(all(not p['configured'] for p in config['providers']))

if __name__=='__main__':unittest.main()
