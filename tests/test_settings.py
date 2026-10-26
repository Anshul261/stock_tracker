"""Settings in the static preview: no server means no credential forms and no false connection claims.
Run against the static preview: uv run python -m http.server 4173 --bind 127.0.0.1 --directory prototype
The full app's settings flows are covered by tests/test_app.py (API) and manual checks in a browser."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
BASE=os.environ.get('STILL_TEST_URL','http://127.0.0.1:4173')
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('STILL_CHROMIUM','/usr/bin/chromium'),args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':900})
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(BASE+'/#settings/ibkr')
    expect(page.locator('h1')).to_have_text('Settings')
    expect(page.locator('#settings-content')).to_contain_text('Needs the Still app')
    expect(page.locator('#settings-content input')).to_have_count(0)
    for tab in ('News search','Security'):
        page.get_by_role('tab',name=tab,exact=True).click()
        expect(page.locator('#settings-content')).to_contain_text('Needs the Still app')
    page.get_by_role('tab',name='Data & privacy',exact=True).click()
    expect(page).to_have_url(BASE+'/#settings/privacy')
    expect(page.get_by_role('button',name='Reset workspace preferences')).to_be_visible()
    expect(page.locator('#settings-content')).to_contain_text('can only show demo data')
    page.reload()
    expect(page.get_by_role('tab',name='Data & privacy',exact=True)).to_have_attribute('aria-selected','true')
    page.get_by_role('tab',name='Data & privacy',exact=True).focus()
    page.keyboard.press('ArrowLeft')
    expect(page.get_by_role('tab',name='Security',exact=True)).to_be_focused()
    page.locator('#global-search').fill('settings')
    page.keyboard.press('Enter')
    expect(page.locator('h1')).to_have_text('Settings')
    for width in [1440,768,390,320]:
        page.set_viewport_size({'width':width,'height':900})
        page.goto(BASE+'/#settings/privacy')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
        assert page.locator('#settings-content').evaluate('(el)=>el.scrollWidth <= el.clientWidth'),width
        if width==390:page.screenshot(path=ROOT/'artifacts/settings-mobile.png')
    assert not errors,errors
    browser.close()
    print('Settings checks passed: static preview offers no credential forms and states it needs the app; history, keyboard, 4 widths.')
