"""News UI checks with explicitly synthetic API fixtures. No live network calls."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
CATALOG=json.loads((ROOT/'news/sources.json').read_text())
CONFIG={**CATALOG,'providers':[{**p,'configured':p['id']=='tavily'} for p in CATALOG['providers']]}
ITEM={'title':'TEST FIXTURE: monetary policy release','source':'Federal Reserve','category':'Monetary policy','url':'https://www.federalreserve.gov/newsevents/test-fixture.htm','publishedAt':'2026-10-23T12:00:00Z'}
FEED={'items':[ITEM], 'sources':[{'id':s['id'],'name':s['name'],'status':'ok','fetchedAt':'2026-10-25T10:00:00Z'} for s in CATALOG['feeds']], 'checkedAt':'2026-10-25T10:00:00Z'}
RESULT={'items':[{'title':'TEST FIXTURE: <img src=x onerror=alert(1)> earnings','source':'www.reuters.com','category':'Search result','url':'https://www.reuters.com/markets/test-fixture','publishedAt':None}, {'title':'Malicious URL','source':'bad','category':'bad','url':'javascript:alert(1)'}], 'query':'Microsoft MSFT', 'provider':'tavily', 'cached':False, 'retrievedAt':'2026-10-25T10:00:00Z'}
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':900})
    errors=[];requests=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def api(route):
        path=route.request.url.split('/api/news/')[1]
        if path=='search':
            requests.append(route.request.post_data_json)
            route.fulfill(json=RESULT)
        else:route.fulfill(json=CONFIG if path=='config' else FEED)
    page.route('**/api/news/**',api)
    page.goto('http://127.0.0.1:4173/#news/feed')
    expect(page.locator('h1')).to_have_text('News')
    expect(page.get_by_role('link',name=ITEM['title'])).to_be_visible()
    page.locator('#news-source').select_option('SEC')
    expect(page.get_by_role('heading',name='No releases in this view')).to_be_visible()
    page.locator('#news-source').select_option('all')
    page.get_by_role('tab',name='Search',exact=True).click()
    expect(page.locator('#news-provider')).to_have_value('tavily')
    page.locator('#news-query').fill('Microsoft MSFT')
    expect(page.locator('#news-search-links a').first).to_have_attribute('href',__import__('re').compile('.*Microsoft.*'))
    page.locator('#finance-search').get_by_role('button',name='Search',exact=True).click()
    expect(page.get_by_role('heading',name='Results for “Microsoft MSFT”')).to_be_visible()
    expect(page.locator('.news-list img')).to_have_count(0)
    expect(page.get_by_text('Publication date unavailable',exact=True)).to_be_visible()
    expect(page.get_by_text('Malicious URL',exact=True)).to_have_count(0)
    assert requests==[{'query':'Microsoft MSFT','provider':'tavily','period':'week'}]
    expect(page.locator('dialog')).to_have_count(0)
    page.get_by_role('tab',name='Sources',exact=True).click()
    page.screenshot(path=ROOT/'artifacts/news-sources-desktop.png')
    page.reload()
    expect(page.get_by_role('tab',name='Sources',exact=True)).to_have_attribute('aria-selected','true')
    page.get_by_role('tab',name='Sources',exact=True).focus();page.keyboard.press('ArrowLeft')
    expect(page.get_by_role('tab',name='Search',exact=True)).to_be_focused()
    page.go_back();expect(page.get_by_role('tab',name='Sources',exact=True)).to_have_attribute('aria-selected','true')
    page.goto('http://127.0.0.1:4173/#stock/MSFT/news')
    expect(page.locator('h1')).to_have_text('Microsoft')
    expect(page.locator('#news-query')).to_have_value('Microsoft MSFT')
    assert len(requests)==1,'Selecting stock news must not automatically search externally'
    for width in [1440,1024,768,390,320]:
        page.set_viewport_size({'width':width,'height':900})
        page.goto('http://127.0.0.1:4173/#news/search')
        expect(page.locator('#news-query')).to_be_visible()
        expect(page.locator('#news-provider')).to_have_value('tavily')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
        assert page.locator('#news-content').evaluate('(el)=>el.scrollWidth<=el.clientWidth'),width
        if width==390:page.screenshot(path=ROOT/'artifacts/news-search-mobile.png')
    # Real static-host response shape: no API, no fabricated headlines.
    page.route('**/api/news/**',lambda route:route.fulfill(status=404,content_type='text/html',body='Not found'))
    page.goto('http://127.0.0.1:4173/#news/feed')
    expect(page.get_by_role('heading',name='Live feeds need the Still server')).to_be_visible()
    expect(page.locator('.news-list')).to_have_count(0)
    assert not errors,errors
    browser.close()
    print('News UI passed: fixtures, source filter, privacy, sanitization, history, keyboard, mobile, static fallback.')
