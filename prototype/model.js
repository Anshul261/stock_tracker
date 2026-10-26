/* Builds the workspace data the views read, from the demo fixture or an imported IBKR view. */
(() => {
  'use strict';
  const cents = value => Math.round(value*100);
  const round = value => cents(value)/100;
  const units = h => h.qty*(h.multiplier??1);
  const fx = h => h.fx??1;
  // Values are in the account's base currency; prices stay in each instrument's own currency.
  const positionValue = h => round(units(h)*h.price*fx(h));
  const purchaseValue = h => h.cost==null?null:round(units(h)*h.cost*fx(h));
  const positionGain = h => h.cost==null?null:round(positionValue(h)-purchaseValue(h));
  const positionDay = h => h.previous==null?null:round(units(h)*(h.price-h.previous)*fx(h));
  const sum = (list, fn) => { let total = 0; for (const item of list) { const v = fn(item); if (v == null) return null; total += cents(v); } return total/100; };

  function build(raw) {
    const positions = raw.positions.map(p => Object.freeze({...p, multiplier: p.multiplier??1, fx: p.fx??1, currency: p.currency||raw.currency}));
    const invested = sum(positions, positionValue) ?? 0;
    const basis = sum(positions, purchaseValue);
    const account = {
      value: round(invested+raw.cash), cash: raw.cash, invested, basis,
      gain: basis==null?null:round(invested-basis), day: positions.length?sum(positions, positionDay):null,
      date: raw.asOf, purchaseDate: raw.firstPurchase,
    };
    return Object.freeze({
      live: Boolean(raw.live), currency: raw.currency, asOf: raw.asOf, previousDate: raw.previousDate||null,
      positions: Object.freeze(positions), account: Object.freeze(account), history: raw.history||[],
      reconciliation: raw.reconciliation||null, warnings: raw.warnings||[], notice: raw.notice||'',
      cents, positionValue, purchaseValue, positionGain, positionDay,
    });
  }

  function fromServer(view) {
    return build({
      live: true, currency: view.baseCurrency, asOf: view.asOf, previousDate: view.previousDate,
      positions: view.positions, cash: view.cashBase, history: view.history, firstPurchase: view.firstPurchase,
      reconciliation: view.reconciliation, warnings: view.warnings,
    });
  }

  window.StillModel = Object.freeze({build, fromServer});
})();
