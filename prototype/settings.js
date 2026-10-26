/* Settings panels. Every value saved here goes to the local server, which encrypts secrets;
   tokens and keys are never stored in the browser or sent back to it. */
(() => {
  'use strict';
  const $ = (s, r=document) => r.querySelector(s);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const link = (url, label, css='') => `<a class="${css}" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}<span class="sr-only"> (opens in a new tab)</span></a>`;
  const when = iso => { if (!iso) return 'Never'; const d = new Date(iso.length === 10 ? iso + 'T00:00:00Z' : iso); return Number.isNaN(d.getTime()) ? '—' : new Intl.DateTimeFormat('en-GB', iso.length === 10 ? {day:'numeric', month:'short', year:'numeric', timeZone:'UTC'} : {day:'numeric', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit'}).format(d); };
  const portalUrl = 'https://www.interactivebrokers.com/sso/Login';
  const flexGuideUrl = 'https://www.ibkrguides.com/advisorportal/ug/flex-web-service.htm';
  const flexQueriesDocs = 'https://www.ibkrguides.com/clientportal/performanceandstatements/activityflex.htm';
  const tokenDocs = 'https://www.interactivebrokers.com/docs/web-api/flex-web-service/client-portal-configuration/enable-and-create-access-token';
  const CHECKS = {position_value:'Position value', trade_net_cash:'Trade net cash', quantity:'Quantity roll-forward', cash:'Cash roll-forward',
    cost_basis:'Cost basis (FIFO)', realized_pnl:'Realized profit'};
  let generation = 0, poll, root, opts;

  function remount() { if (root) mount(root, opts); }
  function toast(text) { const t = document.getElementById('toast'); t.textContent = text; t.classList.add('visible'); clearTimeout(t._timer); t._timer = setTimeout(() => t.classList.remove('visible'), 2600); }
  function message(el, text, kind='error') { if (!el) return; el.textContent = text; el.className = 'form-message ' + kind; el.hidden = !text; }
  async function act(button, work, out) {
    message(out, '');
    button.disabled = true; button.setAttribute('aria-busy', 'true');
    try { return await work(); }
    catch (e) { message(out, e.message); return null; }
    finally { button.disabled = false; button.removeAttribute('aria-busy'); }
  }

  // IBKR ---------------------------------------------------------------------
  function status(s) {
    if (s.attention) return ['attention', {token_expired:'Token expired', token_invalid:'Token not accepted', ip_restricted:'IP restriction blocked the sync', query_invalid:'Query ID not found', account_inactive:'Reporting account inactive', too_many_failures:'IBKR paused access after failed attempts', legacy_query:'Use an Activity Flex Query'}[s.attention] || 'Needs attention'];
    if (s.tokenSaved && s.lastSync) return ['live', `Connected · last sync ${when(s.lastSync)}`];
    if (s.tokenSaved) return ['ready', 'Saved · not synced yet'];
    if (s.reports.length) return ['ready', 'Reports uploaded · no automatic sync'];
    return ['', 'Not connected'];
  }
  function expiryNote(s) {
    if (!s.tokenExpires) return '';
    const days = Math.round((new Date(s.tokenExpires + 'T00:00:00Z') - Date.now()) / 864e5);
    if (days < 0) return `<p class="data-banner warning">Your Flex token expired on ${when(s.tokenExpires)}. Generate a new one in Client Portal and save it below.</p>`;
    if (days <= 14) return `<p class="data-banner warning">Your Flex token expires on ${when(s.tokenExpires)}. Generate a new one in Client Portal before then.</p>`;
    return '';
  }
  function reconciliation(s) {
    const r = s.reconciliation;
    if (!r) return `<p>${s.viewError ? esc(s.viewError) : 'Import a report to see how it reconciles.'}</p>`;
    const c = r.counts;
    const rows = r.checks.map(k => `<tr><td><span class="check-status ${esc(k.status)}">${k.status === 'fail' ? 'Failed' : 'Unverified'}</span></td><td>${esc(CHECKS[k.name] || k.name)}</td><td>${esc(k.subject)}</td><td>${esc(k.detail || (k.expected != null ? `Expected ${k.expected}, IBKR reports ${k.actual}` : ''))}${k.expected != null && k.detail ? `<br><span class="muted">Expected ${esc(k.expected)} · IBKR ${esc(k.actual)}</span>` : ''}</td></tr>`).join('');
    return `<div class="check-counts"><span><strong class="num">${c.pass}</strong> passed</span><span class="${c.fail ? 'negative' : ''}"><strong class="num">${c.fail}</strong> failed</span><span><strong class="num">${c.unverified}</strong> unverified</span></div>
      <p>Still recomputes positions, cash and cost basis from the report’s own transactions and compares them with IBKR’s totals. Unverified means the report alone cannot settle a check; it is never counted as passed.</p>
      ${rows ? `<div class="table-frame keep-table"><table class="check-table" aria-label="Checks that did not pass"><thead><tr><th>Status</th><th>Check</th><th>For</th><th>Why</th></tr></thead><tbody>${rows}</tbody></table></div>` : ''}
      ${r.notices.length ? `<ul class="notice-list">${r.notices.map(n => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}
      ${!r.fromInception && c.unverified ? '<p class="settings-note">Quantity and cost-basis checks need the starting holdings. If your reports begin when the account opened, tick that option below; otherwise import earlier history.</p>' : ''}`;
  }
  function job(s) {
    const j = s.job;
    if (!j) return '';
    const steps = j.steps > 1 ? ` · step ${j.step} of ${j.steps}` : '';
    return `<div class="sync-progress ${j.done ? (j.ok ? 'ok' : 'failed') : 'running'}" role="status"><strong>${esc(j.done ? j.message : j.stage + '…')}</strong>${j.done ? '' : `<span>${esc(steps)} IBKR can take a minute to prepare a report.</span>`}</div>`;
  }
  // Current Client Portal steps (checked against IBKR's guides, October 2026). Screenshots are the
  // owner's own, with the account number blacked out; numbered boxes match the step numbers.
  const GUIDE = [
    {title: 'Open Flex Queries', body: 'Sign in to Client Portal and choose <strong>Performance &amp; Reports → Flex Queries</strong>. (Also under <strong>Menu → Reporting → Flex Queries</strong>.)',
      figures: [['assets/guide/menu.webp', 'Performance & Reports menu with Flex Queries highlighted', 259, 380]]},
    {title: 'Create an Activity Flex Query', body: 'In the <strong>Activity Flex Query</strong> panel, click <strong>+</strong> in its top-right corner. Name the query, for example <em>Still</em>. Skip “Configure with AI”.',
      figures: [['assets/guide/flex-queries.webp', 'Flex Queries page with the Activity Flex Query plus button and the Flex Web Service gear highlighted', 1220, 600]]},
    {title: 'Choose these sections, not all of them', body: `<p>Under <strong>Sections</strong>, select:</p>
      <ul class="guide-sections"><li><b>a</b> Account Information</li><li><b>b</b> Cash Report</li><li><b>c</b> Cash Transactions</li><li><b>d</b> Corporate Actions</li><li><b>e</b> Open Positions</li><li><b>f</b> Trades</li><li><b>g</b> Transfers</li></ul>
      <p>Each one opens a list of fields. For <strong>Account Information</strong>, tick only <strong>Account ID</strong> and <strong>Currency</strong>; Still needs nothing else there, and leaving out your name, address and date of birth keeps them out of the report. For the others, choose <strong>Select All</strong>. Then click <strong>Save</strong>. Where a section offers a level of detail, pick <strong>Summary</strong> for Open Positions, <strong>Execution</strong> for Trades and <strong>Detail</strong> for Cash Transactions.</p>
      <p>Transfers is recommended: Still doesn’t calculate with it yet, but it lets reconciliation say “unverified” instead of reporting a false mismatch when shares moved in from another broker. If you trade options, also add <strong>Option Exercises, Assignments and Expirations</strong> for the same reason. Still doesn’t use the other sections, so leave them off.</p>`,
      figures: [['assets/guide/sections.webp', 'Flex query section list with the seven sections Still needs highlighted', 866, 896]]},
    {title: 'Set delivery and format, then create', body: `<p>Under <strong>Delivery Configuration</strong>, check that your account is selected, then set <b class="guide-key">a</b> <strong>Format: XML</strong> and <b class="guide-key">b</b> <strong>Period: Last 365 Calendar Days</strong>.</p>
      <p>Under <strong>General Configuration</strong> set <b class="guide-key">c</b> <strong>Date Format: yyyyMMdd</strong>, <b class="guide-key">d</b> <strong>Time Format: HHmmss</strong> and <b class="guide-key">e</b> <strong>Date/Time Separator: ; (semi-colon)</strong>. Still reads only these formats. Set <b class="guide-key">f</b> <strong>Include Currency Rates?</strong> to <strong>Yes</strong>; Still uses the rates to convert cash and holdings in other currencies to your base currency. Leave the other options at their defaults (<strong>No</strong>).</p>
      <p>Click <strong>Continue</strong>, check the summary, and click <b class="guide-key">g</b> <strong>Create</strong>. IBKR confirms that the query has been saved; click <strong>Ok</strong>.</p>`,
      figures: [['assets/guide/delivery.webp', 'Delivery and General Configuration with Format, Period, date and time formats, separator and Include Currency Rates highlighted', 878, 682],
                ['assets/guide/review.webp', 'Review screen with the Create button highlighted', 980, 539]]},
    {title: 'Copy the Query ID', body: 'Back on <strong>Flex Queries</strong>, your new query is listed under Activity Flex Query. Click the <strong>info (i)</strong> icon to its left. The <strong>Query ID</strong> is the number at the top of the pop-up, usually 6–7 digits. It belongs to the query, not the token, so it isn’t on the Flex Web Service screen. Copy it into <strong>2. Connect</strong> below.',
      figures: [['assets/guide/query-id.webp', 'Flex Queries list with the info icon next to the saved query and the Flex Web Service gear highlighted', 1120, 576]]},
    {title: 'Turn on Flex Web Service and copy the token', body: 'In <strong>Flex Web Service Configuration</strong>, click the <strong>gear</strong>. Switch the service on; the status then reads <strong>Enabled</strong> and a token appears. To choose how long it lasts and, optionally, the only IP address allowed to use it, click <strong>Generate A New Token</strong>; a new token cancels the old one. Paste the token below and note its expiry date for the reminder. This screen shows only the token; the Query ID comes from the info (i) icon in step 5.',
      figures: [['assets/guide/token.webp', 'Flex Web Service Configuration with the gear and the Enabled status highlighted', 523, 477]]},
  ];
  function guide(configured) {
    return `<section class="settings-block"><h2>1. Prepare Flex in IBKR</h2><div><details class="settings-guide" ${configured ? '' : 'open'}><summary>Create the report and token in Client Portal (about 5 minutes)</summary>
      <p class="field-hint">Screenshots are from IBKR Client Portal in October 2026, with the account number hidden. Numbered boxes match the steps; lettered boxes match the lists.</p>
      <ol class="guide-steps">${GUIDE.map(step => `<li><h3>${step.title}</h3>${step.body.startsWith('<p>') ? step.body : `<p>${step.body}</p>`}${(step.figures || []).map(([src, alt, w, h]) => `<figure class="guide-figure" style="max-width:${Math.min(640, w)}px"><a href="${src}" target="_blank" rel="noopener"><img src="${src}" alt="${esc(alt)}" width="${w}" height="${h}" loading="lazy"></a><figcaption>Your screen may differ slightly. Select the image to enlarge it.</figcaption></figure>`).join('')}</li>`).join('')}</ol>
      <div class="settings-actions">${link(portalUrl, 'Open IBKR Client Portal', 'button')}${link(tokenDocs, 'IBKR’s token guide')}${link(flexQueriesDocs, 'IBKR’s Flex Query guide')}</div></details></div></section>`;
  }
  function ibkr(s, ctx) {
    const [tone, label] = status(s);
    const configured = s.tokenSaved && s.queryIdSaved;
    const running = s.job && !s.job.done;
    const today = new Date().toISOString().slice(0, 10);
    const yearAgo = new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10);
    return `<section class="broker-summary" aria-labelledby="broker-name"><div><p class="broker-label">Reporting connection</p><h2 id="broker-name">Interactive Brokers</h2><p>Your reports through IBKR’s official Flex Web Service. Read-only: Flex cannot place orders, move money or change your account.</p></div><span class="broker-status ${tone}"><span class="connection-dot ${tone}"></span>${esc(label)}</span></section>
    <dl class="connection-facts"><div><dt>Data in this workspace</dt><dd>${ctx.mode !== 'ibkr' ? `Demo data${s.asOf ? ' (IBKR reports saved; switch in Data & privacy)' : ''}` : s.asOf ? `IBKR report of ${when(s.asOf)}` : 'Demo until a report is imported'}</dd></div><div><dt>Last successful import</dt><dd>${when(s.lastSuccess)}</dd></div><div><dt>Token</dt><dd>${s.tokenSaved ? `Saved ${when(s.tokenSavedAt)}${s.tokenExpires ? ` · expires ${when(s.tokenExpires)}` : ''}` : 'Not saved'}</dd></div></dl>
    ${expiryNote(s)}
    ${guide(configured)}
    <section class="settings-block"><h2>2. Connect</h2><div><form id="ibkr-credentials" class="settings-form" autocomplete="off">
      <label class="field"><span>Flex Query ID</span><input name="queryId" inputmode="numeric" pattern="[0-9]*" maxlength="32" placeholder="${s.queryIdSaved ? 'Saved — enter again to change' : 'e.g. 1234567'}" ${s.queryIdSaved ? '' : 'required'}></label>
      <label class="field"><span>Flex token</span><input name="token" type="password" maxlength="4096" autocomplete="off" placeholder="${s.tokenSaved ? 'Saved — leave blank to keep it' : 'Paste the token from Client Portal'}"></label>
      <label class="field"><span>Token expires <small>(optional, for a reminder)</small></span><input name="tokenExpires" type="date" value="${esc(s.tokenExpires || '')}"></label>
      <p class="field-hint">Saved encrypted on this computer. Still never shows the token again and sends it only to IBKR’s Flex service over HTTPS.</p>
      <p class="form-message" hidden></p>
      <div class="settings-actions"><button class="button primary" type="submit">Save connection</button></div></form></div></section>
    <section class="settings-block"><h2>3. Import</h2><div>
      <div class="settings-actions"><button class="button primary" id="ibkr-sync" ${configured && !running ? '' : 'disabled'}>Sync now</button><span class="muted small">${configured ? 'Fetches every completed day since your latest report.' : 'Save your Query ID and token first, or upload a report below.'}</span></div>
      <div id="ibkr-job">${job(s)}</div>
      <form id="ibkr-history" class="settings-inline"><label class="field"><span>Import history from</span><input name="fromDate" type="date" max="${today}" value="${yearAgo}" required></label><button class="button" type="submit" ${configured && !running ? '' : 'disabled'}>Import history</button></form>
      <p class="field-hint">Longer histories are fetched one year at a time, a few seconds apart, as IBKR requires.</p>
      <form id="ibkr-upload" class="settings-inline"><label class="field"><span>Or upload a report downloaded from Client Portal</span><input name="file" type="file" accept=".xml,application/xml,text/xml" required></label><button class="button" type="submit">Upload</button></form>
      <label class="check-option"><input type="checkbox" id="ibkr-inception" ${s.fromInception ? 'checked' : ''}><span>My imported reports start when the account opened<small>Lets Still verify quantities and cost basis from zero.</small></span></label>
      <p class="form-message" id="ibkr-import-message" hidden></p></div></section>
    <section class="settings-block"><h2>Reconciliation</h2><div>${reconciliation(s)}</div></section>
    <section class="settings-block"><h2>Daily sync</h2><div><form id="ibkr-schedule" class="settings-inline"><label class="check-option"><input type="checkbox" name="enabled" ${s.schedule?.enabled ? 'checked' : ''} ${configured ? '' : 'disabled'}><span>Sync once a day</span></label><label class="field"><span>After</span><input name="time" type="time" value="${esc(s.schedule?.time || '07:00')}" required></label><button class="button" type="submit" ${configured ? '' : 'disabled'}>Save schedule</button></form><p class="field-hint">Runs while Still is open and unlocked. If the computer was off, the next sync catches up on the missed days.</p></div></section>
    <section class="settings-block"><h2>Imported reports</h2><div>${s.reports.length ? `<ul class="report-list">${s.reports.map(r => `<li><span>${when(r.fromDate)} – ${when(r.toDate)}</span><span class="muted">${r.source === 'upload' ? 'Uploaded' : 'Synced'} ${when(r.received)}</span></li>`).join('')}</ul>` : '<p>None yet.</p>'}
      ${s.runs.length ? `<details class="settings-guide"><summary>Sync history</summary><ul class="report-list">${s.runs.slice(0, 10).map(r => `<li><span>${esc({sync:'Sync', history:'History import', scheduled:'Daily sync', upload:'Upload'}[r.kind] || r.kind)} · ${when(r.started)}</span><span class="${r.status === 'failed' ? 'negative' : 'muted'}">${esc(r.message || r.status)}</span></li>`).join('')}</ul></details>` : ''}</div></section>
    <section class="settings-block"><h2>Stop access</h2><div>
      <p>Disconnect removes the token and Query ID from Still and turns off the daily sync. Imported reports stay until you delete them.</p>
      <div class="settings-actions"><button class="button" id="ibkr-disconnect" ${s.tokenSaved || s.queryIdSaved ? '' : 'disabled'}>Disconnect</button></div>
      <form id="ibkr-delete" class="settings-inline"><label class="field"><span>Delete all imported reports — type DELETE</span><input name="confirm" autocomplete="off" maxlength="6"></label><button class="button danger" type="submit" ${s.reports.length ? '' : 'disabled'}>Delete imported data</button></form>
      <p class="form-message" id="ibkr-stop-message" hidden></p>
      <details class="settings-guide"><summary>Disable Flex access at IBKR</summary><ol><li>Open <strong>Reporting → Flex Queries</strong> in Client Portal.</li><li>Open <strong>Flex Web Service Configuration</strong>.</li><li>Switch <strong>Flex Web Service</strong> off and save.</li></ol><p>This stops all Flex retrieval for your account, including other tools. Still cannot switch it off for you.</p><div class="settings-actions">${link(portalUrl, 'Open IBKR to disable Flex', 'button')}${link(flexGuideUrl, 'IBKR’s official instructions')}</div></details></div></section>`;
  }
  function bindIbkr(el, s) {
    const api = window.StillApi;
    const reloadAfterImport = text => { toast(text + ' Updating your workspace…'); setTimeout(() => location.reload(), 900); };
    $('#ibkr-credentials', el).addEventListener('submit', async e => {
      e.preventDefault();
      const f = e.target, out = $('.form-message', f);
      const queryId = f.queryId.value.trim();
      if (!queryId && !s.queryIdSaved) return message(out, 'Enter your Flex Query ID.');
      const saved = await act($('button', f), () => api('/api/ibkr/credentials', {method:'POST', body:{queryId: queryId || undefined, token: f.token.value, tokenExpires: f.tokenExpires.value}}), out);
      if (saved) { toast('Connection saved.'); remount(); }
    });
    $('#ibkr-sync', el).addEventListener('click', async e => { const r = await act(e.target, () => api('/api/ibkr/sync', {method:'POST'}), $('#ibkr-import-message', el)); if (r) watch(); });
    $('#ibkr-history', el).addEventListener('submit', async e => { e.preventDefault(); const r = await act($('button', e.target), () => api('/api/ibkr/history', {method:'POST', body:{fromDate: e.target.fromDate.value}}), $('#ibkr-import-message', el)); if (r) watch(); });
    $('#ibkr-upload', el).addEventListener('submit', async e => {
      e.preventDefault();
      const file = e.target.file.files[0], out = $('#ibkr-import-message', el);
      if (!file) return message(out, 'Choose an XML report first.');
      if (file.size > 32 * 1024 * 1024) return message(out, 'Choose an XML report under 32 MB.');
      const result = await act($('button', e.target), async () => api('/api/ibkr/upload', {method:'POST', raw: await file.arrayBuffer(), type:'application/xml'}), out);
      if (result) result.stored ? reloadAfterImport(result.message) : message(out, result.message, 'info');
    });
    $('#ibkr-inception', el).addEventListener('change', async e => {
      const r = await act(e.target, () => api('/api/ibkr/options', {method:'POST', body:{fromInception: e.target.checked}}), $('#ibkr-import-message', el));
      if (r) { if (r.reconciliation) reloadAfterImport('Reconciliation updated.'); else remount(); }
    });
    $('#ibkr-schedule', el).addEventListener('submit', async e => {
      e.preventDefault();
      const r = await act($('button', e.target), () => api('/api/ibkr/options', {method:'POST', body:{schedule:{enabled: e.target.enabled.checked, time: e.target.time.value}}}), $('#ibkr-import-message', el));
      if (r) toast(r.schedule.enabled ? `Daily sync after ${r.schedule.time}.` : 'Daily sync off.');
    });
    $('#ibkr-disconnect', el).addEventListener('click', async e => { const r = await act(e.target, () => api('/api/ibkr/disconnect', {method:'POST'}), $('#ibkr-stop-message', el)); if (r) { toast('Token and Query ID removed from Still.'); remount(); } });
    $('#ibkr-delete', el).addEventListener('submit', async e => {
      e.preventDefault();
      const r = await act($('button', e.target), () => api('/api/ibkr/delete-data', {method:'POST', body:{confirm: e.target.confirm.value.trim()}}), $('#ibkr-stop-message', el));
      if (r) reloadAfterImport('Imported reports deleted.');
    });
    if (s.job && !s.job.done) watch();
  }
  function watch() {
    clearTimeout(poll);
    const version = generation;
    const tick = async () => {
      if (version !== generation) return;
      let s;
      try { s = await window.StillApi('/api/ibkr'); } catch { poll = setTimeout(tick, 4000); return; }
      if (version !== generation) return;
      const box = document.getElementById('ibkr-job');
      if (box) box.innerHTML = job(s);
      if (s.job && !s.job.done) { poll = setTimeout(tick, 2000); return; }
      if (s.job?.ok && s.job.message && !/^No new/.test(s.job.message)) { toast(s.job.message + ' Updating your workspace…'); setTimeout(() => location.reload(), 900); }
      else remount();
    };
    poll = setTimeout(tick, 1500);
  }

  // News search ---------------------------------------------------------------
  const PROVIDERS = [
    ['searxng', 'SearXNG', 'Address of a SearXNG instance you run, with JSON output enabled', 'https://search.example.org', 'url'],
    ['brave', 'Brave Search', 'API key from your Brave Search API account', 'Paste your API key', 'password'],
    ['tavily', 'Tavily', 'API key from your Tavily account', 'Paste your API key', 'password'],
  ];
  function search(s) {
    return `<section class="settings-block"><h2>Search provider</h2><div><p>News → Search sends only the words you type to the provider you choose here. Holdings, quantities and IBKR data are never attached. Paid providers can charge per search.</p>
      ${PROVIDERS.map(([id, name, hint, placeholder, type]) => `<form class="provider-form" data-provider="${id}"><div class="provider-head"><strong>${name}</strong><span class="${s.configured[id] ? 'positive' : 'muted'}">${s.configured[id] ? (s.provider === id ? 'Configured · default' : 'Configured') : 'Not configured'}</span></div>
        <label class="field"><span>${hint}</span><input name="value" type="${type}" maxlength="2048" autocomplete="off" placeholder="${s.configured[id] ? 'Saved — enter again to replace' : placeholder}"></label>
        <div class="settings-actions"><button class="button" type="submit">${s.configured[id] ? 'Save & make default' : 'Save'}</button>${s.configured[id] ? `<button class="text-button" type="button" data-remove="${id}">Remove</button>` : ''}</div><p class="form-message" hidden></p></form>`).join('')}
    </div></section>
    <section class="settings-block"><h2>Search limit</h2><div><form id="search-limit" class="settings-inline"><label class="field"><span>Searches allowed each time Still starts</span><input name="limit" type="number" min="1" max="1000" value="${s.limit}" required></label><button class="button" type="submit">Save limit</button></form><p class="field-hint">A safeguard against unexpected provider charges. Results are cached for 10 minutes.</p><p class="form-message" hidden></p></div></section>`;
  }
  function bindSearch(el) {
    el.querySelectorAll('.provider-form').forEach(form => form.addEventListener('submit', async e => {
      e.preventDefault();
      const r = await act($('button', form), () => window.StillApi('/api/search-settings', {method:'POST', body:{provider: form.dataset.provider, value: form.value.value}}), $('.form-message', form));
      if (r) { toast('Search provider saved.'); remount(); }
    }));
    el.querySelectorAll('[data-remove]').forEach(b => b.addEventListener('click', async () => {
      const r = await act(b, () => window.StillApi('/api/search-settings/remove', {method:'POST', body:{provider: b.dataset.remove}}), $('.form-message', b.closest('form')));
      if (r) { toast('Key removed.'); remount(); }
    }));
    $('#search-limit', el).addEventListener('submit', async e => {
      e.preventDefault();
      const r = await act($('button', e.target), () => window.StillApi('/api/search-settings', {method:'POST', body:{limit: Number(e.target.limit.value)}}), $('.form-message', e.target.parentElement));
      if (r) toast('Search limit saved.');
    });
  }

  // Security ------------------------------------------------------------------
  function security(s) {
    return `<section class="settings-block"><h2>Lock</h2><div><p>Locking forgets the decryption key until you enter your passphrase again. Daily syncs pause while Still is locked.</p>
      <form id="auto-lock" class="settings-inline"><label class="field"><span>Ask for the passphrase after</span><select name="minutes">${[15, 30, 60, 120, 240, 480].map(m => `<option value="${m}" ${s.autoLockMinutes === m ? 'selected' : ''}>${m < 60 ? m + ' minutes' : m / 60 + (m === 60 ? ' hour' : ' hours')} idle</option>`).join('')}</select></label><button class="button" type="submit">Save</button></form>
      <div class="settings-actions"><button class="button" id="lock-now">Lock now</button></div><p class="form-message" hidden></p></div></section>
    <section class="settings-block"><h2>Change passphrase</h2><div><form id="change-passphrase" class="settings-form" autocomplete="off">
      <label class="field"><span>Current passphrase</span><input name="current" type="password" autocomplete="current-password" required></label>
      <label class="field"><span>New passphrase</span><input name="next" type="password" autocomplete="new-password" minlength="12" required></label>
      <label class="field"><span>Confirm new passphrase</span><input name="confirm" type="password" autocomplete="new-password" required></label>
      <p class="form-message" hidden></p><div class="settings-actions"><button class="button" type="submit">Change passphrase</button></div></form></div></section>
    <section class="settings-block"><h2>Quit Still</h2><div><p>Stops Still on this computer. Open it again from its shortcut.</p><div class="settings-actions"><button class="button" id="quit-still">Quit Still</button></div></div></section>`;
  }
  function bindSecurity(el) {
    const api = window.StillApi;
    $('#auto-lock', el).addEventListener('submit', async e => { e.preventDefault(); const r = await act($('button', e.target), () => api('/api/settings', {method:'POST', body:{autoLockMinutes: Number(e.target.minutes.value)}}), $('.form-message', e.target.parentElement)); if (r) toast('Auto-lock saved.'); });
    $('#lock-now', el).addEventListener('click', async e => { const r = await act(e.target, () => api('/api/lock', {method:'POST'}), $('.form-message', e.target.closest('div').parentElement)); if (r) location.reload(); });
    $('#change-passphrase', el).addEventListener('submit', async e => {
      e.preventDefault();
      const f = e.target, out = $('.form-message', f);
      if (f.next.value !== f.confirm.value) return message(out, 'The new passphrases do not match.');
      const r = await act($('button', f), () => api('/api/security/passphrase', {method:'POST', body:{current: f.current.value, new: f.next.value}}), out);
      if (r) { f.reset(); message(out, 'Passphrase changed.', 'info'); }
    });
    $('#quit-still', el).addEventListener('click', async e => {
      const r = await act(e.target, () => api('/api/quit', {method:'POST'}), null);
      if (r) document.body.innerHTML = '<main class="gate"><div class="gate-card"><h1>Still has stopped</h1><p>Your data stays encrypted on this computer. Open Still again from its shortcut when you need it.</p></div></main>';
    });
  }

  // Data & privacy --------------------------------------------------------------
  function privacy(s, ctx, data) {
    const server = ctx.server;
    return `${server ? `<section class="settings-block"><h2>Where your data lives</h2><div><p>Only on this computer, in <code>${esc(s.dataDir)}</code>. The IBKR token, search keys and every imported report are encrypted with a key protected by your passphrase. Settings such as the sync time are stored unencrypted. Nothing is sent to the makers of Still.</p></div></section>
    <section class="settings-block"><h2>Workspace data</h2><div><p>Currently showing <strong>${data.live ? 'your IBKR data' : 'demo data'}</strong>.</p><div class="settings-actions"><button class="button" id="mode-switch" data-mode="${s.mode === 'ibkr' ? 'demo' : 'ibkr'}">${s.mode === 'ibkr' ? 'Show demo data instead' : 'Use my IBKR data'}</button>${data.live ? '<a class="button" href="/api/export/holdings.csv" download>Export holdings (CSV)</a>' : ''}</div>${data.live ? '<p class="field-hint">The exported file is not encrypted. Store it somewhere private.</p>' : ''}<p class="form-message" hidden></p></div></section>
    <section class="settings-block"><h2>Reset Still</h2><div><p>Deletes the token, keys, settings and all imported reports from this computer and returns to first-run setup. Your IBKR account is not affected.</p><form id="reset-still" class="settings-inline"><label class="field"><span>Type RESET to confirm</span><input name="confirm" autocomplete="off" maxlength="5"></label><button class="button danger" type="submit">Reset Still</button></form><p class="form-message" hidden></p></div></section>` :
    `<section class="settings-block"><h2>This preview</h2><div><p>This copy of Still runs without its local server, so it can only show demo data. Install and open the Still app to connect IBKR.</p></div></section>`}
    <section class="settings-block"><h2>Saved in this browser</h2><div><p>Watchlist preferences and panel width are saved in this browser. Open stock tabs are saved for this browser session. No token, key or report is stored in the browser.</p><button class="button settings-reset" id="reset-preferences">Reset workspace preferences</button></div></section>
    <section class="settings-block"><h2>Sources & components</h2><div><p>Visual direction and the SVG chart helper follow ${link('https://github.com/Leonxlnx/taste-skill', 'taste-skill')} (MIT). Public Sans is bundled locally under the SIL Open Font License. No third-party scripts, trackers or remote fonts are loaded.</p></div></section>`;
  }
  function bindPrivacy(el) {
    const api = window.StillApi;
    $('#mode-switch', el)?.addEventListener('click', async e => { const r = await act(e.target, () => api('/api/settings', {method:'POST', body:{mode: e.target.dataset.mode}}), $('.form-message', e.target.closest('div').parentElement)); if (r) location.reload(); });
    $('#reset-still', el)?.addEventListener('submit', async e => {
      e.preventDefault();
      const r = await act($('button', e.target), () => api('/api/reset', {method:'POST', body:{confirm: e.target.confirm.value.trim()}}), $('.form-message', e.target.parentElement));
      if (r) { location.hash = ''; location.reload(); }
    });
  }

  async function mount(el, options) {
    root = el; opts = options;
    const version = ++generation;
    clearTimeout(poll);
    const {tab, context, data} = options;
    if (!context.server && tab !== 'privacy') {
      el.innerHTML = `<section class="settings-block"><h2>Needs the Still app</h2><div><p>This copy of Still runs without its local server, so it cannot save connections or keys. Install and open the Still app on your computer, then set this up in Settings.</p></div></section>`;
      return;
    }
    el.innerHTML = '<p class="news-loading" role="status">Loading…</p>';
    try {
      const path = {ibkr:'/api/ibkr', search:'/api/search-settings', security:'/api/settings', privacy:'/api/settings'}[tab];
      const s = context.server ? await window.StillApi(path) : {};
      if (version !== generation || !el.isConnected) return;
      if (tab === 'ibkr') { el.innerHTML = ibkr(s, context); bindIbkr(el, s); }
      else if (tab === 'search') { el.innerHTML = search(s); bindSearch(el); }
      else if (tab === 'security') { el.innerHTML = security(s); bindSecurity(el); }
      else { el.innerHTML = privacy(s, context, data); bindPrivacy(el); }
    } catch (e) {
      if (version === generation) el.innerHTML = `<p class="form-message error">${esc(e.message)}</p>`;
    }
  }
  window.StillSettings = Object.freeze({mount, unmount(){ generation++; clearTimeout(poll); root = null; }});
})();
