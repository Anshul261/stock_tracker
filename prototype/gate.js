/* First-run setup and sign-in screens. Shown before any portfolio data loads. */
(() => {
  'use strict';
  const $ = (s, r=document) => r.querySelector(s);
  const mark = '<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M9 20V12m7 12V8m7 12V12"/></svg>';

  function strength(value) {
    if (!value) return '';
    if (value.length < 12) return `${12-value.length} more character${value.length===11?'':'s'} needed`;
    const kinds = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter(r => r.test(value)).length;
    if (value.length >= 20 || (value.length >= 14 && kinds >= 3)) return 'Strong';
    return 'Acceptable; a longer phrase of several words is stronger';
  }

  function setupView() {
    return `<form class="gate-card" id="gate-setup" novalidate>
      <div class="gate-brand">${mark}<span>still<span>.</span></span></div>
      <h1>Set up Still</h1>
      <p>Still runs only on this computer. Choose a passphrase to protect your IBKR token and imported reports; they are encrypted with it.</p>
      <label class="field"><span>Passphrase</span><input id="gate-pass" type="password" autocomplete="new-password" minlength="12" maxlength="1024" required aria-describedby="gate-strength"></label>
      <p class="field-hint" id="gate-strength" aria-live="polite">At least 12 characters. A few unrelated words work well.</p>
      <label class="field"><span>Confirm passphrase</span><input id="gate-confirm" type="password" autocomplete="new-password" maxlength="1024" required></label>
      <fieldset class="gate-choice"><legend>Start with</legend>
        <label><input type="radio" name="mode" value="ibkr" checked><span><strong>My IBKR account</strong><small>Connect Flex reporting or upload a report next. Read-only: Flex cannot trade or move money.</small></span></label>
        <label><input type="radio" name="mode" value="demo"><span><strong>Demo data</strong><small>Explore with a synthetic portfolio. You can connect IBKR later in Settings.</small></span></label>
      </fieldset>
      <p class="gate-warning">There is no passphrase recovery. If you forget it, you can reset Still, which deletes its saved data.</p>
      <p class="gate-error" role="alert" hidden></p>
      <button class="button primary gate-submit" type="submit">Create passphrase & continue</button>
    </form>`;
  }

  function unlockView() {
    return `<form class="gate-card" id="gate-login" novalidate>
      <div class="gate-brand">${mark}<span>still<span>.</span></span></div>
      <h1>Unlock Still</h1>
      <p>Enter your passphrase to decrypt your saved data on this computer.</p>
      <label class="field"><span>Passphrase</span><input id="gate-pass" type="password" autocomplete="current-password" maxlength="1024" required autofocus></label>
      <p class="gate-error" role="alert" hidden></p>
      <button class="button primary gate-submit" type="submit">Unlock</button>
      <details class="gate-reset"><summary>Forgot your passphrase?</summary>
        <p>It cannot be recovered. Resetting deletes Still’s saved token, settings and imported reports from this computer, then starts setup again. Your IBKR account is not affected.</p>
        <label class="field"><span>Type RESET to confirm</span><input id="gate-reset-confirm" autocomplete="off" maxlength="5"></label>
        <button class="button danger" type="button" id="gate-reset">Reset Still</button>
      </details>
    </form>`;
  }

  function show(state) {
    document.getElementById('app').hidden = true;
    const gate = document.createElement('main');
    gate.className = 'gate';
    gate.innerHTML = state === 'setup' ? setupView() : unlockView();
    document.body.append(gate);
    const error = $('.gate-error', gate);
    const fail = message => { error.textContent = message; error.hidden = false; };
    const busy = on => { const b = $('.gate-submit', gate); b.disabled = on; b.setAttribute('aria-busy', String(on)); };
    $('#gate-pass', gate).focus();
    if (state === 'setup') $('#gate-pass', gate).addEventListener('input', e => { $('#gate-strength', gate).textContent = strength(e.target.value) || 'At least 12 characters. A few unrelated words work well.'; });
    gate.addEventListener('submit', async event => {
      event.preventDefault();
      error.hidden = true;
      const passphrase = $('#gate-pass', gate).value;
      try {
        busy(true);
        if (state === 'setup') {
          if (passphrase !== $('#gate-confirm', gate).value) { busy(false); return fail('The passphrases do not match.'); }
          const mode = $('input[name=mode]:checked', gate).value;
          await window.StillApi('/api/setup', {method:'POST', body:{passphrase, mode}});
          location.hash = mode === 'ibkr' ? '#settings/ibkr' : '#portfolio';
        } else {
          await window.StillApi('/api/login', {method:'POST', body:{passphrase}});
        }
        location.reload();
      } catch (e) { busy(false); fail(e.message); $('#gate-pass', gate).select(); }
    });
    $('#gate-reset', gate)?.addEventListener('click', async () => {
      error.hidden = true;
      try {
        await window.StillApi('/api/reset', {method:'POST', body:{confirm:$('#gate-reset-confirm', gate).value.trim()}});
        location.hash = '';
        location.reload();
      } catch (e) { fail(e.message); }
    });
  }

  window.StillGate = Object.freeze({show});
})();
