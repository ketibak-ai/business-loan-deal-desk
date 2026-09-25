/* Borrower's Deal Desk: page UI. All math lives in engine.js (window.DealEngine). */
"use strict";
const {PRODUCTS, INDUSTRIES, COLLATERAL, INDEXES, PREPAY, EXAMPLE, BLANK, clone,
  money, moneyShort, pct, bps, x2, indexRate, schedule, capacity, eligibility, run, levers, offerSchedule} = DealEngine;

const STORE_KEY = 'borrower-deal-desk-v1';
let S = load() || clone(EXAMPLE);
let activeTab = 'cost';

function load(){try{const t=localStorage.getItem(STORE_KEY);if(!t)return null;const o=JSON.parse(t);
  if(!o||!o.loan||!o.biz)return null;
  for(const k of ['loan','biz','mkt','assume','lev']) o[k]=Object.assign({},EXAMPLE[k],o[k]);
  if(!Array.isArray(o.offers)||o.offers.length!==3) o.offers=clone(EXAMPLE.offers);
  return o;}catch(e){return null}}
function save(){try{localStorage.setItem(STORE_KEY,JSON.stringify(S))}catch(e){}}
const $ = (sel,root=document)=>root.querySelector(sel);
const esc = s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/* ============================================================
   INPUT FORMS
   ============================================================ */
const opt=o=>Object.entries(o).map(([k,v])=>[k,Array.isArray(v)?v[0]:(v.label||v)]);
const isRev=s=>!!PRODUCTS[s.loan.product].rev, isMca=s=>!!PRODUCTS[s.loan.product].mca;
const GROUPS=[
  {title:'The loan you are offered',lede:'Copy these from the term sheet or quote.',fields:[
    {p:'loan.product',label:'Loan type',type:'select',options:opt(PRODUCTS),wide:true},
    {blurb:true},
    {p:'loan.lender',label:'Lender',type:'text',wide:true},
    {p:'loan.amount',label:'Amount (or line size)',type:'money',step:5000},
    {p:'loan.termY',label:'Term',type:'num',suf:'yrs',step:1,show:s=>!isMca(s),hint:'When it must be repaid'},
    {p:'loan.amortY',label:'Payment schedule',type:'num',suf:'yrs',step:1,show:s=>!isRev(s)&&!isMca(s),hint:'Longer than the term means a balloon'},
    {p:'loan.index',label:'Rate index',type:'select',options:Object.entries(INDEXES),show:s=>!isMca(s)},
    {p:'loan.spreadBps',label:'Spread over index',type:'num',suf:'bps',step:5,show:s=>!isMca(s),hint:'100 bps = 1%'},
    {p:'loan.utilPct',label:'Expected use',type:'num',suf:'%',step:5,show:isRev,hint:'Average share you will draw'},
    {p:'loan.unusedBps',label:'Unused fee',type:'num',suf:'bps',step:5,show:isRev},
    {p:'loan.mcaFactor',label:'Factor rate',type:'num',step:.01,show:isMca,hint:'1.35 = repay $1.35 per $1'},
    {p:'loan.mcaMonths',label:'Payback period',type:'num',suf:'mo',step:1,show:isMca},
    {p:'loan.origPct',label:'Origination fee',type:'num',suf:'%',step:.05},
    {p:'loan.closingCost',label:'Closing costs',type:'money',step:500,hint:'Legal, appraisal, filing'},
    {p:'loan.annualFee',label:'Annual fee',type:'money',step:100,show:s=>!isMca(s)},
    {p:'loan.sbaFeePct',label:'SBA guarantee fee',type:'num',suf:'%',step:.05,show:s=>/sba/.test(s.loan.product),hint:'Check the current SBA schedule'},
    {p:'loan.prepay',label:'Prepayment penalty',type:'select',options:Object.entries(PREPAY),show:s=>!isMca(s)},
    {p:'loan.covDSCR',label:'Min. DSCR covenant',type:'num',suf:'x',step:.05,show:s=>!isMca(s)},
  ]},
  {title:'Your business',lede:'Use your latest full-year numbers.',fields:[
    {p:'biz.name',label:'Business name',type:'text',wide:true},
    {p:'biz.industry',label:'Industry',type:'select',options:opt(INDUSTRIES),wide:true},
    {p:'biz.years',label:'Years in business',type:'num',step:1},
    {p:'biz.fico',label:'Owner credit score',type:'num',step:5},
    {p:'biz.revenue',label:'Annual revenue',type:'money',step:10000},
    {p:'biz.ebitda',label:'EBITDA',type:'money',step:5000,hint:'Profit before interest, tax, depreciation'},
    {p:'biz.existingDebt',label:'Existing debt',type:'money',step:5000,hint:'Total balances owed'},
    {p:'biz.existingDS',label:'Existing debt payments',type:'money',step:1000,hint:'Per year, all loans and leases'},
    {p:'biz.collType',label:'Collateral you can pledge',type:'select',options:Object.entries(COLLATERAL).map(([k,v])=>[k,v[0]]),wide:true},
    {p:'biz.collValue',label:'Collateral value',type:'money',step:5000},
    {p:'biz.tier',label:'Bank segment',type:'select',wide:true,hint:'How the bank prices you. Auto: small business if revenue ≤ $5M and total debt ≤ $1.5M',
      options:[['auto','Auto (by size)'],['small','Small business: scorecard and rate grid'],['commercial','Commercial: risk rating and economic capital']]},
    {p:'biz.pg',label:'Owner will sign a personal guarantee',type:'bool'},
  ]},
  {title:'What you could bring the bank',lede:'Business besides the loan that lowers the rate the bank needs.',fields:[
    {p:'biz.deposits',label:'Operating deposits',type:'money',step:5000,hint:'Average balance you would keep there'},
    {p:'biz.depositRate',label:'Rate paid on them',type:'num',suf:'%',step:.05},
    {p:'biz.treasuryFees',label:'Treasury service fees',type:'money',step:500,hint:'Per year: payroll, ACH, wires, cards',wide:true},
  ]},
];
const ASSUME_FIELDS=[
  {p:'mkt.sofr',label:'SOFR',type:'num',suf:'%',step:.05},
  {p:'mkt.prime',label:'Prime rate',type:'num',suf:'%',step:.05},
  {p:'mkt.ust5',label:'5-yr Treasury',type:'num',suf:'%',step:.05},
  {p:'mkt.shockBps',label:'Rate shock',type:'num',suf:'bps',step:25,min:-500,hint:'Stress test: shifts the whole SOFR path'},
  {p:'mkt.useCurve',label:'Project floating rates along the SOFR forward curve',type:'bool'},
  {p:'assume.hurdle',label:'Bank hurdle (RAROC)',type:'num',suf:'%',step:.5},
  {p:'assume.tax',label:'Bank tax rate',type:'num',suf:'%',step:1},
  {p:'assume.liqBps',label:'Liquidity premium',type:'num',suf:'bps',step:5},
  {p:'assume.opexBps',label:'Servicing cost',type:'num',suf:'bps',step:5},
  {p:'assume.fixedCost',label:'Fixed cost per loan',type:'money',step:250,hint:'Per year, commercial loans'},
  {p:'assume.fixedCostSmall',label:'Fixed cost, small business',type:'money',step:250,hint:'Per year; scorecard lending is automated'},
  {p:'assume.runoff',label:'Deposit run-off',type:'num',suf:'%',step:5},
  {p:'assume.capRate',label:'Credit on capital',type:'num',suf:'%',step:.05},
  {p:'assume.smallRW',label:'Small-business risk weight',type:'num',suf:'%',step:5,hint:'US rules 100%; Basel retail SME 75%'},
  {p:'assume.discretionBps',label:'Small-business banker discretion',type:'num',suf:'bps',step:5,hint:'How far a banker can move off the rate grid'},
  {p:'assume.minCap',label:'Minimum capital held',type:'num',suf:'%',step:.5,hint:'Regulatory capital per $ of loan'},
];
const tenorLabel=t=>t<1?Math.round(t*12)+' mo':t+' yr';
const curveFields=()=>(S.mkt.curve||[]).map((pt,i)=>({p:`mkt.curve.${i}.r`,label:'SOFR in '+tenorLabel(pt.t),type:'num',suf:'%',step:.05,
  show:s=>!!s.mkt.useCurve}));
