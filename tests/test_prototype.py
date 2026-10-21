"""Functional tests against the locally served synthetic prototype."""
import json
import os
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'artifacts'
BASE = os.environ.get('STILL_TEST_URL', 'http://127.0.0.1:4173')

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    context = browser.new_context(viewport={'width':1440, 'height':1100}, device_scale_factor=1)
    page = context.new_page()
    errors, external = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: external.append(request.url) if not request.url.startswith(BASE) and not request.url.startswith('data:') else None)
    page.goto(BASE, wait_until='networkidle')
    expect(page.locator('#balance')).to_have_text('$267,128.50')
    expect(page.locator('#stats-strip')).to_contain_text('+$38,982.60')
    expect(page.locator('#stats-strip')).to_contain_text('+$1,598.80')
    expect(page.locator('.asset-row')).to_have_count(8)
    page.screenshot(path=ARTIFACTS/'still-desktop.png', full_page=True)

    original = page.locator('#portfolio-chart .chart-line').get_attribute('points')
    page.get_by_role('button', name='1M', exact=True).click()
    assert page.locator('#portfolio-chart .chart-line').get_attribute('points') != original
    expect(page.locator('#performance-change')).to_contain_text('past month')
    page.get_by_role('button', name='YTD', exact=True).click()
    page.locator('#portfolio-chart').hover()
    expect(page.locator('#portfolio-chart .chart-tooltip')).to_be_visible()

    page.locator('#holding-search').fill('Microsoft')
    expect(page.locator('.asset-row')).to_have_count(1)
    page.locator('#holding-search').fill('missing-symbol')
    expect(page.locator('#holdings-body')).to_contain_text('No matching holdings')
    page.locator('#holding-search').fill('')
    page.locator('#holdings-filter').click()
    expect(page.locator('.asset-row')).to_have_count(6)
    page.locator('#holdings-filter').click()
    page.locator('[data-sort="value"]').click()
    expect(page.locator('.asset-row').first).to_have_attribute('data-symbol','TSM')
    page.locator('[data-sort="value"]').click()
    expect(page.locator('.asset-row').first).to_have_attribute('data-symbol','NVDA')

    page.get_by_role('button', name='Explore NVIDIA', exact=True).click()
    expect(page.locator('#detail-dialog')).to_be_visible()
    expect(page.locator('#detail-content')).to_contain_text('$128.40')
    expect(page.locator('#detail-content')).to_contain_text('+$13,017.60')
    page.locator('[data-detail-period="1M"]').click()
    expect(page.locator('[data-detail-period="1M"]')).to_have_attribute('aria-pressed','true')
    page.screenshot(path=ARTIFACTS/'still-holding.png', full_page=True)
    page.keyboard.press('Escape')
    expect(page.locator('#detail-dialog')).not_to_be_visible()

    page.keyboard.press('Control+k')
    expect(page.locator('#search-dialog')).to_be_visible()
    page.locator('#command-input').fill('alphabet')
    page.keyboard.press('Enter')
    expect(page.locator('#detail-name')).to_have_text('Alphabet')
    page.keyboard.press('Escape')
    page.keyboard.press('Control+k')
    page.locator('#command-input').fill('')
    page.keyboard.press('ArrowDown')
    page.keyboard.press('Enter')
    expect(page.locator('#discover-view')).to_be_visible()

    page.locator('[data-filter="Semiconductors"]').click()
    expect(page.locator('.company-card')).to_have_count(2)
    page.locator('#discover-search').fill('TSM')
    expect(page.locator('.company-card')).to_have_count(1)
    page.locator('[data-watch="TSM"]').click()
    expect(page.locator('[data-watch="TSM"]')).to_have_attribute('aria-pressed','true')
    page.reload(wait_until='networkidle')
    expect(page.locator('.watch-item[data-open="TSM"]')).to_be_visible()
    page.locator('[data-filter="watchlist"]').click()
    expect(page.locator('.company-card')).to_have_count(4)
    page.locator('[data-filter="all"]').click()
    page.locator('#discover-search').fill('no such company')
    expect(page.locator('.no-results')).to_be_visible()
    page.locator('#discover-search').fill('')
    page.screenshot(path=ARTIFACTS/'still-discover.png', full_page=True)

    page.locator('[data-view="portfolio"]').click()
    page.locator('#question-semiconductor').click()
    expect(page.locator('#assistant-dialog')).to_be_visible()
    expect(page.locator('#assistant-content')).to_contain_text('−$12,193.92')
    expect(page.locator('#assistant-content')).to_contain_text('$254,934.58')
    expect(page.locator('#assistant-content')).to_contain_text('−4.56%')
    page.locator('.evidence summary').click()
    expect(page.locator('.evidence')).to_contain_text('$60,969.60')
    page.screenshot(path=ARTIFACTS/'still-scenario.png', full_page=True)
    page.locator('#assistant-input').fill('Which holding has grown the most?')
    page.locator('.send-button').click()
    expect(page.locator('#assistant-content')).to_contain_text('+42.24%')
    page.locator('#assistant-input').fill('<img src=x onerror=alert(1)>')
    page.locator('.send-button').click()
    expect(page.locator('#assistant-content')).to_contain_text('cannot retrieve news')
    expect(page.locator('#assistant-content img')).to_have_count(0)
    page.keyboard.press('Escape')

    page.locator('#privacy-button').click()
    expect(page.locator('#info-dialog')).to_be_visible()
    page.get_by_role('button',name='Got it').click()
    page.keyboard.press('/')
    expect(page.locator('#holding-search')).to_be_focused()
    page.locator('#holding-search').blur()

    for width,height in [(1440,1100),(1024,900),(768,1024),(390,844),(320,740)]:
        page.set_viewport_size({'width':width,'height':height})
        page.wait_for_timeout(150)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Horizontal overflow at {width}'
        expect(page.get_by_role('button',name='Explore NVIDIA',exact=True)).to_be_visible()
        if width==390:
            page.screenshot(path=ARTIFACTS/'still-mobile.png',full_page=True)
            page.get_by_role('button',name='Explore NVIDIA',exact=True).click()
            expect(page.locator('#detail-dialog')).to_be_visible()
            assert page.locator('#detail-dialog').bounding_box()['width']<=390
            page.keyboard.press('Escape')

    # Measure synchronous cache-local handlers, not model/network latency.
    page.set_viewport_size({'width':1440,'height':1100})
    timings=page.evaluate('''() => {
      const input = document.querySelector('#holding-search'), times=[];
      for(let i=0;i<50;i++) { const start=performance.now(); input.value=i%2?'':'NVDA'; input.dispatchEvent(new Event('input')); times.push(performance.now()-start); }
      times.sort((a,b)=>a-b); return {handlerP50:times[25],handlerP95:times[47],samples:times.length};
    }''')
    page.locator('#holding-search').fill('')
    assert not external, f'Unexpected external requests: {external}'
    assert not errors, errors

    # This environment blocks file:// navigation by browser policy. Verify the
    # same standalone artifact over loopback HTTP without weakening that policy.
    artifact_server=subprocess.Popen(['python','-m','http.server','4174','--bind','127.0.0.1','--directory',str(ARTIFACTS)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        import time
        import urllib.request
        for _ in range(30):
            try:
                urllib.request.urlopen('http://127.0.0.1:4174/still-prototype.html',timeout=1).close()
                break
            except OSError:
                time.sleep(.1)
        offline=context.new_page()
        offline.goto('http://127.0.0.1:4174/still-prototype.html',wait_until='load')
        expect(offline.locator('.asset-row')).to_have_count(8)
        offline.get_by_role('button',name='Explore NVIDIA',exact=True).click()
        expect(offline.locator('#detail-dialog')).to_be_visible()
    finally:
        artifact_server.terminate()
        artifact_server.wait(timeout=5)
    report={'functionalChecks':'passed','responsiveWidths':[1440,1024,768,390,320],
            'consoleErrors':errors,'externalRequests':external,'localHandlerTimingMs':timings,
            'limits':'Synthetic eight-holding fixture. Handler timings exclude browser paint and are not production performance guarantees. Direct file:// navigation is blocked by environment browser policy; standalone HTML was tested over loopback HTTP. Application authentication and live integrations are not implemented.'}
    (ARTIFACTS/'verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    browser.close()
