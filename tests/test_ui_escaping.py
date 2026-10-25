"""Broker-supplied names, symbols and sectors must render as text, never as markup.

Serves hostile values in place of data.js and checks that nothing executes or
injects elements. Run the HTTP server first, then: uv run python tests/test_ui_escaping.py
Set STILL_CHROMIUM to a Chromium/Chrome binary if it is not at /usr/bin/chromium.
"""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get('STILL_TEST_URL', 'http://127.0.0.1:4173')
NAME = '<img src=x onerror="window.__xss=(window.__xss||0)+1">NVIDIA'
SECTOR = '<b class="injected">Semis</b>'
EXCHANGE = '<svg onload="window.__xss=(window.__xss||0)+1"></svg>NASDAQ'
SYMBOL = 'MS"><i class="injected">FT'


def hostile_data():
    text = (ROOT / 'prototype/data.js').read_text()
    original = "symbol:'NVDA', name:'NVIDIA', legalName:'NVIDIA Corporation', sector:'Semiconductors', exchange:'NASDAQ'"
    assert original in text and "symbol:'MSFT'" in text
    return (text.replace(original, f"symbol:'NVDA', name:'{NAME}', legalName:'{NAME}', sector:'{SECTOR}', exchange:'{EXCHANGE}'")
                .replace("symbol:'MSFT'", f"symbol:'{SYMBOL}'"))


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('STILL_CHROMIUM', '/usr/bin/chromium'), args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/data.js', lambda route: route.fulfill(status=200, content_type='text/javascript', body=hostile_data()))
    page.goto(BASE, wait_until='networkidle')
    expect(page.locator('#main-holdings')).to_contain_text(NAME)
    expect(page.locator('#instrument-list')).to_contain_text(SYMBOL)

    page.get_by_role('button', name=f'Open {NAME} in a tab', exact=True).first.click()
    expect(page.locator('h1')).to_have_text(NAME)
    expect(page.locator('.stock-scope')).to_contain_text(EXCHANGE)
    expect(page.locator('.stock-scope')).to_contain_text(SECTOR)
    page.get_by_role('tab', name='Research', exact=True).last.click()
    expect(page.locator('#canvas-content')).to_contain_text(f'{NAME} is classified as')
    page.locator('#global-search').fill('ms"')
    expect(page.locator('#global-results')).to_contain_text(SYMBOL)
    page.keyboard.press('Enter')
    expect(page.locator('h1')).to_have_text('Microsoft')  # The escaped attribute still finds the instrument.

    page.goto(BASE + '/#discover', wait_until='networkidle')
    expect(page.locator('#discover-sector')).to_contain_text(SECTOR)
    assert page.evaluate('window.__xss') is None, 'An injected handler ran'
    assert page.locator('.injected, #app img, #canvas-content svg[onload]').count() == 0
    assert not errors, errors
    browser.close()
    print('Escaping checks passed: names, symbols, sectors and exchanges render as text in lists, tabs, search and research.')