const getP=(o,p)=>p.split('.').reduce((a,k)=>a?.[k],o);
const setP=(o,p,v)=>{const ks=p.split('.');let a=o;for(let i=0;i<ks.length-1;i++)a=a[ks[i]];a[ks.at(-1)]=v};
const fid=p=>'f-'+p.replace(/[.\[\]]/g,'-');

function fieldHTML(f,obj){
  if(f.blurb)return `<div class="product-blurb" id="product-blurb"></div>`;
  const id=fid(f.p),v=getP(obj,f.p);
  if(f.type==='bool')return `<div class="field wide" data-p="${f.p}"><label class="toggle" for="${id}"><input type="checkbox" id="${id}" data-p="${f.p}" ${v?'checked':''}>${esc(f.label)}</label></div>`;
  let ctl;
  if(f.type==='select')ctl=`<select id="${id}" data-p="${f.p}">${f.options.map(([k,l])=>`<option value="${k}" ${k===v?'selected':''}>${esc(l)}</option>`).join('')}</select>`;
  else if(f.type==='text')ctl=`<input type="text" id="${id}" data-p="${f.p}" value="${esc(v)}" autocomplete="off">`;
  else ctl=`${f.type==='money'?'<span class="aff pre">$</span>':''}<input type="number" inputmode="decimal" id="${id}" data-p="${f.p}" value="${v}" step="${f.step||1}" min="${f.min??0}">${f.suf?`<span class="aff">${f.suf}</span>`:''}`;
  return `<div class="field${f.wide?' wide':''}" data-p="${f.p}"><label for="${id}">${esc(f.label)}</label><div class="ctl">${ctl}</div>${f.hint?`<small>${esc(f.hint)}</small>`:''}</div>`;
}
function renderInputs(){
  const html=GROUPS.map(g=>`<section class="panel"><fieldset class="group"><legend>${g.title}</legend><p class="lede">${g.lede}</p><div class="fields">${g.fields.map(f=>fieldHTML(f,S)).join('')}</div></fieldset></section>`).join('')
   +`<details class="panel group-d" id="assume-d"><summary>Market rates and bank assumptions</summary><div class="inner"><p class="small muted" style="margin:0 0 12px">These rates are examples, so update them to today's. The bank settings match a typical commercial bank pricing model.</p><div class="fields">${ASSUME_FIELDS.map(f=>fieldHTML(f,S)).join('')}</div>
     <div id="curve-box" style="margin-top:16px"><h3 style="font-size:14.5px;margin:0 0 2px">SOFR forward curve</h3>
     <p class="small muted" style="margin:0 0 8px">Where the market expects 1-month SOFR to be at each point. Spot SOFR above is today. Floating loans follow this path month by month. Values are examples.</p>
     <div class="chart" id="curve-chart"></div><div class="fields" style="margin-top:8px">${curveFields().map(f=>fieldHTML(f,S)).join('')}</div></div></div></details>`;
  $('#inputs').innerHTML=html;syncVisibility();
}
function syncVisibility(){
  const all=[...GROUPS.flatMap(g=>g.fields),...ASSUME_FIELDS,...curveFields()];
  for(const f of all){if(!f.p||!f.show)continue;const el=document.querySelector(`.field[data-p="${f.p}"]`);if(el)el.hidden=!f.show(S)}
  const b=$('#product-blurb');if(b)b.textContent=PRODUCTS[S.loan.product].blurb;
  const cb=$('#curve-box');if(cb)cb.hidden=!S.mkt.useCurve;
}
function readInput(el,obj){
  const p=el.dataset.p;if(!p)return false;
  let v=el.type==='checkbox'?el.checked:(el.type==='number'?parseFloat(el.value):el.value);
  if(el.type==='number'&&!isFinite(v))return false;
  setP(obj,p,v);return p;
}
function applyProductDefaults(k){
  const P=PRODUCTS[k],L=S.loan;
  L.termY=P.termY;if(P.amortY)L.amortY=P.amortY;else L.amortY=P.termY;
  if(P.index)L.index=P.index;if(P.spread!=null)L.spreadBps=P.spread;L.origPct=P.orig;
  if(P.rev){L.unusedBps=P.unused;L.utilPct=P.util}
  if(P.sbaFee)L.sbaFeePct=P.sbaFee;
  if(P.mca){L.mcaFactor=P.factor;L.mcaMonths=P.months}
}

/* ============================================================
   OUTPUT: KPI strip
   ============================================================ */
function renderKPIs(R){
  const {sch,cap,bank}=R,mca=isMca(S);
  const floating=!mca&&S.loan.index!=='ust5';
  const payLab=mca?'Daily payment':(isRev(S)?'Monthly cost (as used)':(floating&&S.mkt.useCurve?'First monthly payment':'Monthly payment'));
  const k=[
    [payLab,money(mca?sch.daily:sch.payment),mca?money(sch.payment)+' a month':(sch.balloon>1&&!isRev(S)?'+ '+moneyShort(sch.balloon)+' balloon':'for '+Math.round(sch.months)+' months')],
    ['True cost (APR)',pct(sch.apr),mca?'no stated rate':'stated rate '+pct(sch.rate)],
    ['DSCR after loan',x2(cap.dscr),cap.dscr>=1.25?'banks want 1.25x or more':'below the usual 1.25x'],
    ['Bank walk-away (est.)',bank.na?'n/a':pct(bank.walkaway),bank.na?'not a bank product':'lowest rate they likely take'],
    ['Room to negotiate',bank.na?'—':(bank.negotiable>0?bps(bank.negotiable*100):'little'),bank.na?'compare with a bank loan':(bank.negotiable>0?'≈ '+moneyShort(bank.negotiable/100*sch.avgBal*S.loan.termY)+' over the term':'push on fees and terms')]
  ];
  $('#kpis').innerHTML=k.map((x,i)=>`<div class="kpi${i===4?' zone':''}"><div class="lab">${x[0]}</div><div class="val">${x[1]}</div><div class="sub">${x[2]}</div></div>`).join('');
}

/* ============================================================
   OUTPUT: tabs
   ============================================================ */
const TABS=[['cost','What it costs'],['afford','Can I afford it'],['bank','How the bank sees it'],['negotiate','Negotiate'],['compare','Compare offers'],['learn','Learn']];
function renderTabs(){
  $('#tabs').innerHTML=TABS.map(([k,l])=>`<button class="tab" role="tab" id="tab-${k}" aria-selected="${k===activeTab}" data-tab="${k}" type="button">${l}</button>`).join('');
  $('#views').innerHTML=TABS.map(([k])=>`<section class="view" role="tabpanel" id="view-${k}" aria-labelledby="tab-${k}" ${k===activeTab?'':'hidden'}></section>`).join('');
  renderNegotiateShell();renderCompareShell();renderLearn();
}
function setTab(k){activeTab=k;document.querySelectorAll('.tab').forEach(b=>b.setAttribute('aria-selected',b.dataset.tab===k));
  document.querySelectorAll('.view').forEach(v=>v.hidden=v.id!=='view-'+k);try{localStorage.setItem(STORE_KEY+'-tab',k)}catch(e){}
  if(k==='cost'){drawAmort(lastR.sch);drawRatePath(lastR.sch)}}

