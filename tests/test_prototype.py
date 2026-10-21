"""Browser regression checks for Still's tabbed synthetic-data workspace."""
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
ARTIFACTS=ROOT/'artifacts'
BASE=os.environ.get('STILL_TEST_URL','http://127.0.0.1:4173')

def check_overflow(page,width):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Page overflow at {width}'
    assert page.evaluate('document.documentElement.scrollHeight <= innerHeight'), f'Outer-page scroll at {width}'

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    context=browser.new_context(viewport={'width':1440,'height':900},device_scale_factor=1)
    page=context.new_page()
    errors,external=[],[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('console',lambda m:errors.append(m.text) if m.type=='assert' else None)
    page.on('request',lambda r:external.append(r.url) if not r.url.startswith(BASE) and not r.url.startswith('data:') else None)
    page.goto(BASE,wait_until='networkidle')
    expect(page.locator('h1')).to_have_text('Portfolio')
    expect(page.locator('.metric.lead')).to_contain_text('$267,128.50')
    expect(page.locator('.summary-strip')).to_contain_text('+$38,982.60')
    expect(page.locator('.summary-strip')).to_contain_text('+$1,598.80')
    expect(page.locator('#main-holdings tbody tr')).to_have_count(8)
    expect(page.locator('dialog')).to_have_count(0)
    assert page.evaluate("document.fonts.check('13px \"Public Sans\"')")

    # Core regression: selecting stocks uses the whole unblurred workspace.
    page.get_by_role('button',name='Open Microsoft in a tab',exact=True).first.click()
    expect(page.locator('h1')).to_have_text('Microsoft')
    expect(page.get_by_role('tab',name='MSFT',exact=True)).to_have_attribute('aria-selected','true')
    expect(page.locator('#workspace-panel')).to_be_visible()
    assert page.locator('#workspace-panel').bounding_box()['width']>1000
    assert page.evaluate("getComputedStyle(document.querySelector('.workspace-grid')).filter")=='none'
    page.get_by_role('tab',name='Position',exact=True).click()
    expect(page.locator('#canvas-content')).to_contain_text('$437.50')
    expect(page.locator('#canvas-content')).to_contain_text('+$6,710.40')
    expect(page.locator('#canvas-content')).to_contain_text('2026-01-06')
    page.get_by_role('button',name='Open NVIDIA in a tab',exact=True).first.click()
    expect(page.locator('h1')).to_have_text('NVIDIA')
    expect(page.get_by_role('tab',name='NVDA',exact=True)).to_have_count(1)
    page.get_by_role('tab',name='MSFT',exact=True).click()
    expect(page.get_by_role('tab',name='Position',exact=True)).to_have_attribute('aria-selected','true')
    page.get_by_role('tab',name='Overview',exact=True).click()
    chart_before=page.locator('#main-chart svg path[stroke]').first.get_attribute('d')
    page.get_by_role('button',name='1M',exact=True).click()
    assert page.locator('#main-chart svg path[stroke]').first.get_attribute('d')!=chart_before
    page.get_by_role('button',name='YTD',exact=True).click()
    page.screenshot(path=ARTIFACTS/'redesign-stock.png')
    page.locator('#workspace-panel').evaluate('(el)=>el.scrollTop=500')

    # Discover controls remain visible even when coming from scrolled content.
    page.get_by_role('tab',name='Discover',exact=True).click()
    expect(page.locator('#discover-search')).to_be_in_viewport()
    expect(page.locator('#instrument-search')).to_be_in_viewport()
    page.locator('#workspace-panel').evaluate('(el)=>el.scrollTop=500')
    expect(page.locator('#instrument-search')).to_be_in_viewport()
    page.locator('#instrument-search').fill('Microsoft')
    expect(page.locator('.instrument-row')).to_have_count(1)
    expect(page.locator('#main-discover tbody tr')).to_have_count(1)
    expect(page.locator('#discover-search')).to_have_value('Microsoft')
    page.locator('#instrument-search').fill('no-such-company')
    expect(page.locator('#main-discover')).to_contain_text('No companies match')
    page.locator('#instrument-browser [data-clear]').click()
    page.locator('#discover-sector').select_option('Semiconductors')
    expect(page.locator('#main-discover tbody tr')).to_have_count(2)
    page.locator('#main-discover [data-watch="TSM"]').click()
    expect(page.locator('#main-discover [data-watch="TSM"]')).to_have_attribute('aria-pressed','true')
    page.reload(wait_until='networkidle')
    expect(page.get_by_role('tab',name='MSFT',exact=True)).to_have_count(1)
    expect(page.locator('#main-discover [data-watch="TSM"]')).to_have_attribute('aria-pressed','true')
    page.locator('#canvas-content [data-list="watchlist"]').click()
    expect(page.locator('#main-discover tbody tr')).to_have_count(4)
    page.locator('#canvas-content [data-list="holdings"]').click()
    page.locator('#main-gainers').click()
    expect(page.locator('#main-discover tbody tr')).to_have_count(6)
    page.locator('#main-gainers').click()
    page.locator('[data-sort="price"]').click()
    expect(page.locator('#main-discover tbody tr').first).to_have_attribute('data-open','NVDA')
    page.locator('[data-sort="price"]').click()
    expect(page.locator('#main-discover tbody tr').first).to_have_attribute('data-open','COST')
    page.locator('#workspace-panel').evaluate('(el)=>el.scrollTop=0')
    page.screenshot(path=ARTIFACTS/'redesign-discover.png')

    # Global search is always a visible input, not a hidden modal.
    page.keyboard.press('Control+k')
    expect(page.locator('#global-search')).to_be_focused()
    page.locator('#global-search').fill('alphabet')
    page.keyboard.press('Enter')
    expect(page.locator('h1')).to_have_text('Alphabet')
    expect(page.locator('.breadcrumb')).to_contain_text('Discover')
    page.go_back()
    expect(page.locator('h1')).to_have_text('Discover')
    page.go_forward()
    expect(page.locator('h1')).to_have_text('Alphabet')
    page.get_by_role('button',name='Close GOOGL tab',exact=True).click()
    expect(page.get_by_role('tab',name='GOOGL',exact=True)).to_have_count(0)

    # In-page research, adjustable scenarios, and honest unsupported questions.
    page.get_by_role('tab',name='Research',exact=True).first.click()
    expect(page.locator('h1')).to_have_text('Research')
    expect(page.locator('#research-study')).to_contain_text('63.71%')
    page.screenshot(path=ARTIFACTS/'redesign-research.png')
    page.get_by_role('tab',name='Scenarios',exact=True).click()
    expect(page.locator('#scenario-result')).to_contain_text('−$12,193.92')
    expect(page.locator('#scenario-result')).to_contain_text('$254,934.58')
    page.locator('#shock-input').fill('30')
    expect(page.locator('#shock-slider')).to_have_value('30')
    expect(page.locator('#scenario-result')).to_contain_text('−$18,290.88')
    page.locator('#shock-input').fill('0')
    expect(page.locator('#scenario-result .answer-number')).to_have_text('$0.00')
    expect(page.locator('#scenario-result .answer-number')).not_to_have_class('negative')
    page.locator('#shock-input').fill('20')
    page.locator('.evidence summary').click()
    expect(page.locator('.evidence')).to_contain_text('$60,969.60')
    page.screenshot(path=ARTIFACTS/'redesign-scenario.png')
    page.get_by_role('tab',name='Performance',exact=True).click()
    expect(page.locator('#research-study')).to_contain_text('+42.24%')
    page.locator('#research-question').fill('<img src=x onerror=alert(1)>')
    page.get_by_role('button',name='Run demo research',exact=True).click()
    expect(page.locator('#research-study')).to_contain_text('That question needs more data')
    expect(page.locator('#research-study img')).to_have_count(0)
    page.locator('#quick-question-input').fill('semiconductor shock')
    page.get_by_role('button',name='Open research for your question',exact=True).click()
    expect(page.get_by_role('tab',name='Scenarios',exact=True)).to_have_attribute('aria-selected','true')
    expect(page.locator('dialog')).to_have_count(0)

    # Resizable master/detail split, including keyboard and persistence.
    separator=page.get_by_role('separator',name='Resize instrument list')
    separator.focus()
    page.keyboard.press('Home')
    expect(separator).to_have_attribute('aria-valuenow','240')
    page.keyboard.press('ArrowRight')
    expect(separator).to_have_attribute('aria-valuenow','256')
    box=separator.bounding_box()
    page.mouse.move(box['x']+4,box['y']+100)
    page.mouse.down()
    page.mouse.move(416,box['y']+100,steps=5)
    page.mouse.up()
    expect(separator).to_have_attribute('aria-valuenow','360')
    page.reload(wait_until='networkidle')
    expect(separator).to_have_attribute('aria-valuenow','360')
    page.locator('#toggle-list').click()
    expect(page.locator('#instrument-browser')).not_to_be_visible()
    assert page.locator('#workspace-panel').bounding_box()['width']>1300
    page.locator('#toggle-list').click()
    separator.focus()
    page.keyboard.press('Home')
    for _ in range(4):page.keyboard.press('ArrowRight')
    page.locator('#global-search').focus()
    page.keyboard.press('Escape')

    # Roving keyboard tabs and all desktop/mobile primary paths.
    page.get_by_role('tab',name='Portfolio',exact=True).focus()
    page.keyboard.press('ArrowRight')
    expect(page.get_by_role('tab',name='Discover',exact=True)).to_have_attribute('aria-selected','true')
    page.get_by_role('tab',name='Portfolio',exact=True).click()
    page.screenshot(path=ARTIFACTS/'redesign-portfolio.png')
    for width,height in [(1440,900),(1024,900),(768,1024),(390,844),(320,740)]:
        page.set_viewport_size({'width':width,'height':height})
        page.wait_for_timeout(150)
        check_overflow(page,width)
        page.get_by_role('tab',name='Discover',exact=True).click()
        search=page.locator('#discover-search' if width<701 else '#instrument-search')
        expect(search).to_be_in_viewport()
        search.fill('Microsoft')
        if width<701:
            expect(page.locator('#main-discover tbody tr')).to_have_count(1)
            page.locator('#main-discover .asset-identity').first.click()
        else:
            expect(page.locator('.instrument-row')).to_have_count(1)
            page.locator('.instrument-row').first.click()
        expect(page.locator('h1')).to_have_text('Microsoft')
        check_overflow(page,width)
        if width<701:
            expect(page.locator('#instrument-browser')).not_to_be_visible()
            assert page.locator('#workspace-panel').bounding_box()['width']==width
        page.get_by_role('tab',name='Position',exact=True).click()
        expect(page.locator('#canvas-content')).to_contain_text('$437.50')
        if width==390:page.screenshot(path=ARTIFACTS/'redesign-mobile-stock.png')
        page.get_by_role('button',name='Research',exact=True).first.click()
        page.get_by_role('tab',name='Scenarios',exact=True).click()
        expect(page.locator('#shock-input')).to_be_in_viewport()
        page.locator('#shock-input').fill('10')
        expect(page.locator('#scenario-result')).to_contain_text('−$6,096.96')
        if width==390:page.screenshot(path=ARTIFACTS/'redesign-mobile-research.png')
        page.get_by_role('button',name='Discover',exact=True).first.click()
        page.locator('#discover-search' if width<701 else '#instrument-search').fill('')
        if width==390:page.screenshot(path=ARTIFACTS/'redesign-mobile-discover.png')
        page.get_by_role('button',name='Portfolio',exact=True).first.click()
        check_overflow(page,width)
        if width==390:page.screenshot(path=ARTIFACTS/'redesign-mobile.png')

    # Cache-local filtering timings exclude network and browser paint.
    page.set_viewport_size({'width':1440,'height':900})
    timings=page.evaluate('''()=>{const el=document.querySelector('#instrument-search'),times=[];for(let i=0;i<50;i++){const t=performance.now();el.value=i%2?'':'NVDA';el.dispatchEvent(new Event('input',{bubbles:true}));times.push(performance.now()-t)}times.sort((a,b)=>a-b);return{p50:times[25],p95:times[47],samples:50}}''')
    assert not errors,errors
    assert not external,external

    # Browser policy blocks file://. Verify self-contained output over allowed HTTP.
    server=subprocess.Popen(['python','-m','http.server','4174','--bind','127.0.0.1','--directory',str(ARTIFACTS)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(30):
            try:urllib.request.urlopen('http://127.0.0.1:4174/still-prototype.html',timeout=1).close();break
            except OSError:time.sleep(.1)
        packaged=context.new_page()
        packaged.goto('http://127.0.0.1:4174/still-prototype.html',wait_until='networkidle')
        expect(packaged.locator('h1')).to_have_text('Portfolio')
        packaged.get_by_role('button',name='Open Microsoft in a tab',exact=True).first.click()
        expect(packaged.locator('h1')).to_have_text('Microsoft')
        assert packaged.evaluate("document.fonts.check('13px \"Public Sans\"')")
    finally:server.terminate();server.wait(timeout=5)
    report={'status':'passed','viewports':[1440,1024,768,390,320],'consoleErrors':errors,'externalRequests':external,'filterHandlerMs':timings,'coverage':['full-width instrument tabs','no stock or research dialogs','persistent search after scroll','discovery filter synchronization','watchlist persistence','stock tab persistence and close','history back/forward','research subtabs','adjustable scenarios and zero','source calculations','unsafe unsupported input','pointer and keyboard split resizing','collapse and restore','keyboard tab navigation','phone stock and research flows','self-contained packaged output'],'limits':'Synthetic eight-position fixture. Handler timings exclude paint and are not production benchmarks. No IBKR integration, app auth or live AI. Hosted access is separate from application authentication.'}
    (ARTIFACTS/'verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    browser.close()
