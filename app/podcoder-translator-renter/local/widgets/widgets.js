/* Reef Widgets — reusable, data-driven, category-agnostic animated chart components.
   Plain JS + SVG. Each widget: ReefWidgets.<type>(cardEl, config) renders + animates config.
   Formats: 'percent' | 'currency' | 'count' | 'number' (with unit) | 'level' (Low/Medium/High) | 'tag' (Quiet/Emerging/Dominant) */
(function(){
const SCALES = { level:['Low','Medium','High'], tag:['Quiet','Emerging','Dominant'] };
const isQual = f => f==='level' || f==='tag';
const ease = t => 1 - Math.pow(1-t,3);
const esc = s => String(s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function tween(dur, fn, delay=0){
  const start = performance.now()+delay;
  return new Promise(res=>{
    function step(now){
      const t = Math.min(1, Math.max(0,(now-start)/dur));
      fn(ease(t), t);
      if(t<1) requestAnimationFrame(step); else res();
    }
    requestAnimationFrame(step);
  });
}
function decimalsOf(v){ const s=String(v); return s.includes('.') ? s.split('.')[1].length : 0; }
function fmt(v, format, o={}){
  const d = o.decimals ?? 0;
  const n = Number(v).toLocaleString('en-US',{minimumFractionDigits:d, maximumFractionDigits:d});
  switch(format){
    case 'percent': return n+'%';
    case 'currency': return '$'+n;
    case 'number': return n+(o.unit? (o.unit.length<=2?'':' ')+o.unit : '');
    default: return n;
  }
}
function short(v, format){
  let s = Math.abs(v)>=1000 ? (v/1000).toFixed(v%1000?1:0).replace('.0','')+'K' : String(Math.round(v*10)/10);
  return format==='currency' ? '$'+s : format==='percent' ? s+'%' : s;
}
function scaleIdx(word, format){ return Math.max(0, SCALES[format].indexOf(word)); }
/* Count a number up, or for qualitative values flick up through the scale words, landing on the target. */
function countUp(el, value, format, opts={}, dur=1300, delay=0){
  if(isQual(format)){
    const sc = SCALES[format], target = scaleIdx(value, format);
    el.classList.add('q');
    return tween(dur, p=>{ const i = Math.min(target, Math.floor(p*(target+1)*1.15)); el.textContent = p>=1? value : sc[i]; }, delay);
  }
  const dec = opts.decimals ?? decimalsOf(value);
  return tween(dur, p=>{ el.textContent = fmt(value*p, format, {...opts, decimals:dec}); }, delay);
}
function deltaHTML(d){
  if(!d) return '';
  const dir = d.dir || (/^[-−↓]/.test(d.text) ? 'down' : /^[+↑]/.test(d.text) ? 'up' : 'flat');
  return `<div class="delta ${dir}">${esc(d.text)}${d.label?`<small>${esc(d.label)}</small>`:''}</div>`;
}
/* fill: a .bar (0–100) or a .pips (qualitative) */
function meterHTML(format){ return isQual(format) ? `<div class="pips"><i></i><i></i><i></i></div>` : `<div class="bar"><i></i></div>`; }
function fillMeter(el, value, format, max=100, dur=1200, delay=0){
  if(isQual(format)){
    const n = scaleIdx(value, format)+1, pips=[...el.querySelectorAll('i')];
    return tween(dur, p=>pips.forEach((pi,i)=>pi.classList.toggle('on', i < Math.ceil(p*n))), delay);
  }
  const i = el.querySelector('i');
  return tween(dur, p=>{ i.style.width = (Math.min(1,value/max)*100*p)+'%'; }, delay);
}
const DEFS = `<svg width="0" height="0" style="position:absolute"><defs>
  <linearGradient id="gAqua" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#bff8fb"/><stop offset="1" stop-color="#2fb9cb"/></linearGradient>
  <linearGradient id="gArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8ff0f6" stop-opacity=".55"/><stop offset="1" stop-color="#8ff0f6" stop-opacity="0"/></linearGradient>
  <linearGradient id="gBar" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c8fbfd"/><stop offset="1" stop-color="#2aa9bd" stop-opacity=".75"/></linearGradient>
  </defs></svg>`;

/* Ring: numeric -> sweeping arc; qualitative -> 3 segments that light up in turn */
function ringHTML(size=120, format){
  const r=46, c=2*Math.PI*r;
  if(isQual(format)){
    const seg = c/3, gap=10;
    return `<svg viewBox="0 0 120 120">${[0,1,2].map(i=>`<circle cx="60" cy="60" r="${r}" fill="none" stroke-width="10" class="track"
      stroke-dasharray="${seg-gap} ${c}" stroke-dashoffset="${-i*seg}"/><circle cx="60" cy="60" r="${r}" fill="none" stroke-width="10" class="arc seg"
      stroke-dasharray="0 ${c}" stroke-dashoffset="${-i*seg}" data-len="${seg-gap}"/>`).join('')}</svg>`;
  }
  return `<svg viewBox="0 0 120 120"><circle cx="60" cy="60" r="${r}" fill="none" stroke-width="10" class="track"/>
    <circle cx="60" cy="60" r="${r}" fill="none" stroke-width="10" class="arc main" stroke-dasharray="0 ${c}"/></svg>`;
}
function sweepRing(root, value, format, dur=1400){
  const r=46, c=2*Math.PI*r;
  if(isQual(format)){
    const n=scaleIdx(value,format)+1, segs=[...root.querySelectorAll('.seg')];
    return tween(dur, p=>segs.forEach((s,i)=>{ const L=+s.dataset.len; const f=Math.max(0,Math.min(1,p*n-i)); s.setAttribute('stroke-dasharray', `${i<n?L*f:0} ${c}`); }));
  }
  const arc=root.querySelector('.main');
  return tween(dur, p=>arc.setAttribute('stroke-dasharray', `${c*Math.min(1,value/100)*p} ${c}`));
}

/* ---------- Widget 1: ring gauge + labeled metric bars ---------- */
function ringMetrics(body, cfg){
  const f = cfg.format;
  body.innerHTML = `<div class="w1 fadein"><div class="ring">${ringHTML(118,f)}<div class="center"><div class="big"></div><div class="word">${esc(cfg.ring.word||'')}</div></div></div>
    <div class="rows">${cfg.rows.map(r=>`<div class="row"><span>${esc(r.label)}</span><span class="v"></span>${meterHTML(f)}</div>`).join('')}</div></div>`;
  sweepRing(body, cfg.ring.value, f);
  const big = body.querySelector('.big');
  if(isQual(f)){ big.classList.add('q'); countUp(big, cfg.ring.value, f); body.querySelector('.word').textContent = cfg.ring.word||''; }
  else countUp(big, cfg.ring.value, f);
  body.querySelectorAll('.row').forEach((row,i)=>{
    const r=cfg.rows[i];
    countUp(row.querySelector('.v'), r.value, f, {}, 1100, 120*i);
    fillMeter(row.querySelector('.bar,.pips'), r.value, f, 100, 1100, 120*i);
  });
}

/* chart helpers */
function yScale(series, format){
  if(isQual(format)) return {min:-0.25, max:2.25, ticks:[0,1,2], label:i=>SCALES[format][i], v:x=>scaleIdx(x,format)};
  const mx = Math.max(...series); const step = niceStep(mx/4); const max = step*Math.ceil(mx/step);
  const ticks=[]; for(let t=0;t<=max+1e-9;t+=step) ticks.push(t);
  return {min:0, max, ticks, label:t=>short(t,format), v:x=>x};
}
function niceStep(x){ const p=Math.pow(10,Math.floor(Math.log10(x||1))); const m=x/p; return (m<=1?1:m<=2?2:m<=2.5?2.5:m<=5?5:10)*p; }

/* ---------- Widget 2: monthly line/area chart ---------- */
function lineChart(body, cfg){
  const f=cfg.format, W=320, H=150, L=isQual(f)?62:36, R=8, T=10, B=20;
  const ys=yScale(cfg.series,f), n=cfg.series.length;
  const X=i=>L+(W-L-R)*i/(n-1), Y=v=>T+(H-T-B)*(1-(v-ys.min)/(ys.max-ys.min));
  const pts=cfg.series.map((v,i)=>[X(i),Y(ys.v(v))]);
  const d=pts.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ');
  const area=d+` L${X(n-1)} ${H-B} L${X(0)} ${H-B} Z`;
  body.innerHTML = `<div class="fadein"><div class="chead"><div><div class="lbl">${esc(cfg.headlineLabel)}</div><div class="big-num"></div></div>${deltaHTML(cfg.delta)}</div>
   <svg class="chart" viewBox="0 0 ${W} ${H}">
    <g class="grid">${ys.ticks.map(t=>`<line x1="${L}" x2="${W-R}" y1="${Y(t)}" y2="${Y(t)}"/><text x="${L-6}" y="${Y(t)+3}" text-anchor="end">${esc(ys.label(t))}</text>`).join('')}</g>
    ${cfg.labels.map((m,i)=>`<text x="${X(i)}" y="${H-5}" text-anchor="middle">${esc(m)}</text>`).join('')}
    <path class="area" d="${area}" fill="url(#gArea)" opacity="0"/>
    <path class="ln" d="${d}" fill="none" stroke="#bff8fb" stroke-width="2.4" stroke-linejoin="round" style="filter:drop-shadow(0 0 4px rgba(140,240,248,.9))"/>
    ${pts.map(p=>`<circle class="pt" cx="${p[0]}" cy="${p[1]}" r="3.4" fill="#e9feff" opacity="0"/>`).join('')}
   </svg></div>`;
  const ln=body.querySelector('.ln'), len=ln.getTotalLength(); ln.style.strokeDasharray=len; ln.style.strokeDashoffset=len;
  const area_=body.querySelector('.area'), dots=[...body.querySelectorAll('.pt')];
  tween(1500, p=>{ ln.style.strokeDashoffset=len*(1-p); area_.setAttribute('opacity',p); dots.forEach((c,i)=>c.setAttribute('opacity', p*(n-1)>=i-0.05?1:0)); });
  countUp(body.querySelector('.big-num'), cfg.headline, f, cfg.opts||{});
}

/* ---------- Widget 3: monthly bar chart + side stats ---------- */
function barChart(body, cfg){
  const f=cfg.format, W=320, H=120, L=isQual(f)?62:36, R=4, T=8, B=20;
  const ys=yScale(cfg.series,f), n=cfg.series.length, slot=(W-L-R)/n, bw=slot*0.56;
  const Y=v=>T+(H-T-B)*(1-(v-ys.min)/(ys.max-ys.min));
  body.innerHTML = `<div class="w3 fadein"><div class="left"><div class="chead"><div><div class="lbl">${esc(cfg.headlineLabel)}</div><div class="big-num"></div></div>${deltaHTML(cfg.delta)}</div>
   <svg class="chart" viewBox="0 0 ${W} ${H}">
    <g class="grid">${ys.ticks.map(t=>`<line x1="${L}" x2="${W-R}" y1="${Y(t)}" y2="${Y(t)}"/><text x="${L-6}" y="${Y(t)+3}" text-anchor="end">${esc(ys.label(t))}</text>`).join('')}</g>
    ${cfg.series.map((v,i)=>{ const x=L+slot*i+(slot-bw)/2; const tv = isQual(f)? ys.v(v)+0.35 : v;
      return `<rect class="b" x="${x}" width="${bw}" rx="3" y="${H-B}" height="0" data-h="${(H-B)-Y(tv)}" fill="url(#gBar)"/>
      <text x="${x+bw/2}" y="${H-5}" text-anchor="middle">${esc(cfg.labels[i])}</text>`; }).join('')}
   </svg></div>
   <div class="side">${cfg.side.map(s=>`<div><span>${esc(s.label)}</span><b></b></div>`).join('')}</div></div>`;
  const bars=[...body.querySelectorAll('.b')];
  bars.forEach((b,i)=>tween(900, p=>{ const h=+b.dataset.h*p; b.setAttribute('height',h); b.setAttribute('y',H-B-h); }, i*110));
  countUp(body.querySelector('.big-num'), cfg.headline, f);
  body.querySelectorAll('.side b').forEach((b,i)=>countUp(b, cfg.side[i].value, cfg.side[i].format||f, {}, 1200, 200+i*120));
}

/* ---------- Widget 4: goal ring (On Track) + amount + goal + progress ---------- */
function goalRing(body, cfg){
  const f=cfg.format, q=isQual(f);
  body.innerHTML = `<div class="fadein"><div class="w4"><div class="ring">${ringHTML(120,q?f:'percent')}<div class="center"><div class="big"></div><div class="word">${esc(cfg.status)}</div></div></div>
    <div class="info"><div class="line"><div><div class="lbl">${esc(cfg.headlineLabel)}</div><div class="big-num"></div></div>${deltaHTML(cfg.delta)}</div>
    <div><div class="lbl">${esc(cfg.goalLabel)}</div><div class="big-num" style="font-size:22px"></div></div></div></div>
    <div class="goalbar"><div class="lab"><span>${esc(cfg.progressLabel)}</span><span class="pv"></span></div>${meterHTML(q?f:'percent')}
    ${q?`<div class="stages">${SCALES[f].map(s=>`<span>${s}</span>`).join('')}</div>`:''}</div></div>`;
  const prog = q? cfg.progress : cfg.progress;
  sweepRing(body, prog, q?f:'percent');
  countUp(body.querySelector('.big'), prog, q?f:'percent');
  const nums=body.querySelectorAll('.big-num');
  countUp(nums[0], cfg.headline, cfg.valueFormat||f, cfg.opts||{});
  countUp(nums[1], cfg.goal, cfg.valueFormat||f, cfg.opts||{}, 1300, 150);
  countUp(body.querySelector('.pv'), prog, q?f:'percent', {}, 1300, 200);
  fillMeter(body.querySelector('.goalbar .bar,.goalbar .pips'), prog, q?f:'percent', 100, 1300, 200);
  if(q) setTimeout(()=>{ const i=scaleIdx(prog,f); body.querySelectorAll('.stages span').forEach((s,k)=>s.classList.toggle('on',k<=i)); }, 1200);
}

/* ---------- Widget 5: score plaque + 4 stat tiles ---------- */
function scorePlaque(body, cfg){
  body.innerHTML = `<div class="fadein"><div class="plaque"><div class="ttl">${esc(cfg.plaqueTitle)}</div><div class="score"></div>
    <div class="w">${esc(cfg.word||'')}</div><div class="sub">${esc(cfg.sub||'')}</div></div>
    <div class="tiles">${cfg.tiles.map(t=>`<div class="tile"><div class="ic">${t.icon}</div><div class="tl">${esc(t.label)}</div><div class="tv"></div>${deltaHTML(t.delta)}</div>`).join('')}</div></div>`;
  countUp(body.querySelector('.score'), cfg.score, cfg.format, cfg.opts||{}, 1500);
  body.querySelectorAll('.tile').forEach((el,i)=>{ const t=cfg.tiles[i]; el.style.animation=`fade .5s ${0.12*i}s ease both`; countUp(el.querySelector('.tv'), t.value, t.format||cfg.format, t.opts||{}, 1200, 150*i); });
}

/* ---------- Widget 6: horizontal progress + 4 icon sub-stats ---------- */
function progressStats(body, cfg){
  const f=cfg.format;
  body.innerHTML = `<div class="w6 fadein"><div class="lbl" style="margin-bottom:6px">${esc(cfg.barLabel||'')}</div><div class="top">${meterHTML(f)}<div class="big-num"></div></div>
    <div class="stats">${cfg.stats.map(s=>`<div class="stat"><div class="ic">${s.icon}</div><div><div class="sl">${esc(s.label)}</div><div class="sv"></div></div></div>`).join('')}</div></div>`;
  fillMeter(body.querySelector('.top .bar,.top .pips'), cfg.value, f, 100, 1500);
  countUp(body.querySelector('.top .big-num'), cfg.value, f, {}, 1500);
  body.querySelectorAll('.stat').forEach((el,i)=>{ const s=cfg.stats[i]; el.style.animation=`fade .5s ${0.12*i+.2}s ease both`; countUp(el.querySelector('.sv'), s.value, s.format||f, s.opts||{}, 1200, 200+120*i); });
}

/* ---------- Widget 7: quote card (text only) with pearl-in-shell motif ---------- */
const PEARL = `<svg class="pearl" viewBox="0 0 120 110" aria-hidden="true">
  <defs><radialGradient id="pg" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#fff"/><stop offset=".55" stop-color="#f3e9ff"/><stop offset="1" stop-color="#bcd6e0"/></radialGradient>
  <linearGradient id="sg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffe3cf"/><stop offset="1" stop-color="#e6a98d"/></linearGradient></defs>
  <path d="M8 58 Q12 8 60 6 Q108 8 112 58 Q86 46 60 48 Q34 46 8 58Z" fill="url(#sg)" stroke="#fff3ea" stroke-width="1.2"/>
  ${[18,32,46,60,74,88,102].map(x=>`<path d="M60 48 L${x} ${x<60?14+ (60-x)/3: 14+(x-60)/3}" stroke="#d48f74" stroke-width="1" opacity=".7"/>`).join('')}
  <path d="M8 62 Q60 50 112 62 Q104 100 60 104 Q16 100 8 62Z" fill="url(#sg)" stroke="#fff3ea" stroke-width="1.2"/>
  <circle cx="60" cy="66" r="15" fill="url(#pg)" class="pearl-orb"><animate attributeName="r" values="15;16.2;15" dur="3s" repeatCount="indefinite"/></circle>
  <circle cx="55" cy="61" r="4" fill="#fff" opacity=".9"/></svg>`;
function quoteCard(body, cfg){
  body.innerHTML = `<div class="w7 fadein">${PEARL}<div><blockquote>${esc(cfg.quote)}</blockquote><div class="tag">${esc(cfg.tag||'')}</div></div></div>`;
}

/* ---------- card shell + auto-cycler ---------- */
const SHELL = `<svg class="shell" viewBox="0 0 32 32" aria-hidden="true"><defs><linearGradient id="shg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff1e4"/><stop offset="1" stop-color="#eeb196"/></linearGradient></defs>
  <path d="M16 28 L4 13 Q4 4 16 3 Q28 4 28 13 Z" fill="url(#shg)" stroke="#fff" stroke-width=".8"/>
  ${[5.5,9,12.5,16,19.5,23,26.5].map(x=>`<path d="M16 27 L${x} ${x===16?4:Math.abs(16-x)>9?11:6}" stroke="#c97c62" stroke-width=".8"/>`).join('')}
  <path d="M12 27 L16 30 L20 27 Z" fill="#eeb196"/></svg>`;
const WAVE = `<svg class="wave" viewBox="0 0 200 14" preserveAspectRatio="none"><path d="M0 8 Q12 1 25 8 T50 8 T75 8 T100 8 T125 8 T150 8 T175 8 T200 8" fill="none" stroke="rgba(230,253,255,.75)" stroke-width="1.4"/></svg>`;
const TYPES = {ringMetrics, lineChart, barChart, goalRing, scorePlaque, progressStats, quoteCard};

function mount(el, type, datasets, opts={}){
  el.classList.add('card');
  el.innerHTML = `${WAVE}<header>${SHELL}<h3><span class="n"></span><span class="t"></span></h3><span class="cat"></span></header>
    <div class="body"></div><p class="caption"></p><div class="dots">${datasets.map(()=>'<b></b>').join('')}</div><span class="fake">Example data</span>`;
  let i = 0; const body=el.querySelector('.body');
  function show(){
    const cfg = datasets[i];
    el.querySelector('.n').textContent = cfg.badge + '.';
    el.querySelector('.t').textContent = cfg.title;
    el.querySelector('.cat').textContent = cfg.category;
    const cap = el.querySelector('.caption'); cap.textContent = cfg.caption||''; cap.classList.remove('fadein'); void cap.offsetWidth; cap.classList.add('fadein');
    el.querySelectorAll('.dots b').forEach((b,k)=>b.classList.toggle('on',k===i));
    TYPES[type](body, cfg);
  }
  const api = { next(){ i=(i+1)%datasets.length; show(); }, show };
  show();
  return api;
}
window.ReefWidgets = { mount, ...TYPES, fmt, DEFS };
})();