/* ---------- Cost ---------- */
function renderCost(R){
  const {sch}=R,L=S.loan,mca=isMca(S),rev=isRev(S);
  const years=[];for(const r of sch.rows){const y=Math.ceil(r.m/12);years[y]=years[y]||{y,pay:0,int:0,prin:0,fee:0,bal:0,sb:0};
    Object.assign(years[y],{pay:years[y].pay+r.pay,int:years[y].int+r.int,prin:years[y].prin+r.prin,fee:years[y].fee+r.fee,bal:r.bal,sb:years[y].sb+r.start})}
  const floating=!mca&&L.index!=='ust5',yrs=years.filter(Boolean),yRate=y=>y.sb>0?y.int/y.sb*1200:NaN;
  let msg;
  if(mca)msg=`You receive ${money(sch.net)} after fees and repay ${money(L.amount*L.mcaFactor)} over about ${L.mcaMonths} months. A factor rate of ${L.mcaFactor} sounds like ${pct((L.mcaFactor-1)*100,0)}, but because you repay daily over a short period, the real annual cost is <b>${pct(sch.apr,1)} APR</b>.`;
  else{const gap=sch.apr-sch.rate;msg=`The stated rate is <b>${pct(sch.rate)}</b> (${INDEXES[L.index].split(' ')[0]} ${pct(indexRate(S,L.index))} + ${L.spreadBps} bps). Fees raise the true cost to <b>${pct(sch.apr)} APR</b>${gap>.005?`, which is ${bps(gap*100)} more`:''}.`;
    if(sch.balloon>1&&!rev)msg+=` Because the payments run over ${L.amortY} years and the loan is due in ${L.termY}, a <b>${money(sch.balloon)} balloon</b> is due at the end. Plan to refinance or pay it off.`;
    if(rev)msg+=` Line costs assume you use ${L.utilPct}% on average, and ${money(sch.drawn)} is repaid when the line ends.`;
    const shock=S.mkt.shockBps||0,shockTxt=shock?` These figures include a <b>${shock>0?'+':'−'}${Math.abs(shock)} bps rate shock</b>.`:'';
    if(floating&&S.mkt.useCurve)msg+=` This is a floating rate that follows the SOFR forward curve, so the payment is recalculated each month. The average rate over the term is <b>${pct(sch.avgRate)}</b> (year 1 ${pct(yRate(yrs[0]))}, year ${yrs.length} ${pct(yRate(yrs[yrs.length-1]))}).`+shockTxt;
    else if(floating)msg+=' This is a floating rate. With the curve turned off, these figures assume SOFR stays where it is today.'+shockTxt;}
  $('#view-cost').innerHTML=`
  <div class="card"><h2>What this loan really costs</h2><p class="lede">${msg}</p>
    <div class="stats">
      <div class="stat"><div class="lab">${mca?'Daily payment':rev?'Monthly cost at expected use':floating&&S.mkt.useCurve?'First monthly payment':'Monthly payment'}</div><div class="val">${money(mca?sch.daily:sch.payment)}</div><div class="sub">${mca?money(sch.payment)+' / month':floating&&S.mkt.useCurve?'changes as SOFR moves':'incl. fees charged monthly'}</div></div>
      <div class="stat"><div class="lab">Cash you receive</div><div class="val">${money(sch.net)}</div><div class="sub">after ${money(sch.upfront)} upfront fees</div></div>
      <div class="stat"><div class="lab">Total interest</div><div class="val">${money(sch.totalInterest)}</div><div class="sub">${mca?'the factor premium':'over the '+(rev?L.termY:Math.min(L.termY,L.amortY))+'-year term'}</div></div>
      <div class="stat"><div class="lab">Total fees</div><div class="val">${money(sch.totalFees)}</div><div class="sub">upfront and ongoing</div></div>
      <div class="stat"><div class="lab">Cost per $1 borrowed</div><div class="val">${'$'+(sch.totalCost/Math.max(1,sch.drawn)).toFixed(2)}</div><div class="sub">interest + fees</div></div>
    </div></div>
  <div class="card"><h3>${mca?'What you still owe':rev?'Drawn balance and cost to date':'Balance and interest paid over time'}</h3>
    <div class="chart" id="amort-chart"></div>
    <div class="legend"><span><i style="background:var(--c1)"></i>${mca?'Amount still owed':'Loan balance'}</span><span><i style="background:var(--c2)"></i>${mca?'Premium paid to date':'Interest paid to date'}</span></div></div>
  ${floating?rateRiskCard(sch):''}
  <div class="card"><h3>Year by year</h3><div class="tablewrap" style="margin-top:8px"><table>
    <thead><tr><th>Year</th>${mca?'':'<th class="r">Avg rate</th>'}<th class="r">Payments</th><th class="r">Interest</th><th class="r">Principal</th><th class="r">Fees</th><th class="r">Balance at year end</th></tr></thead>
    <tbody>${yrs.map(y=>`<tr><td>${y.y}</td>${mca?'':`<td class="r num">${pct(yRate(y))}</td>`}<td class="r num">${money(y.pay)}</td><td class="r num">${money(y.int)}</td><td class="r num">${money(y.prin)}</td><td class="r num">${money(y.fee)}</td><td class="r num">${money(y.bal)}</td></tr>`).join('')}
    ${sch.balloon>1?`<tr class="hl"><td colspan="${mca?5:6}">${rev?'Repay the drawn balance when the line ends':'Balloon payment due at maturity'}</td><td class="r num"><b>${money(sch.balloon)}</b></td></tr>`:''}</tbody></table></div></div>`;
  drawAmort(sch);drawRatePath(sch);
}
function shocked(bpsMove){const t=clone(S);t.mkt.shockBps=(S.mkt.shockBps||0)+bpsMove;return schedule(t)}
function rateRiskCard(sch){
  const dn=shocked(-100),up=shocked(100),rev=isRev(S),payLab=rev?'Monthly cost':'First payment';
  const row=(lab,x,base)=>`<tr${base?' class="hl"':''}><td>${lab}</td><td class="r num">${pct(x.avgRate)}</td><td class="r num">${money(x.payment)}</td><td class="r num">${pct(x.apr)}</td><td class="r num">${money(x.totalCost)}</td><td class="r num">${base?'—':(x.totalCost>=sch.totalCost?'+':'−')+money(Math.abs(x.totalCost-sch.totalCost))}</td></tr>`;
  return `<div class="card"><h3>Rate risk: what if SOFR moves?</h3><p class="lede" style="margin:4px 0 10px">Floating rates move with SOFR. This shows the cost if SOFR ends up 1% above or below ${S.mkt.useCurve?'the forward curve':'today'} for the whole term. A 1% move changes your total cost by about <b>${money(up.totalCost-sch.totalCost)}</b>.</p>
    <div class="chart" id="rate-chart"></div>
    <div class="legend"><span><i style="background:var(--c1)"></i>All-in rate, month by month</span></div>
    <div class="tablewrap" style="margin-top:10px"><table><thead><tr><th>SOFR path</th><th class="r">Avg rate</th><th class="r">${payLab}</th><th class="r">APR</th><th class="r">Total cost</th><th class="r">vs. base</th></tr></thead><tbody>
    ${row('1% lower',dn)}${row(S.mkt.useCurve?'Forward curve (base)':'Flat (base)',sch,true)}${row('1% higher',up)}</tbody></table></div>
    <p class="small muted" style="margin:10px 0 0">To limit this risk, ask the bank to also quote a fixed rate, or the cost of an interest rate cap or swap.</p></div>`;
}
function lineChart(box,pts,{fmtY,fmtX,label}){
  if(!box||box.offsetParent===null||!pts.length)return;
  const W=Math.max(280,box.clientWidth),H=170,ml=50,mr=12,mt=10,mb=24,iw=W-ml-mr,ih=H-mt-mb;
  const xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]);let lo=Math.min(...ys),hi=Math.max(...ys);
  if(hi-lo<0.5){const mid=(hi+lo)/2;lo=mid-0.25;hi=mid+0.25}const pad=(hi-lo)*.12;lo-=pad;hi+=pad;
  const x0=Math.min(...xs),x1=Math.max(...xs)||1,X=v=>ml+(v-x0)/(x1-x0||1)*iw,Y=v=>mt+ih-(v-lo)/(hi-lo)*ih;
  const ticks=[0,1/3,2/3,1].map(f=>lo+f*(hi-lo));
  const path='M'+pts.map(p=>`${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(' L');
  const xt=[x0,x0+(x1-x0)/2,x1];
  box.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}"><g class="grid">${ticks.map(t=>`<line x1="${ml}" x2="${W-mr}" y1="${Y(t)}" y2="${Y(t)}"/>`).join('')}</g>
    <g class="axis">${ticks.map(t=>`<text x="${ml-8}" y="${Y(t)+4}" text-anchor="end">${fmtY(t)}</text>`).join('')}${xt.map((v,i)=>`<text x="${X(v)}" y="${H-6}" text-anchor="${i===0?'start':i===2?'end':'middle'}">${fmtX(v)}</text>`).join('')}</g>
    <path d="${path}" fill="none" stroke="var(--c1)" stroke-width="2" stroke-linejoin="round"/>
    ${pts.map(p=>`<circle cx="${X(p[0])}" cy="${Y(p[1])}" r="${pts.length<=12?4:0}" fill="var(--c1)" stroke="var(--surface)" stroke-width="2"><title>${fmtX(p[0])}: ${fmtY(p[1])}</title></circle>`).join('')}</svg>`;
}
function drawRatePath(sch){
  const box=$('#rate-chart');if(!box)return;
  lineChart(box,sch.rows.map(r=>[r.m,r.rate]),{fmtY:v=>v.toFixed(2)+'%',fmtX:m=>'Month '+Math.round(m),label:'All-in loan rate by month'});
}
function drawCurve(){
  const box=$('#curve-chart');if(!box||!S.mkt.useCurve)return;
  const pts=[[0,S.mkt.sofr],...S.mkt.curve.filter(p=>p.t>0).map(p=>[p.t,p.r]).sort((a,b)=>a[0]-b[0])];
  lineChart(box,pts,{fmtY:v=>v.toFixed(2)+'%',fmtX:t=>t===0?'Today':tenorLabel(+t.toFixed(1)),label:'SOFR forward curve'});
}
function niceMax(v){const e=Math.pow(10,Math.floor(Math.log10(v||1))),n=v/e;return (n<=1?1:n<=2?2:n<=2.5?2.5:n<=5?5:10)*e}
function drawAmort(sch){
  const box=$('#amort-chart');if(!box||box.offsetParent===null)return;
  const W=Math.max(300,box.clientWidth),H=250,ml=58,mr=14,mt=12,mb=28,iw=W-ml-mr,ih=H-mt-mb;
  const rows=sch.rows;if(!rows.length){box.innerHTML='';return}
  let cum=0;const pts=[{m:0,bal:rows[0].start,ci:0}];rows.forEach(r=>{cum+=r.int;pts.push({m:r.m,bal:r.bal,ci:cum})});
  const N=rows.at(-1).m,ymax=niceMax(Math.max(...pts.map(p=>Math.max(p.bal,p.ci)))*1.02);
  const X=m=>ml+m/N*iw,Y=v=>mt+ih-v/ymax*ih;
  const area=`M${X(0)},${Y(0)} `+pts.map(p=>`L${X(p.m).toFixed(1)},${Y(p.bal).toFixed(1)}`).join(' ')+` L${X(N)},${Y(0)} Z`;
  const bl='M'+pts.map(p=>`${X(p.m).toFixed(1)},${Y(p.bal).toFixed(1)}`).join(' L');
  const il='M'+pts.map(p=>`${X(p.m).toFixed(1)},${Y(p.ci).toFixed(1)}`).join(' L');
  const ticks=[0,.25,.5,.75,1].map(f=>f*ymax);
  const xstep=N<=24?6:N<=60?12:N<=120?24:60;const xt=[];for(let m=0;m<=N;m+=xstep)xt.push(m);
  box.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Loan balance and cumulative interest by month">
    <g class="grid">${ticks.map(t=>`<line x1="${ml}" x2="${W-mr}" y1="${Y(t)}" y2="${Y(t)}"/>`).join('')}</g>
    <g class="axis">${ticks.map(t=>`<text x="${ml-8}" y="${Y(t)+4}" text-anchor="end">${moneyShort(t)}</text>`).join('')}
      ${xt.map(m=>`<text x="${X(m)}" y="${H-8}" text-anchor="middle">${m===0?'0':(xstep>=12?'Yr '+m/12:'Mo '+m)}</text>`).join('')}</g>
    <path d="${area}" fill="var(--c1)" fill-opacity=".14"/>
    <path d="${bl}" fill="none" stroke="var(--c1)" stroke-width="2" stroke-linejoin="round"/>
    <path d="${il}" fill="none" stroke="var(--c2)" stroke-width="2" stroke-linejoin="round"/>
    <circle cx="${X(N)}" cy="${Y(pts.at(-1).bal)}" r="4" fill="var(--c1)" stroke="var(--surface)" stroke-width="2"/>
    <circle cx="${X(N)}" cy="${Y(pts.at(-1).ci)}" r="4" fill="var(--c2)" stroke="var(--surface)" stroke-width="2"/>
    <g id="hv" visibility="hidden"><line id="hv-l" y1="${mt}" y2="${mt+ih}" stroke="var(--ink-2)" stroke-dasharray="3 3"/>
      <circle id="hv-a" r="5" fill="var(--c1)" stroke="var(--surface)" stroke-width="2"/><circle id="hv-b" r="5" fill="var(--c2)" stroke="var(--surface)" stroke-width="2"/></g>
    <rect x="${ml}" y="${mt}" width="${iw}" height="${ih}" fill="transparent" id="hv-hit"/></svg><div class="tip" id="amort-tip" hidden></div>`;
  const svg=box.querySelector('svg'),hit=$('#hv-hit',box),tip=$('#amort-tip',box),g=$('#hv',box);
  const move=e=>{const rc=svg.getBoundingClientRect(),sx=(e.clientX-rc.left)*W/rc.width;
    const m=Math.max(0,Math.min(N,Math.round((sx-ml)/iw*N)));const p=pts.reduce((a,b)=>Math.abs(b.m-m)<Math.abs(a.m-m)?b:a);
    g.setAttribute('visibility','visible');$('#hv-l',box).setAttribute('x1',X(p.m));$('#hv-l',box).setAttribute('x2',X(p.m));
    $('#hv-a',box).setAttribute('cx',X(p.m));$('#hv-a',box).setAttribute('cy',Y(p.bal));$('#hv-b',box).setAttribute('cx',X(p.m));$('#hv-b',box).setAttribute('cy',Y(p.ci));
    tip.hidden=false;tip.style.left=(X(p.m)/W*rc.width)+'px';tip.style.top=(Math.min(Y(p.bal),Y(p.ci))/H*rc.height-10)+'px';
    tip.innerHTML=`Month ${p.m}<br>${isMca(S)?'Owed':'Balance'} <b>${money(p.bal)}</b><br>${isMca(S)?'Premium':'Interest'} to date <b>${money(p.ci)}</b>`};
  hit.addEventListener('pointermove',move);hit.addEventListener('pointerleave',()=>{g.setAttribute('visibility','hidden');tip.hidden=true});
}

/* ---------- Afford ---------- */
function meter(name,sub,val,valTxt,max,markAt,markLbl,goodIfAbove){
  const w=Math.min(100,Math.max(0,val/max*100)),m=Math.min(100,markAt/max*100);
  const ok=goodIfAbove?val>=markAt:val<=markAt;const near=goodIfAbove?val>=markAt*.9:val<=markAt*1.12;
  const col=ok?'var(--good)':near?'var(--warn)':'var(--bad)';
  return `<div class="meter"><div class="name">${name}<small>${sub}</small></div><div class="bar"><div class="fill" style="width:${w}%;background:${col}"></div><div class="mark" style="left:${m}%"><span>${markLbl}</span></div></div><div class="v">${valTxt} <span class="pill ${ok?'good':near?'warn':'bad'}">${ok?'OK':near?'Tight':'Weak'}</span></div></div>`;
}
function renderAfford(R){
  const {cap,sch}=R,B=S.biz,L=S.loan,el=eligibility(S,cap);
  const bind=cap.binding;const over=bind&&L.amount>bind[1];
  const collOnly=over&&bind[0]==='collateral'&&L.amount<=Math.min(cap.maxDSCR,cap.maxLev);
  $('#view-afford').innerHTML=`
  <div class="card"><h2>Can the business carry this loan?</h2><p class="lede">Lenders check three ratios before they look at anything else. Each bar shows where you are, and the line shows the typical bank limit.</p>
    ${meter('Debt service coverage','Cash flow ÷ all debt payments',cap.dscr,x2(cap.dscr),Math.max(3,cap.dscr*1.1),1.25,'1.25x min',true)}
    ${meter('Debt to EBITDA','Total debt ÷ EBITDA',cap.lev,x2(cap.lev),Math.max(6,cap.lev*1.1),3.5,'3.5x max',false)}
    ${COLLATERAL[B.collType][1]>0?meter('Collateral coverage','Lendable value ÷ loan',cap.collCov*100,pct(cap.collCov*100,0),Math.max(150,cap.collCov*110),100,'100%',true):`<div class="meter"><div class="name">Collateral coverage<small>No collateral entered</small></div><div class="small muted">Unsecured loans lean on cash flow, credit score and usually a personal guarantee.</div><div class="v"><span class="pill info">Unsecured</span></div></div>`}
    <p class="small muted" style="margin:12px 0 0">Total debt payments after this loan: ${money(cap.totDS)} a year (${money(B.existingDS)} existing + ${money(cap.newDS)} new). This uses EBITDA as a stand-in for cash flow. Banks may subtract taxes, owner draws and required spending on equipment, which lowers the ratio.</p></div>
  <div class="card"><h2>How much could you borrow?</h2><p class="lede">Each limit below gives a maximum loan on the same terms. The lowest one is what a bank will likely approve.</p>
    <div class="stats">
      <div class="stat" ${bind&&bind[0].startsWith('cash')?'style="outline:2px solid var(--accent)"':''}><div class="lab">By cash flow (1.25x DSCR)</div><div class="val">${money(cap.maxDSCR)}</div></div>
      <div class="stat" ${bind&&bind[0].startsWith('lev')?'style="outline:2px solid var(--accent)"':''}><div class="lab">By leverage (3.5x EBITDA)</div><div class="val">${money(cap.maxLev)}</div></div>
      <div class="stat" ${bind&&bind[0]==='collateral'?'style="outline:2px solid var(--accent)"':''}><div class="lab">By collateral</div><div class="val">${isFinite(cap.maxColl)?money(cap.maxColl):'n/a'}</div><div class="sub">${COLLATERAL[B.collType][1]>0?pct(COLLATERAL[B.collType][1]*100,0)+' advance on '+money(B.collValue):'nothing pledged'}</div></div>
    </div>
    <div class="callout ${over?(collOnly?'zone':'bad'):'good'}" style="margin-top:14px">${bind?(over?(collOnly?`Cash flow and leverage support ${money(L.amount)}, but collateral covers only ${money(bind[1])} of it. Cash-flow lenders often go beyond collateral for strong borrowers. Expect them to ask for a personal guarantee, more collateral or an SBA structure to cover the ${money(L.amount-bind[1])} gap.`:`You are asking for ${money(L.amount)}, which is <b>${money(L.amount-bind[1])} more</b> than the ${bind[0]} limit allows. Expect a counteroffer, or ask for a longer schedule, a smaller amount, an SBA structure or more collateral.`)
      :`Your request fits. The tightest limit is <b>${bind[0]}</b> at ${money(bind[1])}, which leaves ${money(bind[1]-L.amount)} of headroom.`):'Enter EBITDA to estimate capacity.'}</div>
    ${!isMca(S)?`<p class="small" style="margin:12px 0 0"><b>Covenant cushion:</b> at a ${L.covDSCR.toFixed(2)}x minimum DSCR covenant, EBITDA could fall about <b>${pct(Math.max(0,cap.cushion*100),0)}</b> (to ${money(B.ebitda*(1-Math.max(0,cap.cushion)))}) before you breach it.</p>`:''}</div>
  <div class="card"><h2>Which loan types fit you?</h2><p class="lede">Based on your profile. This is a guide to where to start, not an approval.</p>
    <div class="tablewrap"><table><thead><tr><th>Loan type</th><th>Fit</th><th>Why</th></tr></thead><tbody>
    ${el.map(e=>`<tr ${e.k===L.product?'class="hl"':''}><td><b>${e.label}</b></td><td><span class="pill ${e.status}">${{good:'Good fit',warn:'Maybe',bad:'Unlikely'}[e.status]}</span></td><td class="small">${e.why}</td></tr>`).join('')}
    </tbody></table></div></div>`;
}

/* ---------- Bank view ---------- */
function renderBank(R){
  const b=R.bank,L=S.loan;
  if(b.na){$('#view-bank').innerHTML=`<div class="card"><h2>A merchant cash advance is not priced like a bank loan</h2><p class="lede">MCA funders buy your future sales at a discount. They are not bound by bank capital rules, so this model does not apply. Switch the loan type to <b>Term loan</b> or <b>SBA 7(a)</b> to see what a bank would likely charge you for the same amount. That is often a fraction of this APR.</p></div>`;return}
  const pts=[
    {k:'cost',v:b.costFloor,lbl:'Cost floor',cls:''},
    {k:'walk',v:b.walkaway,lbl:'Walk-away',cls:''},
    {k:'stand',v:b.standalone,lbl:'Loan-only target',cls:''},
    {k:'offer',v:b.offered,lbl:'Offered',cls:'offer'},
  ];
  if(S.lev.competeRate>0)pts.push({k:'comp',v:S.lev.competeRate,lbl:'Competing offer',cls:''});
  const uniq=pts.filter((p,i)=>!(p.k==='cost'&&Math.abs(p.v-b.walkaway)<.005));
  const lo=Math.min(...uniq.map(p=>p.v))-.4,hi=Math.max(...uniq.map(p=>p.v))+.4,pos=v=>(v-lo)/(hi-lo)*100;
  const sorted=[...uniq].sort((a,c)=>a.v-c.v);const slots=['dn','up','dn2','up2','dn','up'];
  const ladder=`<div class="ladder" aria-label="Rate ladder"><div class="track">
    ${b.negotiable>0?`<div class="zoneband" style="left:${pos(b.offered-b.negotiable)}%;width:${pos(b.offered)-pos(b.offered-b.negotiable)}%" title="Negotiation zone"></div>`:''}
    ${sorted.map((p,i)=>{const x=pos(p.v),edge=x<8?' edge-l':x>92?' edge-r':'';return `<div class="tick ${p.cls}" style="left:${x}%"></div><div class="lbl ${slots[i]}${edge}" style="left:${x}%">${p.lbl}<b style="${p.k==='offer'?'color:var(--accent-ink)':''}">${pct(p.v)}</b></div>`}).join('')}
  </div></div>`;
  const rr=b.rr,spreadOf=v=>Math.round((v-b.idx)*100);
  $('#view-bank').innerHTML=`
  <div class="card"><div class="row" style="justify-content:space-between"><h2>The bank's side of your deal</h2><span class="pill info">${b.tier==='small'?'Small business segment':'Commercial segment'}</span></div>
    <p class="small muted" style="margin:4px 0 10px">${b.tier==='small'?'Priced like a small-business loan: a credit scorecard sets a band with a pooled default rate, capital follows retail rules, and the rate comes from a grid that bankers can adjust only a little.':'Priced like a commercial loan: an analyst-style risk rating, economic capital for this specific deal, and relationship pricing with more room to negotiate.'} ${S.biz.tier==='auto'?'Chosen automatically from your revenue and total debt. You can change it under Your business.':''}</p>
    <p class="lede">Banks price a loan to earn a target return on the capital it uses, usually around ${S.assume.hurdle}%. This estimates the rates the bank is working with. The <b style="color:var(--zone-ink)">striped band</b> is the room between the offer and the lowest rate the bank would likely accept.</p>
    ${ladder}
    <div class="tablewrap"><table><thead><tr><th>Rate</th><th class="r">All-in</th><th class="r">Spread</th><th>What it means</th></tr></thead><tbody>
      <tr><td><b>Offered</b></td><td class="r num">${pct(b.offered)}</td><td class="r num">${spreadOf(b.offered)} bps</td><td class="small">What the bank opened with.</td></tr>
      <tr><td>Loan-only target</td><td class="r num">${pct(b.standalone)}</td><td class="r num">${spreadOf(b.standalone)} bps</td><td class="small">Earns the ${S.assume.hurdle}% hurdle on the loan alone, with no other business from you.</td></tr>
      <tr class="hl"><td><b>Walk-away (est.)</b></td><td class="r num"><b>${pct(b.walkaway)}</b></td><td class="r num"><b>${spreadOf(b.walkaway)} bps</b></td><td class="small">${b.relFloor>=b.costFloor?'The hurdle counting the deposits and services you bring. Below this, the bank earns less than its target.':'Covers funding, expected loss and servicing costs. Banks rarely go below it.'}</td></tr>
      <tr><td>Cost floor</td><td class="r num">${pct(b.costFloor)}</td><td class="r num">${spreadOf(b.costFloor)} bps</td><td class="small">Funding + liquidity + expected loss + servicing. Below this, the bank loses money.</td></tr>
    </tbody></table></div>
    <div class="callout ${b.negotiable>0?'zone':'bad'}" style="margin-top:14px">${b.negotiable>0
      ?`The bank's estimated return at the offered rate is <b>${pct(b.rarocStand,1)}</b> on the loan alone and <b>${pct(b.rarocRel,1)}</b> counting your deposits and services, against a ${S.assume.hurdle}% hurdle. ${b.tier==='small'&&b.room>b.negotiable?`The bank's model has about ${bps(b.room*100)} of room, but small-business loans are priced from a rate grid and a banker can usually move only about <b>${bps(b.negotiable*100)}</b> without an exception.`:`There is about <b>${bps(b.negotiable*100)}</b> of room.`} A reasonable opening ask is <b>${pct(b.opening)}</b> (${spreadOf(b.opening)} bps). A realistic outcome is around <b>${pct(b.landing)}</b>.`
      :`The offer is already at or below the estimated walk-away rate (the bank's return is about ${pct(b.rarocRel,1)}). Pushing on rate probably will not work. Focus on fees, covenants, the prepayment penalty and the personal guarantee.`}</div></div>
  <div class="card"><h3>Credit risk: PD, LGD and capital</h3>
    <p class="small muted" style="margin:4px 0 12px">How the bank sizes the risk of this loan. Expected loss is built into the rate every year. Capital is the cushion the bank must hold, and its ${S.assume.hurdle}% return target is measured on it.</p>
    <div class="stats">
      <div class="stat"><div class="lab">PD · probability of default</div><div class="val">${pct(rr.pd*100,2)}</div><div class="sub">${b.tier==='small'?`pooled rate for band ${rr.rating}`:`from risk rating ${rr.rating} of 10`}, per year</div></div>
      <div class="stat"><div class="lab">LGD · loss given default</div><div class="val">${pct(b.lgd*100,0)}</div><div class="sub">${L.product==='sba504'?'SBA 504 first-lien structure':S.biz.collType==='none'?'unsecured':`collateral covers ${pct(Math.min(1,b.cap.collCov)*100,0)} of the loan`}${S.biz.pg&&L.product!=='sba504'?'; guarantee trims 3 pts':''}</div></div>
      <div class="stat"><div class="lab">EAD · exposure at default</div><div class="val">${money(b.ead)}</div><div class="sub">${isRev(S)?'drawn + 75% of the unused line':'loan balance'}</div></div>
      <div class="stat"><div class="lab">Expected loss · PD × LGD × EAD</div><div class="val">${money(b.EL)}</div><div class="sub">${pct(b.EL/b.ead*100,2)} of EAD a year${b.g?`, on the ${pct((1-b.g)*100,0)} not guaranteed by SBA`:''}</div></div>
      <div class="stat"><div class="lab">Capital held (ECAP)</div><div class="val">${money(b.EC)}</div><div class="sub">${pct(b.EC/b.ead*100,1)} of EAD, ${b.ecReg>=b.ecIRB?'regulatory minimum binds':'risk model binds'}</div></div>
    </div>
    <div class="tablewrap" style="margin-top:12px"><table><tbody>
      <tr><td>${b.tier==='small'?'Basel IRB retail':'Basel IRB corporate'} capital charge K (99.9%)</td><td class="r num">${pct(b.K*100,2)} of EAD</td></tr>
      <tr><td>Economic capital: 1.06 × K × EAD${b.g?'; SBA-guaranteed share at 1.6%':''}</td><td class="r num">${money(b.ecIRB)}</td></tr>
      <tr><td>Regulatory minimum: ${S.assume.minCap}%${b.tier==='small'?` × ${S.assume.smallRW}% risk weight`:''} × EAD</td><td class="r num">${money(b.ecReg)}</td></tr>
      <tr class="hl"><td><b>Capital used for pricing (the higher of the two)</b></td><td class="r num"><b>${money(b.EC)}</b></td></tr>
    </tbody></table></div></div>
  <div class="two">
    <div class="card">${b.tier==='small'?`<h3>Your estimated credit score: ${rr.score} (band ${rr.rating})</h3><p class="small muted" style="margin:4px 0 10px">Small-business loans are scored, not individually rated. Band ${rr.rating} carries a pooled default rate of ${pct(rr.pd*100,1)} a year (bands run A to E).`:`<h3>Your estimated risk rating: ${rr.rating} of 10</h3><p class="small muted" style="margin:4px 0 10px">1 is strongest. Implied probability of default: ${pct(rr.pd*100,2)} a year.`} The bank's loss if you default: ${pct(b.lgd*100,0)} of the balance${b.g?`, before the SBA guarantee covers ${pct(b.g*100,0)}`:''}.</p>
      <div class="tablewrap"><table><thead><tr><th>Driver</th><th>You</th><th class="r">Effect</th></tr></thead><tbody>
      ${rr.drivers.map(d=>`<tr><td>${d.name}</td><td class="num">${esc(d.val)}</td><td class="r"><span class="pill ${(b.tier==='small'?-d.delta:d.delta)<0?'good':(b.tier==='small'?-d.delta:d.delta)>0?'bad':'info'}">${(b.tier==='small'?-d.delta:d.delta)<0?'Helps':(b.tier==='small'?-d.delta:d.delta)>0?'Hurts':'Neutral'}</span></td></tr>`).join('')}
      </tbody></table></div></div>
    <div class="card"><h3>The bank's numbers at the offered rate (year 1)</h3>
      <div class="tablewrap"><table><tbody>
      <tr><td>Funds used (drawn)</td><td class="r num">${money(b.drawn)}</td></tr>
      <tr><td>Bank's cost of funds</td><td class="r num">${pct(b.cof)} + ${bps(b.liq*100)}</td></tr>
      <tr><td>Revenue from loan (margin + fees)</td><td class="r num">${money(b.revenueAtOffer)}</td></tr>
      <tr><td>Expected loss (PD × LGD × EAD)</td><td class="r num">−${money(b.EL)}</td></tr>
      <tr><td>Servicing cost</td><td class="r num">−${money(b.opex)}</td></tr>
      <tr><td>Value of your deposits and services</td><td class="r num">+${money(b.relInc)}</td></tr>
      <tr><td>Capital held (ECAP)</td><td class="r num">${money(b.EC)} <span class="muted">(${pct(b.EC/b.ead*100,1)}, ${b.ecReg>=b.ecIRB?'regulatory minimum':'risk model'})</span></td></tr>
      <tr class="hl"><td><b>Return on that capital</b></td><td class="r num"><b>${pct(b.rarocRel,1)}</b> vs ${S.assume.hurdle}%</td></tr>
      </tbody></table></div>
      ${L.index==='ust5'&&S.mkt.useCurve?`<p class="small" style="margin:10px 0 0"><b>About fixed rates:</b> the bank funds a fixed-rate loan at the swap rate for its term, which the SOFR curve puts at ${pct(b.cof)} for ${L.termY} years, not at the ${pct(S.mkt.ust5)} Treasury index your rate is quoted over.</p>`:''}
      ${L.index==='prime'?`<p class="small" style="margin:10px 0 0"><b>About Prime:</b> Prime is usually about ${pct(S.mkt.prime-S.mkt.sofr,1)} above SOFR, which is closer to what money costs the bank. So "Prime + ${(L.spreadBps/100).toFixed(2)}%" is really about SOFR + ${pct(S.mkt.prime-S.mkt.sofr+L.spreadBps/100,2)}. Ask for a SOFR-based quote to compare.</p>`:''}
    </div>
  </div>`;
}

/* ---------- Negotiate ---------- */
function renderNegotiateShell(){
  const f=[{p:'lev.moreDeposits',label:'Extra deposits you could move',type:'money',step:10000},
    {p:'lev.moreTreasury',label:'Extra treasury fees per year',type:'money',step:500},
    {p:'lev.competeName',label:'Competing lender',type:'text'},
    {p:'lev.competeRate',label:'Their all-in rate',type:'num',suf:'%',step:.05,hint:'0 if none'}];
  $('#view-negotiate').innerHTML=`<div class="card" id="neg-top"></div>
   <div class="card"><h3>What you can bring</h3><p class="small muted" style="margin:4px 0 12px">Change these to see how much each offer is worth to the bank.</p><div class="fields" id="neg-inputs">${f.map(x=>fieldHTML(x,S)).join('')}</div></div>
   <div class="card"><h2>Ways to improve the deal</h2><p class="lede">Each option below is a change to the deal we tested in the bank's model. Dollar amounts assume the bank passes the full savings on to you, so treat them as the most you could get.</p><div class="levers" id="neg-levers"></div></div>
   <div class="card"><div class="row" style="justify-content:space-between"><h2>Your talking points</h2><button class="btn primary" id="copy-brief" type="button">Copy</button></div><p class="lede" style="margin-top:4px">Use these to prepare for the call, or edit them into an email to your banker.</p><pre class="brief" id="brief" tabindex="0"></pre></div>`;
}
function renderNegotiate(R){
  const b=R.bank,L=S.loan,sch=R.sch;
  if(b.na){$('#neg-top').innerHTML=`<h2>Before you sign an MCA</h2><p class="lede">Your true cost is <b>${pct(sch.apr,0)} APR</b>. The strongest move is to replace it: ask two banks or an SBA lender for a term loan or line of the same size, and compare using the Compare offers tab. If you do take an MCA, ask for a lower factor rate, a longer payback, repayment as a percentage of sales instead of a fixed daily amount, and no fees for paying it off early.</p>`;
    $('#neg-levers').innerHTML='';$('#brief').textContent=briefText(R,[]);return}
  const lv=levers(S,R),yrs=L.termY;
  const saveLand=Math.max(0,b.offered-b.landing)/100*sch.avgBal*yrs;
  $('#neg-top').innerHTML=`<h2>${b.negotiable>0?`About ${bps(b.negotiable*100)} of room on rate`:'Rate is near the floor. Negotiate the terms instead.'}</h2>
    <div class="stats" style="margin-top:12px">
      <div class="stat"><div class="lab">Offered</div><div class="val">${pct(b.offered)}</div><div class="sub">${Math.round((b.offered-b.idx)*100)} bps spread</div></div>
      <div class="stat" style="background:var(--zone-soft)"><div class="lab">Opening ask</div><div class="val">${pct(b.opening)}</div><div class="sub">${Math.round((b.opening-b.idx)*100)} bps spread</div></div>
      <div class="stat" style="background:var(--zone-soft)"><div class="lab">Realistic outcome</div><div class="val">${pct(b.landing)}</div><div class="sub">saves ≈ ${money(saveLand)} over ${yrs} yrs</div></div>
      <div class="stat"><div class="lab">Bank walk-away (est.)</div><div class="val">${pct(b.walkaway)}</div><div class="sub">do not expect to go below this</div></div>
    </div>`;
  $('#neg-levers').innerHTML=lv.map(l=>`<div class="lever"><div><h3>${esc(l.title)}</h3><div class="ask">${esc(l.ask)}</div></div>
     <div class="worth">${l.dollars>0?`<span class="n">≈ ${money(l.dollars)}</span><small>${l.kind==='fee'&&l.bps>0?'APR −'+bps(l.bps):l.bps>0?'rate −'+bps(l.bps):'over the term'}</small>`:`<span class="n neutral">Terms</span><small>protects you</small>`}</div>
     <div class="why">${esc(l.why)}</div></div>`).join('');
  $('#brief').textContent=briefText(R,lv);
}
function briefText(R,lv){
  const b=R.bank,L=S.loan,B=S.biz,cap=R.cap,sch=R.sch,P=PRODUCTS[L.product],lender=L.lender||'the bank',name=B.name||'our business';
  const lines=[];
  lines.push(`TALKING POINTS: ${name} and ${lender}`,`${P.label}, ${money(L.amount)}`,'');
  lines.push('OUR PROFILE');
  lines.push(`- ${B.years} years in business, ${money(B.revenue)} revenue, ${money(B.ebitda)} EBITDA`);
  lines.push(`- Debt service coverage after this loan: ${x2(cap.dscr)}. Debt to EBITDA: ${x2(cap.lev)}`);
  if(COLLATERAL[B.collType][1]>0)lines.push(`- Collateral: ${COLLATERAL[B.collType][0].toLowerCase()}, about ${money(B.collValue)}`);
  lines.push('');
  if(b.na){lines.push('WHAT WE ARE ASKING',`- A term loan or line of credit to replace an MCA priced at ${pct(sch.apr,0)} APR`);return lines.join('\n')}
  lines.push('WHAT WE ARE ASKING');
  if(b.negotiable>0)lines.push(`- Rate: ${INDEXES[L.index].split(' ')[0]} + ${Math.round((b.opening-b.idx)*100)} bps (offered: + ${L.spreadBps} bps)`);
  else lines.push(`- Rate: we accept the offered spread of ${L.spreadBps} bps, subject to the terms below`);
  lv.filter(l=>l.kind==='fee').forEach(l=>lines.push('- '+l.ask));
  lv.filter(l=>l.kind==='terms').forEach(l=>lines.push('- '+l.ask));
  const give=lv.filter(l=>l.kind==='rate'&&l.bps>0&&!/competing/i.test(l.title));
  if(give.length){lines.push('','WHAT WE CAN OFFER IN RETURN');give.forEach(l=>lines.push('- '+l.ask))}
  const comp=lv.find(l=>/competing/i.test(l.title));
  if(comp){lines.push('','COMPETING OFFER',`- ${S.lev.competeName||'Another lender'} has offered ${pct(S.lev.competeRate)}. We prefer to stay with ${lender} if you can come close.`)}
  lines.push('','OUR LIMITS (DO NOT SHARE)',`- Target: about ${pct(b.landing)}. Their walk-away is probably near ${pct(b.walkaway)}.`,`- True cost of the current offer: ${pct(sch.apr)} APR, ${money(sch.totalCost)} in interest and fees over the term.`);
  return lines.join('\n');
}

/* ---------- Compare ---------- */
function renderCompareShell(){
  const f=i=>[{p:`offers.${i}.name`,label:'Lender',type:'text',wide:true},{p:`offers.${i}.amount`,label:'Amount',type:'money',step:5000},
    {p:`offers.${i}.rate`,label:'Interest rate',type:'num',suf:'%',step:.05},{p:`offers.${i}.termY`,label:'Term',type:'num',suf:'yrs'},
    {p:`offers.${i}.amortY`,label:'Payment schedule',type:'num',suf:'yrs'},{p:`offers.${i}.origPct`,label:'Origination fee',type:'num',suf:'%',step:.05},
    {p:`offers.${i}.closing`,label:'Closing costs',type:'money',step:500},{p:`offers.${i}.annualFee`,label:'Annual fee',type:'money',step:100}];
  $('#view-compare').innerHTML=`<div class="card"><div class="row" style="justify-content:space-between"><div><h2>Compare offers side by side</h2><p class="lede" style="margin:4px 0 0">Enter up to three quotes as fixed-rate term loans. The lowest rate is not always the cheapest loan.</p></div><button class="btn" id="copy-offer" type="button">Copy my current offer into Offer 1</button></div>
    <div class="offers" style="margin-top:14px">${[0,1,2].map(i=>`<div class="offer"><div class="fields">${f(i).map(x=>fieldHTML(x,S)).join('')}</div><div id="offer-out-${i}"></div></div>`).join('')}</div></div>
    <div class="card"><h3>Total cost over each loan's term (interest + fees)</h3><div id="cmp-bars" style="margin-top:10px"></div><p class="small muted" id="cmp-note" style="margin:10px 0 0"></p></div>`;
}
function renderCompare(){
  const res=S.offers.map(o=>({o,s:o.rate>0&&o.amount>0?offerSchedule(S,o):null}));
  const valid=res.filter(r=>r.s);const best=valid.length?valid.reduce((a,b)=>b.s.apr<a.s.apr?b:a):null;
  res.forEach((r,i)=>{$('#offer-out-'+i).innerHTML=r.s?`<table class="small"><tbody>
    <tr><td>Monthly payment</td><td class="r num">${money(r.s.payment)}</td></tr>
    <tr><td>APR</td><td class="r num"><b>${pct(r.s.apr)}</b> ${r===best&&valid.length>1?'<span class="pill good">Lowest</span>':''}</td></tr>
    <tr><td>Total cost</td><td class="r num">${money(r.s.totalCost)}</td></tr>
    <tr><td>Balloon</td><td class="r num">${r.s.balloon>1?money(r.s.balloon):'none'}</td></tr></tbody></table>`:'<p class="small muted">Enter a rate and amount.</p>'});
  const mx=Math.max(1,...valid.map(r=>r.s.totalCost));
  $('#cmp-bars').innerHTML=valid.map(r=>`<div class="cbar"><div class="t" title="${esc(r.o.name)}">${esc(r.o.name)}</div><div class="b"><div class="f" style="width:${r.s.totalCost/mx*82}%" title="${esc(r.o.name)}: ${money(r.s.totalCost)} over ${r.o.termY} yrs, ${pct(r.s.apr)} APR"></div><span style="left:${r.s.totalCost/mx*82}%">${moneyShort(r.s.totalCost)} · ${pct(r.s.apr)}</span></div></div>`).join('')||'<p class="small muted">No offers yet.</p>';
  const terms=new Set(valid.map(r=>r.o.termY));
  $('#cmp-note').textContent=terms.size>1?'These loans have different terms, so total cost is not a like-for-like comparison. Use APR to compare the cost of the money, and weigh the monthly payment and any balloon against your cash flow.':'Same term for every offer, so total cost and APR point the same way.';
}

