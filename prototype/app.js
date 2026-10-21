(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const paths = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    compass: '<circle cx="12" cy="12" r="9"/><path d="m16 8-3 5-5 3 3-5Z"/>',
    spark: '<path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4Z"/><path d="m20 2 .5 1.5L22 4l-1.5.5L20 6l-.5-1.5L18 4l1.5-.5Z"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    shield: '<path d="m12 3 8 3v6c0 4-5 7.5-8 9-3-1.5-8-5-8-9V6Z"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
    sliders: '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="2" fill="currentColor"/><circle cx="15" cy="17" r="2" fill="currentColor"/>',
  };
  function icons(root = document) { $$('[data-icon]', root).forEach(el => el.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[el.dataset.icon] || ''}</svg>`); }
  const holdings = [
    { symbol:'NVDA', name:'NVIDIA', short:'NVIDIA Corporation', sector:'Semiconductors', qty:240, cost:128.40, price:182.64, previous:179.31, date:'Jan 06, 2026', seed:7, mark:'≋' },
    { symbol:'MSFT', name:'Microsoft', short:'Microsoft Corporation', sector:'Technology', qty:80, cost:437.50, price:521.38, previous:518.12, date:'Jan 06, 2026', seed:13, mark:'ms' },
    { symbol:'AAPL', name:'Apple', short:'Apple Inc.', sector:'Technology', qty:160, cost:221.60, price:248.50, previous:250.18, date:'Jan 06, 2026', seed:21, mark:'a' },
    { symbol:'GOOGL', name:'Alphabet', short:'Alphabet Inc.', sector:'Technology', qty:140, cost:173.25, price:198.24, previous:196.47, date:'Jan 06, 2026', seed:31, mark:'G' },
    { symbol:'AMZN', name:'Amazon', short:'Amazon.com, Inc.', sector:'Consumer discretionary', qty:110, cost:199.10, price:224.16, previous:222.68, date:'Jan 06, 2026', seed:43, mark:'a↗' },
    { symbol:'VTI', name:'Vanguard Total Market', short:'Vanguard Total Stock Market ETF', sector:'Broad market ETF', qty:130, cost:277.20, price:308.72, previous:307.55, date:'Jan 06, 2026', seed:53, mark:'V' },
    { symbol:'TSM', name:'Taiwan Semiconductor', short:'Taiwan Semiconductor ADR', sector:'Semiconductors', qty:70, cost:193.80, price:244.80, previous:240.35, date:'Jan 06, 2026', seed:67, mark:'t' },
    { symbol:'COST', name:'Costco', short:'Costco Wholesale Corporation', sector:'Consumer staples', qty:18, cost:905.30, price:962.40, previous:966.10, date:'Jan 06, 2026', seed:79, mark:'C' },
  ];
  // Monetary totals use integer cents. All data is synthetic; no deposits, sales,
  // dividends, fees or FX are represented by this deliberately bounded prototype.
  const cents = n => Math.round(n * 100);
  const cash = 14820.50;
  const investedCents = holdings.reduce((sum,h) => sum + h.qty * cents(h.price),0);
  const costCents = holdings.reduce((sum,h) => sum + h.qty * cents(h.cost),0);
  const total = investedCents / 100 + cash;
  const basis = costCents / 100 + cash;
  const gain = (investedCents - costCents) / 100;
  const today = holdings.reduce((sum,h) => sum + h.qty * (cents(h.price)-cents(h.previous)),0) / 100;
  const usd = (n, decimals=2) => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:decimals,maximumFractionDigits:decimals}).format(n);
  const percent = n => `${n >= 0 ? '+' : '−'}${Math.abs(n).toFixed(2)}%`;
  const change = h => (h.price / h.previous - 1) * 100;
  const growth = h => (h.price / h.cost - 1) * 100;
  const value = h => h.qty * cents(h.price) / 100;
  const pnl = h => h.qty * (cents(h.price)-cents(h.cost)) / 100;
  const tone = n => n >= 0 ? 'positive' : 'negative';
  const signedMoney = n => `${n >= 0 ? '+' : '−'}${usd(Math.abs(n))}`;
  let watchlist = ['NVDA','MSFT','AAPL'];
  try { const saved=JSON.parse(localStorage.getItem('still.watchlist')); if(Array.isArray(saved)) watchlist=[...new Set(saved.filter(s=>holdings.some(h=>h.symbol===s)))]; } catch {}
  let view='portfolio', period='YTD', detailPeriod='YTD', selected=null, sort='default', sortDirection=1, gainers=false, discoveryFilter='all';
  let commandIndex=0, commandActions=[], toastTimer;
  const periods=['1D','1W','1M','3M','YTD','ALL'];
  const periodFraction={'1D':null,'1W':.018,'1M':.047,'3M':.093,'YTD':total/basis-1,'1Y':.218,'ALL':total/basis-1};
  const periodLabels={'1D':'today','1W':'past week','1M':'past month','3M':'past 3 months','YTD':'year to date','1Y':'past year','ALL':'since purchase'};
  function logo(h) { return `<span class="asset-logo ${h.symbol.toLowerCase()}">${h.mark==='ms'?'<span class="ms-grid"><i></i><i></i><i></i><i></i></span>':h.mark}</span>`; }
  function toast(message) { $('#toast').textContent=message; $('#toast').classList.add('visible'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),2600); }
  function openDialog(id) { const dialog=$(id); if(!dialog.open) dialog.showModal(); }
  function closeDialogs() { $$('dialog[open]').forEach(d=>d.close()); }
  function seeded(seed) { return () => { seed=(seed*16807)%2147483647; return (seed-1)/2147483646; }; }
  function series(end,start,seed,count=100) {
    const random=seeded(seed), raw=[0];
    for(let i=1;i<count;i++) raw.push(raw[i-1]+(random()-.47));
    const last=raw[count-1];
    return raw.map((v,i)=>{const t=i/(count-1);return start+(end-start)*t+(v-last*t)*end*.009*Math.sin(Math.PI*t);});
  }
  function chartSeries(h,p) {
    const end=h?h.price:total;
    const start=p==='1D'?(h?h.previous:total-today):p==='ALL'||p==='YTD'?(h?h.cost:basis):end/(1+periodFraction[p]*(h?1.3:1));
    return series(end,start,(h?h.seed:97)+periods.indexOf(p)*17,p==='1D'?48:100);
  }
  function dateRange(p) {
    const end=new Date('2026-10-21T16:00:00Z'), start=new Date(end);
    if(p==='1D') start.setUTCHours(9,30);
    else if(p==='1W') start.setUTCDate(end.getUTCDate()-7);
    else if(p==='1M') start.setUTCMonth(end.getUTCMonth()-1);
    else if(p==='3M') start.setUTCMonth(end.getUTCMonth()-3);
    else if(p==='1Y') start.setUTCFullYear(end.getUTCFullYear()-1);
    else start.setTime(new Date('2026-01-06T16:00:00Z').getTime());
    return {start,end};
  }
  function dateLabel(date,p,full=false) { return new Intl.DateTimeFormat('en-US',p==='1D'?{hour:'numeric',minute:'2-digit',timeZone:'UTC'}:{month:'short',day:full||['1W','1M','3M'].includes(p)?'numeric':undefined,year:full?'numeric':undefined,timeZone:'UTC'}).format(date); }
  function renderChart(container,values,p) {
    const width=Math.max(container.clientWidth,250), height=container.clientHeight||190;
    const right=46,top=14,bottom=25,w=width-right,h=height-top-bottom;
    let low=Math.min(...values),high=Math.max(...values),padding=(high-low)*.20||1; low-=padding;high+=padding;
    const x=i=>i/(values.length-1)*w, y=v=>top+h-(v-low)/(high-low)*h;
    const coords=values.map((v,i)=>`${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    const id=`fill-${container.id}`, {start,end}=dateRange(p);
    const grid=Array.from({length:4},(_,i)=>{const v=low+(high-low)*(i+1)/5;return `<line class="chart-grid" x1="0" x2="${w}" y1="${y(v)}" y2="${y(v)}"/><text x="${w+10}" y="${y(v)+3}">${v>1000?`${(v/1000).toFixed(0)}k`:v.toFixed(0)}</text>`;}).join('');
    const ticks=Array.from({length:5},(_,i)=>{const t=i/4;const date=new Date(start.getTime()+(end-start)*t);return `<text x="${t*w}" y="${height-2}" text-anchor="${i===0?'start':i===4?'end':'middle'}">${dateLabel(date,p)}</text>`;}).join('');
    container.innerHTML=`<svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Illustrative ${p} performance chart, starting at ${usd(values[0])} and ending at ${usd(values.at(-1))}"><defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#8baa62" stop-opacity=".16"/><stop offset="100%" stop-color="#8baa62" stop-opacity="0"/></linearGradient></defs>${grid}<polygon fill="url(#${id})" points="0,${top+h} ${coords} ${w},${top+h}"/><polyline class="chart-line" points="${coords}"/><circle class="chart-point" cx="${w}" cy="${y(values.at(-1))}" r="3"/>${ticks}<line class="chart-guide" hidden x1="0" x2="0" y1="${top}" y2="${top+h}"/><circle class="hover-point" hidden r="3" fill="#d5e9b5"/></svg><div class="chart-tooltip" hidden></div>`;
    const guide=$('.chart-guide',container),point=$('.hover-point',container),tip=$('.chart-tooltip',container);
    container.onpointermove=event=>{const rect=container.getBoundingClientRect();const px=Math.min(Math.max(event.clientX-rect.left,0),w);const i=Math.round(px/w*(values.length-1));const date=new Date(start.getTime()+(end-start)*i/(values.length-1));guide.removeAttribute('hidden');point.removeAttribute('hidden');guide.setAttribute('x1',x(i));guide.setAttribute('x2',x(i));point.setAttribute('cx',x(i));point.setAttribute('cy',y(values[i]));tip.hidden=false;tip.innerHTML=`<small>${dateLabel(date,p,true)} · Synthetic</small>${usd(values[i])}`;tip.style.left=`${Math.max(0,Math.min(x(i)-55,width-145))}px`;tip.style.top=`${Math.max(0,y(values[i])-47)}px`;};
    container.onpointerleave=()=>{guide.setAttribute('hidden','');point.setAttribute('hidden','');tip.hidden=true;};
  }
  function sparkline(h) { const down=change(h)<0; const values=series(100,down?108:91,h.seed,25);const min=Math.min(...values)-1,max=Math.max(...values)+1;return `<svg class="sparkline" viewBox="0 0 76 28" preserveAspectRatio="none" aria-hidden="true"><path stroke="${down?'#bd8b82':'#9bb97e'}" d="${values.map((v,i)=>`${i?'L':'M'}${(i/24*76).toFixed(1)},${(26-(v-min)/(max-min)*23).toFixed(1)}`).join(' ')}"/></svg>`; }
  function renderPortfolio() {
    const [whole,fraction]=usd(total).split('.'); $('#balance').innerHTML=`${whole}<span class="cents">.${fraction}</span>`;
    const values=chartSeries(null,period),delta=values.at(-1)-values[0],pct=delta/values[0]*100;
    $('#performance-change').innerHTML=`<span class="${tone(delta)}">↗ ${signedMoney(delta)}</span><span class="return-pill">${percent(pct)}</span><span class="period-caption">${periodLabels[period]}</span>`;
    $('#portfolio-periods').innerHTML=periods.map(p=>`<button data-period="${p}" class="${p===period?'active':''}" aria-pressed="${p===period}">${p}</button>`).join('');
    renderChart($('#portfolio-chart'),values,period);
    const tech=holdings.filter(h=>['Technology','Semiconductors'].includes(h.sector)).reduce((s,h)=>s+value(h),0)/total*100;
    $('#concentration-copy').innerHTML=`Technology and semiconductors make up <strong>${tech.toFixed(1)}%</strong> of your portfolio. See what that means for your next move.`;
    $('#stats-strip').innerHTML=[
      ['Total gain',signedMoney(gain),percent(gain/(costCents/100)*100),'Price return on invested capital','positive'],
      ["Today’s movement",signedMoney(today),percent(today/(total-today)*100),'Compared with previous demo close',tone(today)],
      ['Invested capital',usd(costCents/100,0),'','Purchase cost · 8 holdings',''],
      ['Available cash',usd(cash,0),`${(cash/total*100).toFixed(1)}%`,'Uninvested · Included in portfolio value',''],
    ].map(([label,number,extra,note,cls])=>`<div class="stat"><div class="stat-label">${label}</div><div class="stat-value ${cls}">${number}${extra?`<small>${extra}</small>`:''}</div><div class="stat-note">${note}</div></div>`).join('');
  }
  function renderHoldings() {
    const query=$('#holding-search').value.trim().toLowerCase();let list=holdings.filter(h=>(h.symbol+' '+h.name+' '+h.short).toLowerCase().includes(query)&&(!gainers||change(h)>0));
    const fns={name:(a,b)=>a.name.localeCompare(b.name),price:(a,b)=>a.price-b.price,day:(a,b)=>change(a)-change(b),value:(a,b)=>value(a)-value(b),return:(a,b)=>growth(a)-growth(b)};
    if(fns[sort])list.sort((a,b)=>fns[sort](a,b)*sortDirection);
    $('#holdings-body').innerHTML=list.length?list.map(h=>`<tr class="asset-row" data-symbol="${h.symbol}"><td><button class="asset-button" data-open="${h.symbol}" aria-label="Explore ${h.name}">${logo(h)}<span><span class="asset-name">${h.symbol}</span><span class="asset-description" style="display:block">${h.short}</span></span></button></td><td>${usd(h.price)}</td><td class="${tone(change(h))}">${percent(change(h))}</td><td>${usd(value(h))}<div class="cell-sub">${h.qty} shares</div></td><td class="${tone(pnl(h))}">${signedMoney(pnl(h))}<div class="cell-sub ${tone(growth(h))}">${percent(growth(h))}</div></td><td class="trend-cell">${sparkline(h)}</td><td>↗</td></tr>`).join(''):'<tr><td colspan="7" class="empty-state">No matching holdings. Try a company name or ticker, or turn off Gainers.</td></tr>';
    $('#holdings-count').textContent=`Showing ${list.length} of ${holdings.length} holdings`;
    $$('th button[data-sort]').forEach(button=>{button.parentElement.setAttribute('aria-sort',button.dataset.sort===sort?(sortDirection===1?'ascending':'descending'):'none');});
  }
  function renderWatchlist() {
    $('#sidebar-watchlist').innerHTML=watchlist.length?watchlist.map(symbol=>{const h=holdings.find(h=>h.symbol===symbol);return `<button class="watch-item" data-open="${symbol}"><span class="watch-dot"></span>${symbol}<small class="${tone(change(h))}">${percent(change(h))}</small></button>`;}).join(''):'<div class="nav-label" style="font-size:8px;letter-spacing:0">Add a company to follow it here.</div>';
  }
  function toggleWatch(symbol) {watchlist=watchlist.includes(symbol)?watchlist.filter(s=>s!==symbol):[...watchlist,symbol];try{localStorage.setItem('still.watchlist',JSON.stringify(watchlist));}catch{toast('Watchlist updated for this session; browser storage is unavailable.');}renderWatchlist();renderDiscover();if(selected&&$('#detail-dialog').open)renderDetail();}
  function renderDiscover() {
    const q=$('#discover-search').value.trim().toLowerCase();const list=holdings.filter(h=>`${h.symbol} ${h.name} ${h.sector}`.toLowerCase().includes(q)&&(discoveryFilter==='all'||discoveryFilter==='positive'&&change(h)>0||discoveryFilter==='watchlist'&&watchlist.includes(h.symbol)||h.sector===discoveryFilter));
    $('#company-grid').innerHTML=list.length?list.map(h=>`<article class="company-card"><div class="company-card-top">${logo(h)}<button data-open="${h.symbol}" aria-label="Explore ${h.name}"><div class="asset-name">${h.name}</div><div class="asset-description">${h.symbol} · USD</div></button><button class="watch-toggle" data-watch="${h.symbol}" aria-label="${watchlist.includes(h.symbol)?'Remove':'Add'} ${h.symbol} ${watchlist.includes(h.symbol)?'from':'to'} watchlist" aria-pressed="${watchlist.includes(h.symbol)}">${watchlist.includes(h.symbol)?'★':'☆'}</button></div><div class="company-price">${usd(h.price)}</div><span class="${tone(change(h))}" style="font-size:10px">${percent(change(h))} today</span>${sparkline(h)}<div class="company-card-footer"><span>${h.sector}</span><button data-open="${h.symbol}" aria-label="View ${h.name} details">Explore ↗</button></div></article>`).join(''):'<div class="no-results">No companies match these filters. Try All companies or a different search.</div>';
  }
  function navigate(next) {
    view=next;const names={portfolio:'Overview',discover:'Discover',research:'Research'};
    const titles={portfolio:['Your money. In focus.','The big picture, without the noise.'],discover:['A world of possibilities.','A thoughtful place to find your next idea.'],research:['Go a little deeper.','Good decisions begin with better questions.']};
    ['portfolio','discover','research'].forEach(v=>$(`#${v}-view`).hidden=v!==next);
    $$('.nav-item').forEach(b=>{b.classList.toggle('active',b.dataset.view===next);if(b.dataset.view===next)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
    $('#breadcrumb').textContent=names[next];$('#page-title').textContent=titles[next][0];$('#page-subtitle').textContent=titles[next][1];
    if(next==='portfolio')renderPortfolio();if(next==='discover')renderDiscover();
    if(location.hash!==`#${next}`)history.replaceState(null,'',`#${next}`);
  }
  function openDetail(symbol) {selected=holdings.find(h=>h.symbol===symbol);detailPeriod='YTD';openDialog('#detail-dialog');renderDetail();}
  function renderDetail() {
    const h=selected;
    $('#detail-content').innerHTML=`<div class="drawer-heading">${logo(h)}<div><h2 id="detail-name">${h.name}</h2><span>${h.symbol} · Synthetic snapshot</span></div><button class="icon-button close-dialog" aria-label="Close stock details">×</button></div><div class="detail-main"><div class="detail-sector">${h.sector} · USD</div><div class="detail-price">${usd(h.price)}</div><div class="detail-day ${tone(change(h))}">${signedMoney(h.price-h.previous)} (${percent(change(h))}) today</div><div class="periods" id="detail-periods">${periods.map(p=>`<button data-detail-period="${p}" aria-pressed="${p===detailPeriod}" class="${p===detailPeriod?'active':''}">${p}</button>`).join('')}</div><div id="detail-chart" class="chart-wrap"></div><div class="detail-stats"><div class="detail-stat"><span>Your position</span><strong>${usd(value(h))}</strong></div><div class="detail-stat"><span>Shares owned</span><strong>${h.qty}</strong></div><div class="detail-stat"><span>Average purchase price</span><strong>${usd(h.cost)}</strong></div><div class="detail-stat"><span>Total price return</span><strong class="positive">${percent(growth(h))}</strong></div><div class="detail-stat"><span>Unrealized gain</span><strong class="positive">${signedMoney(pnl(h))}</strong></div><div class="detail-stat"><span>Portfolio weight</span><strong>${(value(h)/total*100).toFixed(1)}%</strong></div></div><div class="purchase-block"><h3>Your purchase history</h3><div class="purchase-row"><div>Buy · ${h.qty} shares<small>${h.date} · Synthetic opening purchase</small></div><div>${usd(h.cost)}<small>${usd(h.qty*h.cost)} total</small></div></div></div><p class="detail-note">Illustrative prices and history, as of Oct 21, 2026. Price return excludes dividends, fees, taxes and FX. This is a demo position, not an IBKR record.</p><button class="primary-button" data-watch="${h.symbol}">${watchlist.includes(h.symbol)?'★ Following · Remove from watchlist':'☆ Add to watchlist'}</button></div>`;
    renderChart($('#detail-chart'),chartSeries(h,detailPeriod),detailPeriod);
  }
  function research(type) {
    // All prose below is generated from local synthetic data and fixed templates.
    // Free text is classified with simple rules, never rendered as HTML.
    closeDialogs();openDialog('#assistant-dialog');let title,body,evidence;
    const semis=holdings.filter(h=>h.sector==='Semiconductors'),semiValue=semis.reduce((s,h)=>s+value(h),0);
    if(type==='semiconductor') {
      const loss=semiValue*.2;
      title='What if semiconductor stocks fell 20%?';
      body=`<p class="answer-text">Your direct semiconductor holdings are NVIDIA and Taiwan Semiconductor. Together, they account for <strong>${(semiValue/total*100).toFixed(1)}%</strong> of your demo portfolio, including cash.</p><div class="answer-metric"><strong class="negative">−${usd(loss)}</strong><span>Illustrative portfolio impact · ${percent(-loss/total*100)}</span></div><p class="answer-text">A uniform 20% price decline in those two positions would bring your portfolio to <strong>${usd(total-loss)}</strong>, assuming every other holding and cash remained unchanged.</p>${semis.map(h=>`<div class="exposure-row"><span>${h.symbol}</span><span class="negative">−${usd(value(h)*.2)}</span></div>`).join('')}<div class="example-notice">Direct holdings only. VTI may hold semiconductor stocks, but this demo has no ETF look-through data. This is a mechanical shock scenario, not a forecast or a complete estimate of exposure.</div>`;
      evidence=`<p>Inputs: ${semis.map(h=>`${h.symbol}: ${h.qty} shares × ${usd(h.price)} = ${usd(value(h))}`).join('; ')}.</p><p>Calculation: direct semiconductor value (${usd(semiValue)}) × 20%. Impact percentage divides the loss by portfolio value including cash (${usd(total)}).</p>`;
    } else if(type==='performance') {
      const ranked=[...holdings].sort((a,b)=>growth(b)-growth(a)),best=ranked[0];
      title='Which holding has grown the most?';
      body=`<p class="answer-text"><strong>${best.name}</strong> has the highest percentage price return since the synthetic purchase date. That differs from identifying the largest dollar position.</p><div class="answer-metric"><strong>${percent(growth(best))}</strong><span>${best.symbol} · ${signedMoney(pnl(best))} unrealized gain</span></div>${ranked.slice(0,4).map(h=>`<div class="exposure-row"><span>${h.name}</span><span class="positive">${percent(growth(h))}</span></div><div class="exposure-bar"><span style="width:${growth(h)/growth(best)*100}%"></span></div>`).join('')}<div class="example-notice">Price returns exclude dividends, fees, taxes and FX. Synthetic transactions contain one purchase per holding and no sales.</div>`;
      evidence=`<p>Rank holdings by (current price ÷ average purchase price − 1) × 100.</p><p>${best.symbol}: (${usd(best.price)} ÷ ${usd(best.cost)} − 1) × 100 = ${percent(growth(best))}. Dollar gain: ${best.qty} × (${usd(best.price)} − ${usd(best.cost)}).</p>`;
    } else if(type==='unsupported') {
      title='Let’s keep the answer grounded.';
      body='<p class="answer-text">This prototype can calculate concentration, a 20% semiconductor shock, and price growth from its synthetic holdings. It cannot retrieve news, give recommendations, or answer arbitrary research questions yet.</p><div class="research-prompts"><button data-question="exposure">Show my concentration <span>↗</span></button><button data-question="semiconductor">Model a semiconductor shock <span>↗</span></button><button data-question="performance">Compare my holdings’ growth <span>↗</span></button></div>';
      evidence='<p>No external sources or models were queried. This demo uses only its eight synthetic positions and cash balance.</p>';
    } else {
      const grouped={};holdings.forEach(h=>grouped[h.sector]=(grouped[h.sector]||0)+value(h));grouped.Cash=cash;const groups=Object.entries(grouped).sort((a,b)=>b[1]-a[1]);
      const tech=holdings.filter(h=>['Technology','Semiconductors'].includes(h.sector)).reduce((s,h)=>s+value(h),0);
      title='Where am I most concentrated?';
      body=`<p class="answer-text">Your largest combined exposure is technology and semiconductors. Together, they represent <strong>${(tech/total*100).toFixed(1)}%</strong> of portfolio value, including cash.</p><div class="answer-metric"><strong>${usd(tech,0)}</strong><span>In direct technology and semiconductor holdings</span></div>${groups.map(([name,v])=>`<div class="exposure-row"><span>${name}</span><span>${(v/total*100).toFixed(1)}%</span></div><div class="exposure-bar"><span style="width:${v/total*100}%"></span></div>`).join('')}<div class="example-notice">Categories are explicit demo classifications. VTI is shown as a broad market ETF without looking through to its underlying holdings. Sector weighting alone does not measure total investment risk.</div>`;
      evidence=`<p>For each category, sum shares × current synthetic price, then divide by total portfolio value including cash (${usd(total)}).</p><p>Technology includes MSFT, AAPL and GOOGL; semiconductors includes NVDA and TSM. AMZN is classified as consumer discretionary. Categories describe these demo holdings, not a verified classification feed.</p>`;
    }
    $('#assistant-content').innerHTML=`<div class="answer-label">YOUR QUESTION</div><h3 class="assistant-question">${title}</h3><div class="answer-label">A VIEW FROM YOUR DEMO DATA</div>${body}<details class="evidence"><summary>See the inputs & calculation</summary>${evidence}<p>Source: local synthetic dataset · Oct 21, 2026. No live market data.</p></details>`;
    $('#assistant-input').value='';
  }
  function openSearch() {closeDialogs();openDialog('#search-dialog');$('#command-input').value='';renderCommands();$('#command-input').focus();}
  function renderCommands() {
    const q=$('#command-input').value.trim().toLowerCase();
    commandActions=[...['portfolio','discover','research'].map(v=>({label:({portfolio:'Portfolio overview',discover:'Discover companies',research:'Research workspace'})[v],sub:'Go to',run:()=>navigate(v)})),...holdings.map(h=>({label:`${h.symbol} · ${h.name}`,sub:'Open holding',run:()=>openDetail(h.symbol)})),{label:'Semiconductor shock scenario',sub:'Explore',run:()=>research('semiconductor')}].filter(a=>a.label.toLowerCase().includes(q));commandIndex=0;renderCommandList();
  }
  function renderCommandList() {$('#command-results').innerHTML=commandActions.length?commandActions.map((a,i)=>`<button class="command-result ${i===commandIndex?'selected':''}" data-command="${i}"><span>${a.label}</span><small>${a.sub} ↵</small></button>`).join(''):'<div class="empty-state">Nothing found. Try NVDA, Microsoft, or Discover.</div>';}
  function runCommand(i){const action=commandActions[i];if(action){$('#search-dialog').close();action.run();}}
  document.addEventListener('click',event=>{
    const button=event.target.closest('button');
    if(button?.dataset.view)navigate(button.dataset.view);
    if(button?.dataset.open)openDetail(button.dataset.open);
    if(!button){const row=event.target.closest('.asset-row');if(row)openDetail(row.dataset.symbol);}
    if(button?.dataset.period){period=button.dataset.period;renderPortfolio();}
    if(button?.dataset.detailPeriod){detailPeriod=button.dataset.detailPeriod;renderDetail();}
    if(button?.dataset.watch)toggleWatch(button.dataset.watch);
    if(button?.dataset.question)research(button.dataset.question);
    if(button?.dataset.filter){discoveryFilter=button.dataset.filter;$$('[data-filter]').forEach(b=>b.classList.toggle('active',b===button));renderDiscover();}
    if(button?.dataset.sort){sortDirection=sort===button.dataset.sort?-sortDirection:1;sort=button.dataset.sort;renderHoldings();}
    if(button?.dataset.command!==undefined)runCommand(Number(button.dataset.command));
    if(button?.classList.contains('close-dialog'))button.closest('dialog').close();
  });
  ['#search-button','#sidebar-search','#add-watch'].forEach(id=>$(id).onclick=openSearch);
  ['#privacy-button','#workspace-info','#profile-info'].forEach(id=>$(id).onclick=()=>openDialog('#info-dialog'));
  $('#ask-top').onclick=()=>research('exposure');$('#explore-exposure').onclick=()=>research('exposure');$('#question-semiconductor').onclick=()=>research('semiconductor');
  $('#holdings-filter').onclick=()=>{gainers=!gainers;$('#holdings-filter').setAttribute('aria-pressed',String(gainers));renderHoldings();};
  $('#holding-search').oninput=renderHoldings;$('#discover-search').oninput=renderDiscover;$('#command-input').oninput=renderCommands;
  $('#command-input').onkeydown=event=>{if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();if(commandActions.length){commandIndex=(commandIndex+(event.key==='ArrowDown'?1:-1)+commandActions.length)%commandActions.length;renderCommandList();$('.command-result.selected')?.scrollIntoView({block:'nearest'});}}if(event.key==='Enter'){event.preventDefault();runCommand(commandIndex);}};
  $('#assistant-form').onsubmit=event=>{event.preventDefault();const text=$('#assistant-input').value.trim().toLowerCase();if(!text)return;if(/semiconductor|shock|20%|nvidia.*fall/.test(text))research('semiconductor');else if(/grow|growth|perform|best|gain/.test(text))research('performance');else if(/expos|concentr|sector|divers/.test(text))research('exposure');else research('unsupported');};
  document.addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();openSearch();return;}if($('dialog[open]')||/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)||event.metaKey||event.ctrlKey||event.altKey)return;if(event.key==='/'){event.preventDefault();navigate('portfolio');$('#holding-search').focus();}if(event.key==='1')navigate('portfolio');if(event.key==='2')navigate('discover');});
  $$('dialog').forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target===dialog){const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();}}));
  let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(view==='portfolio')renderPortfolio();if($('#detail-dialog').open)renderDetail();},100);});
  icons();renderPortfolio();renderHoldings();renderWatchlist();renderDiscover();navigate(['portfolio','discover','research'].includes(location.hash.slice(1))?location.hash.slice(1):'portfolio');
})();
