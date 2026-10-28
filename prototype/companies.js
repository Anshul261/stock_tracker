/* US-listed company search and company pages, from SEC EDGAR through Still's local server.
   No prices: SEC data has none, and Still shows prices only for holdings, from IBKR reports. */
(() => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const link = (url, label, css='') => `<a class="${css}" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}<span class="sr-only"> (opens in a new tab)</span></a>`;
  const date = iso => { const d = new Date(iso + 'T00:00:00Z'); return iso && !Number.isNaN(d.getTime()) ? new Intl.DateTimeFormat('en-GB', {day:'numeric', month:'short', year:'numeric', timeZone:'UTC'}).format(d) : '—'; };
  const fiscal = mmdd => /^\d{4}$/.test(mmdd || '') ? new Intl.DateTimeFormat('en-GB', {day:'numeric', month:'long', timeZone:'UTC'}).format(new Date(`2000-${mmdd.slice(0, 2)}-${mmdd.slice(2)}T00:00:00Z`)) : '—';
  const profiles = new Map();
  let searchController, generation = 0, filingsView = 'key';

  async function search(query) {
    searchController?.abort();
    searchController = new AbortController();
    const response = await fetch('/api/companies/search?q=' + encodeURIComponent(query), {signal: searchController.signal, credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.error === 'string' ? data.error : 'Company search failed.');
    return data;
  }

  async function profile(ticker) {
    if (!profiles.has(ticker)) profiles.set(ticker, window.StillApi('/api/companies/profile?ticker=' + encodeURIComponent(ticker)).catch(e => { profiles.delete(ticker); throw e; }));
    return profiles.get(ticker);
  }

  function filingRows(list) {
    // The document title is the link, so the table stays three columns wide on a phone.
    return list.length ? list.map(f => `<tr><td>${esc(date(f.date))}</td><td><strong>${esc(f.form)}</strong></td><td>${link(f.url, f.description, 'filing-link')}${f.reportDate ? `<span class="cell-sub">Period ${esc(date(f.reportDate))}</span>` : ''}</td></tr>`).join('')
      : '<tr><td colspan="3"><div class="empty-state">No filings of these types in SEC’s recent list.</div></td></tr>';
  }
  function filingsTable(list, label) {
    return `<div class="table-frame keep-table"><table class="filings-table" aria-label="${esc(label)}"><thead><tr><th>Filed</th><th>Form</th><th>Document on SEC.gov</th></tr></thead><tbody>${filingRows(list)}</tbody></table></div>`;
  }

  function overview(p, held) {
    const facts = [
      ['Tickers', p.tickers.join(', ') || p.ticker], ['Exchange', p.exchanges.join(', ') || (p.kind === 'fund' ? 'Fund or ETF' : '—')],
      ['Industry', p.sic || '—'], ['Incorporated in', p.state || '—'], ['Fiscal year ends', fiscal(p.fiscalYearEnd)],
      ['SEC filer category', p.category || p.entityType || '—'], ['SEC CIK', String(p.cik)],
    ];
    return `${held ? '' : `<div class="data-banner">${'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/></svg>'}<p>Not in your portfolio. Still shows prices only for holdings, from your IBKR reports; this page has company information, SEC filings and news.</p></div>`}
      <dl class="company-facts">${facts.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>
      ${p.formerNames.length ? `<p class="detail-note">Formerly ${p.formerNames.map(esc).join(', ')}.</p>` : ''}
      <section class="section"><div class="section-header"><h2>Latest key filings</h2><button class="text-button" data-stock-section="filings">All filings →</button></div>${filingsTable(p.keyFilings.slice(0, 5), 'Latest key filings')}</section>
      <div class="settings-actions">${link(p.edgar, 'Open on SEC EDGAR', 'button')}${p.website ? link(p.website.startsWith('http') ? p.website : 'https://' + p.website, 'Company website') : ''}</div>
      <p class="detail-note">Source: SEC EDGAR, retrieved by Still on this computer. Company information is as filed with the SEC.</p>`;
  }

  function filings(p) {
    const list = filingsView === 'key' ? p.keyFilings : p.filings.slice(0, 100);
    return `<div class="list-chips filings-filter" role="group" aria-label="Filing types"><button data-filings="key" class="${filingsView === 'key' ? 'active' : ''}" aria-pressed="${filingsView === 'key'}">Annual, quarterly & current reports</button><button data-filings="all" class="${filingsView === 'all' ? 'active' : ''}" aria-pressed="${filingsView === 'all'}">All recent filings</button></div>
      ${filingsTable(list, 'SEC filings')}
      <p class="detail-note">10-K is the annual report, 10-Q the quarterly report and 8-K a report of a major event. Funds file N-CSR and 497K instead. ${link(p.edgar, 'See every filing on SEC EDGAR')}</p>`;
  }

  async function mount(el, {ticker, section, held}) {
    const version = ++generation;
    el.innerHTML = '<p class="news-loading" role="status">Loading from SEC EDGAR…</p>';
    let p;
    try { p = await profile(ticker); }
    catch (e) {
      if (version !== generation || !el.isConnected) return;
      const contact = /contact email/.test(e.message);
      el.innerHTML = `<div class="data-banner warning"><p>${esc(e.message)}</p>${contact ? '<button class="button" data-setting="search">Open settings</button>' : ''}</div>`;
      return;
    }
    if (version !== generation || !el.isConnected) return;
    const render = () => { el.innerHTML = section === 'filings' ? filings(p) : overview(p, held); };
    render();
    el.onclick = e => { const b = e.target.closest('[data-filings]'); if (b) { filingsView = b.dataset.filings; render(); el.querySelector(`[data-filings="${filingsView}"]`)?.focus(); } };
  }

  window.StillCompanies = Object.freeze({search, mount, unmount() { generation++; }});
})();