/* ---------- Learn ---------- */
function renderLearn(){
  const g=[
    ['Interest rate vs APR','The rate is what the loan charges on its balance. APR adds fees and shows the true annual cost. Always compare offers by APR.'],
    ['Index + spread','Floating rates are an index (SOFR or Prime) plus a spread in basis points. The index moves with the market. The spread is the part you negotiate.'],
    ['SOFR forward curve','The market\'s expected path for SOFR over the coming years. A floating-rate payment follows that path, so the average rate over the loan can differ from today\'s rate.'],
    ['Basis point (bp)','One hundredth of a percent. 25 bps = 0.25%. On $1M, 25 bps is $2,500 a year.'],
    ['Amortization vs term','The payment schedule sets your payment. The term sets when the loan is due. If the schedule is longer than the term, a balloon is due at the end.'],
    ['DSCR','Debt service coverage ratio: cash flow divided by all loan payments. Banks usually want 1.25x or more, meaning $1.25 of cash flow for every $1 of payments.'],
    ['Leverage','Total debt divided by EBITDA. Above about 3.5x, most banks tighten terms or say no.'],
    ['Covenants','Promises in the loan agreement, such as keeping DSCR above 1.25x. Breaking one can bring fees, a higher rate or a demand to repay, even if you never miss a payment.'],
    ['Personal guarantee','The owner is personally liable if the business cannot pay. It can often be capped or released over time.'],
    ['Prepayment penalty','A fee for paying the loan off early. Step-downs (3-2-1%) are milder than yield maintenance, which can be very expensive when rates fall.'],
    ['Unused fee','On a line of credit, a fee charged on the part you do not draw. Asking for a bigger line than you need costs money.'],
    ['RAROC and the hurdle','Risk-adjusted return on capital. Banks must hold capital against every loan and want it to earn a target return, around 12%. This sets the lowest rate they can accept.'],
    ['Why deposits matter','Your operating deposits are cheap funding for the bank. A bank will often take less on the loan to win the whole relationship.'],
  ];
  $('#view-learn').innerHTML=`<div class="card"><h2>Key terms</h2><p class="lede">What the words on your term sheet mean.</p><div class="gloss">${g.map(([t,d])=>`<div><b>${t}</b><p>${d}</p></div>`).join('')}</div></div>
  <div class="two">
    <div class="card"><h2>How to negotiate a business loan</h2><ol class="steps" style="margin-top:8px">
      <li><b>Get at least two quotes.</b> A real competing term sheet is your strongest tool.</li>
      <li><b>Know your numbers first.</b> DSCR, leverage and collateral coverage are what the credit officer will look at.</li>
      <li><b>Negotiate the whole deal, not just the rate.</b> Fees, covenants, the guarantee and the prepayment penalty can be worth more.</li>
      <li><b>Offer the relationship.</b> Deposits and treasury services lower the rate the bank needs.</li>
      <li><b>Ask for everything in writing</b> before you move accounts or pay deposits.</li>
      <li><b>Know your walk-away</b> and your alternative (another lender, SBA, a smaller loan) before the call.</li></ol></div>
    <div class="card"><h2>What the bank will ask for</h2><ol class="steps" style="margin-top:8px">
      <li>Business tax returns for the last 3 years</li><li>Year-to-date income statement and balance sheet</li>
      <li>Receivables and payables aging reports</li><li>A list of current debts, with balances and payments</li>
      <li>Personal financial statement and tax returns for each owner with 20% or more</li>
      <li>Projections and what the money is for</li><li>Details on collateral: appraisals, equipment lists, titles</li></ol></div>
  </div>
  <div class="card"><h2>How this engine estimates the bank's price</h2><p class="lede">It mirrors a typical commercial bank pricing model. The bank's required income on the loan is:</p>
    <p class="mono small" style="background:var(--surface-2);padding:12px 14px;border-radius:10px;overflow-x:auto;white-space:nowrap">Required income = Hurdle × Capital ÷ (1 − tax) − credit on capital + servicing cost + expected loss − value of your deposits and services</p>
    <p class="small" style="margin:0">Expected loss is probability of default (from your estimated rating) × loss given default (from collateral and the guarantee) × exposure. Capital is the higher of the Basel IRB corporate formula and a regulatory minimum (10% of the loan by default), which is how most banks that lend to small businesses price. Lines of credit count 75% of the unused amount as exposure. For SBA 7(a) loans, the guaranteed share carries very little risk for the bank. Every bank's model is different, so treat the results as a guide to your room to negotiate, not an exact number.</p></div>`;
}

