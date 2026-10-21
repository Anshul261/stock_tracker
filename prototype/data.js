/* Synthetic fixture. Prices are USD, purchases occur on 2026-01-06. */
(() => {
  const positions = [
    { symbol:'NVDA', name:'NVIDIA', legalName:'NVIDIA Corporation', sector:'Semiconductors', exchange:'NASDAQ', qty:240, cost:128.40, price:182.64, previous:179.31, seed:7 },
    { symbol:'MSFT', name:'Microsoft', legalName:'Microsoft Corporation', sector:'Technology', exchange:'NASDAQ', qty:80, cost:437.50, price:521.38, previous:518.12, seed:13 },
    { symbol:'AAPL', name:'Apple', legalName:'Apple Inc.', sector:'Technology', exchange:'NASDAQ', qty:160, cost:221.60, price:248.50, previous:250.18, seed:21 },
    { symbol:'GOOGL', name:'Alphabet', legalName:'Alphabet Inc.', sector:'Technology', exchange:'NASDAQ', qty:140, cost:173.25, price:198.24, previous:196.47, seed:31 },
    { symbol:'AMZN', name:'Amazon', legalName:'Amazon.com, Inc.', sector:'Consumer discretionary', exchange:'NASDAQ', qty:110, cost:199.10, price:224.16, previous:222.68, seed:43 },
    { symbol:'VTI', name:'Vanguard Total Market', legalName:'Vanguard Total Stock Market ETF', sector:'Broad market ETF', exchange:'NYSE Arca', qty:130, cost:277.20, price:308.72, previous:307.55, seed:53 },
    { symbol:'TSM', name:'Taiwan Semiconductor', legalName:'Taiwan Semiconductor ADR', sector:'Semiconductors', exchange:'NYSE', qty:70, cost:193.80, price:244.80, previous:240.35, seed:67 },
    { symbol:'COST', name:'Costco', legalName:'Costco Wholesale Corporation', sector:'Consumer staples', exchange:'NASDAQ', qty:18, cost:905.30, price:962.40, previous:966.10, seed:79 },
  ];
  const cents = value => Math.round(value*100);
  const positionValue = h => h.qty*cents(h.price)/100;
  const purchaseValue = h => h.qty*cents(h.cost)/100;
  const positionGain = h => (h.qty*(cents(h.price)-cents(h.cost)))/100;
  const positionDay = h => h.qty*(cents(h.price)-cents(h.previous))/100;
  const totalCents = positions.reduce((s,h)=>s+h.qty*cents(h.price),0);
  const basisCents = positions.reduce((s,h)=>s+h.qty*cents(h.cost),0);
  const cashCents = 1482050;
  const account = { value:(totalCents+cashCents)/100, cash:cashCents/100, invested:totalCents/100, basis:basisCents/100, gain:(totalCents-basisCents)/100, day:positions.reduce((s,h)=>s+h.qty*(cents(h.price)-cents(h.previous)),0)/100, date:'2026-10-21', purchaseDate:'2026-01-06' };
  console.assert(cents(account.value)===totalCents+cashCents,'Holdings plus cash must equal account value');
  console.assert(cents(account.invested-account.basis)===cents(account.gain),'Gain reconciles to cost');
  console.assert(positions.every(h=>h.qty>0&&h.cost>0&&h.price>0),'Positive prices and share counts');
  window.StillData = Object.freeze({positions:positions.map(Object.freeze), account:Object.freeze(account), cents, positionValue, purchaseValue, positionGain, positionDay});
})();
