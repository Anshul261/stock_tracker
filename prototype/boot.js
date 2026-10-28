/* Decides what the workspace shows before it starts: sign-in, imported IBKR data or the demo. */
(() => {
  'use strict';
  async function api(path, {method='GET', body, raw, type}={}) {
    const headers = {Accept:'application/json'};
    if (method !== 'GET') headers['X-Still-Request'] = '1';
    let payload;
    if (raw !== undefined) { payload = raw; headers['Content-Type'] = type; }
    else if (body !== undefined) { payload = JSON.stringify(body); headers['Content-Type'] = 'application/json'; }
    let response;
    try { response = await fetch(path, {method, headers, body:payload, credentials:'same-origin', cache:'no-store'}); }
    catch { throw Object.assign(new Error('Still’s local server is not running. Open Still again from its shortcut.'), {offline:true}); }
    if (!(response.headers.get('content-type')||'').includes('application/json')) throw Object.assign(new Error('Still’s local server is not running.'), {offline:true});
    const data = await response.json();
    // A session that expired while the page was open: show the sign-in screen again.
    if (response.status === 401 && window.StillContext?.server) { location.reload(); return new Promise(()=>{}); }
    if (!response.ok) throw Object.assign(new Error(typeof data.error === 'string' ? data.error : 'Request failed.'), {status:response.status});
    return data;
  }
  window.StillApi = api;

  window.StillReady = (async () => {
    let session;
    try { session = await api('/api/session'); }
    catch { window.StillContext = {server:false}; return; }  // Offline file or static preview: demo only.
    if (!session.signedIn) { window.StillGate.show(session.state); return new Promise(()=>{}); }
    const context = {server:true, mode:session.mode, prices:false};
    if (session.mode === 'ibkr') {
      try {
        const result = await api('/api/portfolio');
        context.prices = Boolean(result.prices);
        if (result.view) window.StillData = window.StillModel.fromServer(result.view);
        else { context.noData = true; context.viewError = result.error; }
      } catch (error) { context.noData = true; context.viewError = error.message; }
    }
    else { try { context.prices = Boolean((await api('/api/prices/settings')).configured); } catch { /* prices stay off */ } }
    window.StillContext = context;
  })();
})();
