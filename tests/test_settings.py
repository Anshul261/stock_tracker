"""Check that connection settings never imply live access or collect credentials."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':900})
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto('http://127.0.0.1:4173/#settings/ibkr')
    expect(page.locator('h1')).to_have_text('Settings')
    expect(page.locator('.broker-status')).to_have_text('Not connected')
    expect(page.locator('.connection-facts')).to_contain_text('Never')
    expect(page.locator('#settings-content input')).to_have_count(0)
    page.get_by_text('Disable Flex access at IBKR',exact=True).click()
    expect(page.get_by_role('link',name='Open IBKR to disable Flex')).to_be_visible()
    expect(page.locator('#settings-content')).to_contain_text('Reports already downloaded remain')
    assert page.get_by_role('link',name='Open IBKR to disable Flex').get_attribute('href')=='https://www.interactivebrokers.com/sso/Login'
    page.get_by_text('Prepare Flex reporting in IBKR',exact=True).click()
    expect(page.get_by_role('link',name='Official token setup')).to_be_visible()
    page.screenshot(path=ROOT/'artifacts/settings-desktop.png')
    page.get_by_role('tab',name='Data & privacy',exact=True).click()
    expect(page).to_have_url('http://127.0.0.1:4173/#settings/privacy')
    expect(page.get_by_role('button',name='Reset workspace preferences')).to_be_visible()
    page.reload()
    expect(page.get_by_role('tab',name='Data & privacy',exact=True)).to_have_attribute('aria-selected','true')
    page.get_by_role('tab',name='Data & privacy',exact=True).focus()
    page.keyboard.press('ArrowLeft')
    expect(page.get_by_role('tab',name='IBKR connection',exact=True)).to_be_focused()
    expect(page.locator('.broker-status')).to_have_text('Not connected')
    page.go_back()
    expect(page.get_by_role('tab',name='Data & privacy',exact=True)).to_have_attribute('aria-selected','true')
    page.locator('#global-search').fill('settings')
    page.keyboard.press('Enter')
    expect(page.locator('h1')).to_have_text('Settings')
    for width in [1440,768,390,320]:
        page.set_viewport_size({'width':width,'height':900})
        page.goto('http://127.0.0.1:4173/#settings/ibkr')
        page.get_by_text('Disable Flex access at IBKR',exact=True).click()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
        assert page.locator('#settings-content').evaluate('(el)=>el.scrollWidth <= el.clientWidth'),width
        if width==390:page.screenshot(path=ROOT/'artifacts/settings-mobile.png')
    assert not errors,errors
    browser.close()
    print('Settings checks passed: truthful status, no token collection, official links, history, keyboard, 4 widths.')