/* ============================================================
   WIRING
   ============================================================ */
let lastR=null;
function recompute(){lastR=run(S);drawCurve();renderKPIs(lastR);renderCost(lastR);renderAfford(lastR);renderBank(lastR);renderNegotiate(lastR);renderCompare()}
function onInput(e){const el=e.target;if(!el.dataset||!el.dataset.p)return;const p=readInput(el,S);if(!p)return;
  if(p==='loan.product'){applyProductDefaults(S.loan.product);renderInputs();}
  else if(p==='loan.index'||p==='biz.collType'||p==='mkt.useCurve')syncVisibility();
  syncVisibility();save();recompute();}
document.addEventListener('input',e=>{if(e.target.tagName!=='SELECT')onInput(e)});
document.addEventListener('change',e=>{if(e.target.tagName==='SELECT'||e.target.type==='checkbox')onInput(e)});
document.addEventListener('click',e=>{
  const t=e.target.closest('[data-tab]');if(t){setTab(t.dataset.tab);return}
  if(e.target.id==='copy-brief'){const txt=$('#brief').textContent,btn=e.target;
    const done=ok=>{btn.textContent=ok?'Copied':'Select and copy';setTimeout(()=>btn.textContent='Copy',1800)};
    try{navigator.clipboard.writeText(txt).then(()=>done(true),()=>{selectEl($('#brief'));done(false)})}catch(err){selectEl($('#brief'));done(false)}}
  if(e.target.id==='copy-offer'){const L=S.loan,sch=lastR.sch;if(isMca(S)||isRev(S))return;
    Object.assign(S.offers[0],{name:L.lender||'Current offer',amount:L.amount,rate:+sch.rate.toFixed(3),termY:L.termY,amortY:L.amortY,origPct:L.origPct,closing:L.closingCost,annualFee:L.annualFee});
    save();renderCompareShell();renderCompare()}
  if(e.target.id==='btn-example'){S=clone(EXAMPLE);save();boot()}
  if(e.target.id==='btn-clear'){S=clone(BLANK);save();boot()}
});
document.addEventListener('toggle',e=>{if(e.target.id==='assume-d'&&e.target.open)drawCurve()},true);
document.addEventListener('keydown',e=>{const t=e.target.closest?.('[role=tab]');if(!t)return;
  if(e.key==='ArrowRight'||e.key==='ArrowLeft'){const i=TABS.findIndex(x=>x[0]===t.dataset.tab),n=(i+(e.key==='ArrowRight'?1:-1)+TABS.length)%TABS.length;setTab(TABS[n][0]);$('#tab-'+TABS[n][0]).focus();e.preventDefault()}});
function selectEl(el){const r=document.createRange();r.selectNodeContents(el);const s=getSelection();s.removeAllRanges();s.addRange(r)}
let rz;window.addEventListener('resize',()=>{clearTimeout(rz);rz=setTimeout(()=>{if(lastR){drawAmort(lastR.sch);drawRatePath(lastR.sch);drawCurve()}},120)});
function boot(){
  const isEx=S.biz.name===EXAMPLE.biz.name;$('#example-note').hidden=!isEx;
  renderInputs();renderTabs();recompute();
}
(function init(){
  const h=(location.hash||'').slice(1);let saved=null;try{saved=localStorage.getItem(STORE_KEY+'-tab')}catch(e){}
  if(TABS.some(t=>t[0]===h))activeTab=h;else if(TABS.some(t=>t[0]===saved))activeTab=saved;
  boot();
})();
