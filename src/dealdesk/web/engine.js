/* Borrower's Deal Desk: browser engine.
 * A line-for-line port of src/dealdesk/engine.py, tested for parity by tests/test_js_parity.py.
 * Loads as a browser global (window.DealEngine) or a CommonJS module (Node).
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.DealEngine = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /* ============================================================
     REFERENCE DATA (must match src/dealdesk/config.py)
     ============================================================ */
  const PRODUCTS = {
    term:   {label:"Term loan", termY:5, amortY:7, index:"sofr", spread:300, orig:1.0,
             blurb:"A lump sum repaid on a fixed schedule. Used for expansion, acquisitions and refinancing."},
    loc:    {label:"Line of credit (revolver)", rev:true, termY:2, index:"prime", spread:75, orig:0.5, unused:25, util:40,
             blurb:"Draw and repay as needed. You pay interest on what you use and a fee on the unused part."},
    equip:  {label:"Equipment loan", termY:5, amortY:5, index:"ust5", spread:325, orig:0.5,
             blurb:"Pays for a machine or vehicle, and that equipment is the collateral. The term usually matches its useful life."},
    cre:    {label:"Commercial real estate mortgage", termY:10, amortY:25, index:"ust5", spread:250, orig:0.75,
             blurb:"To buy or refinance property. Usually a 5 to 10 year term on a 20 to 25 year schedule, so a large final payment (balloon) comes due."},
    sba7a:  {label:"SBA 7(a) loan", termY:10, amortY:10, index:"prime", spread:275, orig:0, sbaFee:2.5,
             blurb:"A bank loan backed 75 to 85% by a federal guarantee. Longer terms and less collateral needed, but more paperwork and a guarantee fee. SBA caps the spread over Prime."},
    sba504: {label:"SBA 504 loan", termY:20, amortY:20, index:"ust5", spread:225, orig:0.5, sbaFee:2.2,
             blurb:"For real estate or major equipment. Typically the bank funds 50%, a CDC 40% and you 10%. Long fixed rates. Modeled here as one blended loan."},
    invoice:{label:"Invoice / receivables financing", rev:true, termY:1, index:"prime", spread:300, orig:1.0, unused:0, util:70,
             blurb:"An advance of about 80% of what customers owe you. Fast and grows with sales, but priced higher."},
    mca:    {label:"Merchant cash advance", mca:true, termY:1, factor:1.35, months:9, orig:2.5,
             blurb:"Not a loan. You sell future sales for a lump sum and repay daily. Often the most expensive money a business can take, so check the APR before signing."}
  };
  const INDUSTRIES = {
    prof:["Professional services",0], health:["Healthcare practice",0], tech:["Technology / software",0],
    mfg:["Manufacturing",0], dist:["Wholesale / distribution",0], constr:["Construction / trades",1],
    trans:["Transportation / logistics",1], retail:["Retail",1], rest:["Restaurant / hospitality",1],
    ag:["Agriculture",1], energy:["Energy / oil and gas",2]
  };
  const COLLATERAL = { // [label, advance rate, secured LGD]
    none:["None (unsecured)",0,0.45], blanket:["Receivables and inventory (blanket lien)",0.65,0.32],
    equip:["Equipment and vehicles",0.80,0.30], re:["Real estate",0.75,0.35], cash:["Cash or CDs",0.95,0.05]
  };
  const INDEXES = {sofr:"SOFR (floating)", prime:"Prime (floating)", ust5:"5-yr Treasury (fixed)"};
  const PREPAY = {none:"None", step:"Step-down (e.g. 3-2-1%)", ym:"Yield maintenance / make-whole"};
  const PD_BY_RATING = [null,0.0003,0.0006,0.0015,0.003,0.005,0.009,0.016,0.035,0.07,0.15];
  const DSCR_MIN = 1.25, LEVERAGE_MAX = 3.5, REVOLVER_CCF = 0.75, EC_MULTIPLIER = 1.06,
        GOV_GUARANTEE_CAPITAL = 0.016, TREASURY_MARGIN = 0.45, UNSECURED_LGD = 0.45, PG_LGD_BENEFIT = 0.03;

  const EXAMPLE = {
    loan:{product:"term", lender:"First Harbor Bank", amount:1200000, termY:5, amortY:7, index:"sofr", spreadBps:325,
          utilPct:40, unusedBps:25, mcaFactor:1.35, mcaMonths:9, origPct:1.0, closingCost:7500, annualFee:0,
          sbaFeePct:2.5, prepay:"step", covDSCR:1.25},
    biz:{name:"Cedar & Pine Millwork", industry:"mfg", years:12, revenue:6200000, ebitda:850000, existingDebt:900000,
         existingDS:240000, fico:735, pg:true, collType:"blanket", collValue:1400000,
         deposits:150000, depositRate:0.25, treasuryFees:4000},
    mkt:{sofr:3.65, prime:6.75, ust5:3.75},
    assume:{hurdle:12, tax:24, capRate:3.85, liqBps:25, opexBps:45, fixedCost:4000, runoff:25, minCap:10},
    lev:{moreDeposits:400000, moreTreasury:9000, competeRate:6.60, competeName:"Lakeside Community Bank"},
    offers:[
      {name:"First Harbor Bank", amount:1200000, rate:6.90, termY:5, amortY:7, origPct:1.0, closing:7500, annualFee:0},
      {name:"Lakeside Community Bank", amount:1200000, rate:6.60, termY:5, amortY:7, origPct:1.5, closing:9000, annualFee:1500},
      {name:"Online lender", amount:1200000, rate:9.75, termY:3, amortY:3, origPct:3.0, closing:0, annualFee:0}
    ]
  };
  const clone = o => JSON.parse(JSON.stringify(o));
  const BLANK = clone(EXAMPLE);
  Object.assign(BLANK.loan, {lender:"", amount:250000, closingCost:0});
  Object.assign(BLANK.biz, {name:"", years:5, revenue:1000000, ebitda:150000, existingDebt:0, existingDS:0, fico:700, pg:true,
    collType:"none", collValue:0, deposits:0, treasuryFees:0});
  Object.assign(BLANK.lev, {moreDeposits:50000, moreTreasury:2000, competeRate:0, competeName:""});
  BLANK.offers = BLANK.offers.map((o, i) => ({name:["Offer A","Offer B","Offer C"][i], amount:250000, rate:0, termY:5, amortY:5,
    origPct:0, closing:0, annualFee:0}));

  /* ============================================================
     FORMATTING
     ============================================================ */
  function money(v, dec = 0) {
    if (!isFinite(v)) return "—";
    const neg = v < 0; v = Math.abs(v);
    return (neg ? "−" : "") + "$" + v.toLocaleString("en-US", {minimumFractionDigits:dec, maximumFractionDigits:dec});
  }
  function moneyShort(v) {
    if (!isFinite(v)) return "—";
    const a = Math.abs(v), s = v < 0 ? "−" : "";
    if (a >= 1e6) return s + "$" + (a / 1e6).toFixed(a >= 1e7 ? 1 : 2).replace(/\.?0+$/, "") + "M";
    if (a >= 1e3) return s + "$" + Math.round(a / 1e3) + "K";
    return s + "$" + Math.round(a);
  }
  const pct = (v, d = 2) => isFinite(v) ? v.toFixed(d) + "%" : "—";
  const bps = v => isFinite(v) ? Math.round(v) + " bps" : "—";
  const x2 = v => isFinite(v) ? v.toFixed(2) + "x" : "—";

  /* ============================================================
     MATH: normal distribution, Basel IRB capital, IRR
     ============================================================ */
  function ncdf(x) {
    const t = 1 / (1 + 0.2316419 * Math.abs(x)), d = 0.3989422804 * Math.exp(-x * x / 2);
    const p = d * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
    return x > 0 ? 1 - p : p;
  }
  function ninv(p) {
    const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239],
      b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572],
      c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783],
      d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416], pl = 0.02425;
    let q, r;
    if (p < pl) {
      q = Math.sqrt(-2 * Math.log(p));
      return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    }
    if (p <= 1 - pl) {
      q = p - 0.5; r = q * q;
      return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
    }
    q = Math.sqrt(-2 * Math.log(1 - p));
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  function irbK(pd, lgd, M) {
    pd = Math.min(Math.max(pd, 0.0003), 0.9999);
    const e = (1 - Math.exp(-50 * pd)) / (1 - Math.exp(-50)), R = 0.12 * e + 0.24 * (1 - e);
    const b = Math.pow(0.11852 - 0.05478 * Math.log(pd), 2);
    const k = (lgd * ncdf((ninv(pd) + Math.sqrt(R) * 3.090232) / Math.sqrt(1 - R)) - pd * lgd) * (1 + (M - 2.5) * b) / (1 - 1.5 * b);
    return Math.max(k, 0);
  }
  // Periodic IRR by bisection: net = sum cf_t / (1+i)^t, t = 1..n
  function irr(net, cfs) {
    const f = i => { let s = 0, df = 1; for (let t = 0; t < cfs.length; t++) { df /= (1 + i); s += cfs[t] * df; } return s - net; };
    if (net <= 0 || f(0) <= 0) return 0;
    let lo = 0, hi = 1;
    for (let k = 0; k < 90; k++) { const m = (lo + hi) / 2; if (f(m) > 0) lo = m; else hi = m; }
    return (lo + hi) / 2;
  }

  /* ============================================================
     ENGINE 1: payment schedule, true cost (APR)
     ============================================================ */
  const indexRate = (s, idx) => ({sofr:s.mkt.sofr, prime:s.mkt.prime, ust5:s.mkt.ust5})[idx] || 0;
  const statedRate = (s, L = s.loan) => indexRate(s, L.index) + L.spreadBps / 100;
  const sbaGuarPct = L => L.product === "sba7a" ? (L.amount <= 150000 ? 0.85 : 0.75) : 0;
  function upfrontFees(L) {
    let f = L.amount * L.origPct / 100 + L.closingCost;
    if (L.product === "sba7a") f += L.amount * sbaGuarPct(L) * L.sbaFeePct / 100;
    if (L.product === "sba504") f += L.amount * L.sbaFeePct / 100;
    return f;
  }

  function schedule(s, L = s.loan) {
    const P = PRODUCTS[L.product], A = Math.max(0, L.amount), out = {rows:[], balloon:0};
    const upfront = upfrontFees(L); out.upfront = upfront;
    if (P.mca) {
      const months = Math.max(1, L.mcaMonths), N = Math.max(1, Math.round(months * 21)), total = A * L.mcaFactor, pay = total / N;
      const i = irr(A - upfront, new Array(N).fill(pay));
      let paid = 0;
      for (let m = 1; m <= Math.ceil(months); m++) {
        const days = Math.min(21, N - (m - 1) * 21); if (days <= 0) break;
        const amt = pay * days; paid += amt; const intPart = amt * (L.mcaFactor - 1) / L.mcaFactor;
        out.rows.push({m, pay:amt, int:intPart, prin:amt - intPart, fee:0, bal:Math.max(0, total - paid), start:total - paid + amt});
      }
      Object.assign(out, {rate:NaN, apr:i * 252 * 100, net:A - upfront, payment:pay * 21, daily:pay, totalInterest:A * (L.mcaFactor - 1),
        totalFees:upfront, firstYearDS:Math.min(total, pay * 252), avgBal:A / 2, months:months, drawn:A});
    } else if (P.rev) {
      const rate = statedRate(s, L), r = rate / 1200, T = Math.max(1, Math.round(L.termY * 12)), drawn = A * L.utilPct / 100;
      const cfs = []; let ti = 0, tf = 0;
      for (let m = 1; m <= T; m++) {
        const int = drawn * r, unused = (A - drawn) * L.unusedBps / 1e4 / 12, fee = L.annualFee / 12;
        const pay = int + unused + fee; ti += int; tf += unused + fee; cfs.push(pay + (m === T ? drawn : 0));
        out.rows.push({m, pay, int, prin:0, fee:unused + fee, bal:drawn, start:drawn});
      }
      const i = irr(drawn - upfront, cfs);
      Object.assign(out, {rate, apr:i * 1200, net:drawn - upfront, payment:out.rows[0] ? out.rows[0].pay : 0, totalInterest:ti,
        totalFees:tf + upfront, firstYearDS:out.rows.slice(0, 12).reduce((a, r) => a + r.pay, 0) * (12 / Math.min(12, T)),
        avgBal:drawn, months:T, drawn, balloon:drawn});
    } else {
      const rate = statedRate(s, L), r = rate / 1200, n = Math.max(1, Math.round(L.amortY * 12)),
        T = Math.max(1, Math.round(Math.min(L.termY, L.amortY) * 12));
      const pmt = r ? A * r / (1 - Math.pow(1 + r, -n)) : A / n;
      let bal = A, ti = 0, tf = 0, sumBal = 0; const cfs = [];
      for (let m = 1; m <= T; m++) {
        const start = bal, int = bal * r, prin = Math.min(bal, pmt - int); bal -= prin; const fee = L.annualFee / 12;
        ti += int; tf += fee; sumBal += start; let cf = int + prin + fee;
        if (m === T && bal > 0.5) { out.balloon = bal; cf += bal; }
        cfs.push(cf);
        out.rows.push({m, pay:int + prin + fee, int, prin, fee, bal:m === T && out.balloon ? out.balloon : bal, start});
      }
      const i = irr(A - upfront, cfs);
      Object.assign(out, {rate, apr:i * 1200, net:A - upfront, payment:pmt + L.annualFee / 12, totalInterest:ti, totalFees:tf + upfront,
        firstYearDS:(pmt + L.annualFee / 12) * 12, avgBal:sumBal / T, months:T, drawn:A});
    }
    out.totalCost = out.totalInterest + out.totalFees;
    return out;
  }

  /* ============================================================
     ENGINE 2: affordability and borrowing capacity
     ============================================================ */
  function capacity(s, sch) {
    const B = s.biz, L = s.loan, eb = Math.max(1, B.ebitda), totDS = B.existingDS + sch.firstYearDS;
    const dscr = B.ebitda / Math.max(1, totDS), lev = (B.existingDebt + L.amount) / eb;
    const perDollar = L.amount > 0 ? sch.firstYearDS / L.amount : 0;
    const maxDSCR = perDollar > 0 ? Math.max(0, B.ebitda / DSCR_MIN - B.existingDS) / perDollar : NaN;
    const maxLev = Math.max(0, LEVERAGE_MAX * B.ebitda - B.existingDebt);
    const adv = COLLATERAL[B.collType][1], maxColl = adv > 0 ? adv * B.collValue : NaN;
    const cands = [["cash flow (1.25x DSCR)", maxDSCR], ["leverage (3.5x EBITDA)", maxLev], ["collateral", maxColl]].filter(c => isFinite(c[1]));
    cands.sort((a, b) => a[1] - b[1]);
    const collCov = L.amount > 0 && adv > 0 ? adv * B.collValue / L.amount : 0;
    const cushion = dscr > 0 ? 1 - L.covDSCR / dscr : NaN;
    return {dscr, lev, maxDSCR, maxLev, maxColl, binding:cands[0] || null, collCov, cushion, totDS, newDS:sch.firstYearDS};
  }
  function eligibility(s, cap) {
    const B = s.biz, out = [], d = cap.dscr;
    const add = (k, status, why) => out.push({k, label:PRODUCTS[k].label, status, why});
    const hasRE = B.collType === "re", hasAR = B.collType === "blanket";
    if (d >= 1.25 && B.years >= 2 && B.fico >= 660) add("term", "good", "Cash flow, history and credit meet common bank standards.");
    else if (d >= 1.1 && B.years >= 2) add("term", "warn", "Possible, but expect tighter terms or a smaller amount.");
    else add("term", "bad", B.years < 2 ? "Most banks want 2 or more years in business." : "Cash flow does not cover the debt with enough cushion.");
    if (B.years >= 2 && B.revenue >= 250000 && (hasAR || d >= 1.5)) add("loc", "good", "Receivables or strong cash flow support a working capital line.");
    else if (B.years >= 1) add("loc", "warn", "Likely a smaller line, often with a personal guarantee.");
    else add("loc", "bad", "Lines usually need at least a year of operating history.");
    add("equip", d >= 1.15 && B.years >= 1 ? "good" : "warn", "The equipment secures itself, so these are easier to get. Lenders advance about 80 to 100% of cost.");
    if (hasRE && d >= 1.2) add("cre", "good", "You have real estate and the cash flow to support it.");
    else add("cre", hasRE ? "warn" : "bad", hasRE ? "Cash flow is thin for a property loan." : "Only fits if you are buying or own property.");
    if (B.fico >= 650 && d >= 1.15) add("sba7a", (B.years < 2 || cap.collCov < 1) ? "good" : "warn",
      (B.years < 2 || cap.collCov < 1) ? "Built for your gap: short history or not enough collateral." : "You may qualify for a conventional loan. SBA adds fees and paperwork.");
    else add("sba7a", "bad", "SBA lenders still need cash flow of about 1.15x and fair credit.");
    add("sba504", (hasRE || B.collType === "equip") && d >= 1.15 ? "good" : "warn", "Only for fixed assets like buildings or major equipment. Needs about 10% down.");
    add("invoice", hasAR ? "good" : "warn", hasAR ? "You sell on terms to other businesses, which is what this finances." : "Only works if customers pay you on invoice terms.");
    add("mca", "warn", "Almost always available, and almost always the most expensive. Treat it as a last resort.");
    return out;
  }

  /* ============================================================
     ENGINE 3: the bank's view (mirror of a bank RAROC pricing model)
     ============================================================ */
  function riskRating(s, cap) {
    const B = s.biz, drivers = []; let r = 6; // small and mid-size businesses start below investment grade
    const push = (name, val, delta) => { r += delta; drivers.push({name, val, delta}); };
    const d = cap.dscr; push("Debt service coverage", x2(d), d >= 2 ? -2 : d >= 1.5 ? -1 : d >= 1.25 ? 0 : d >= 1.1 ? 1 : d >= 1 ? 2 : 3);
    const l = cap.lev; push("Debt to EBITDA", x2(l), l <= 1.5 ? -1 : l <= 3 ? 0 : l <= 4 ? 1 : 2);
    push("Years in business", B.years + " yrs", B.years >= 10 ? -1 : B.years >= 3 ? 0 : B.years >= 2 ? 1 : 2);
    push("Owner credit score", String(B.fico), B.fico >= 760 ? -1 : B.fico >= 680 ? 0 : B.fico >= 640 ? 1 : 2);
    const ind = INDUSTRIES[B.industry]; push("Industry risk", ind[0], ind[1]);
    const rating = Math.min(9, Math.max(2, Math.round(r)));
    return {rating, pd:PD_BY_RATING[rating], drivers};
  }
  function lossGivenDefault(s) {
    const B = s.biz, L = s.loan, c = COLLATERAL[B.collType];
    if (L.product === "sba504") return 0.15;
    const cov = L.amount > 0 ? Math.min(1, c[1] * B.collValue / L.amount) : 0;
    let lgd = cov * c[2] + (1 - cov) * UNSECURED_LGD;
    if (B.pg) lgd -= PG_LGD_BENEFIT;
    return Math.max(0.05, lgd);
  }
  function bankView(s, sch) {
    const L = s.loan, B = s.biz, A = s.assume, P = PRODUCTS[L.product];
    if (P.mca) return {na:true};
    const cap = capacity(s, sch), rr = riskRating(s, cap), lgd = lossGivenDefault(s);
    const idx = indexRate(s, L.index), cof = L.index === "prime" ? s.mkt.sofr : idx; // Prime loans are still funded at market (SOFR-like) rates
    const liq = A.liqBps / 100, h = A.hurdle / 100, t = A.tax / 100, cr = A.capRate / 100;
    const drawn = Math.max(1, P.rev ? L.amount * L.utilPct / 100 : L.amount);
    const ead = P.rev ? drawn + REVOLVER_CCF * (L.amount - drawn) : L.amount;
    const g = sbaGuarPct(L), M = Math.min(5, Math.max(1, L.termY));
    const K = irbK(rr.pd, lgd, M);
    const ecIRB = EC_MULTIPLIER * K * ead * (1 - g) + GOV_GUARANTEE_CAPITAL * ead * g;
    const ecReg = A.minCap / 100 * ead * (1 - g) + GOV_GUARANTEE_CAPITAL * ead * g;
    const EC = Math.max(ecIRB, ecReg); // banks price to the higher of economic and regulatory capital
    const EL = rr.pd * lgd * ead * (1 - g);
    const opex = A.opexBps / 1e4 * ead + A.fixedCost;
    const fees = L.amount * L.origPct / 100 / Math.max(1, L.termY) + L.annualFee + (P.rev ? L.unusedBps / 1e4 * (L.amount - drawn) : 0);
    const niiReq = h * EC / (1 - t) - cr * EC + opex + EL;
    const depVal = B.deposits * Math.max(0, cof / 100 - B.depositRate / 100) * (1 - A.runoff / 100);
    const tsVal = B.treasuryFees * TREASURY_MARGIN;
    const relInc = depVal + tsVal;
    const rateFrom = nii => cof + liq + (nii - fees) / drawn * 100;
    const standalone = rateFrom(niiReq);
    const relFloor = rateFrom(niiReq - relInc);
    const costFloor = cof + liq + Math.max(0, EL + opex - fees) / drawn * 100;
    const walkaway = Math.max(costFloor, relFloor);
    const offered = sch.rate;
    const niiAt = rate => (rate - cof - liq) / 100 * drawn + fees;
    const raroc = (rate, rel) => ((niiAt(rate) + (rel ? relInc : 0)) - opex - EL + cr * EC) * (1 - t) / EC * 100;
    const room = offered - walkaway;
    return {na:false, cap, rr, lgd, idx, cof, liq, drawn, ead, g, K, EC, ecIRB, ecReg, EL, opex, fees, niiReq, depVal, tsVal, relInc,
      standalone, relFloor, costFloor, walkaway, offered, room,
      rarocStand:raroc(offered, false), rarocRel:raroc(offered, true),
      opening:walkaway + Math.max(0, room) * 0.25, landing:walkaway + Math.max(0, room) * 0.5,
      revenueAtOffer:niiAt(offered)};
  }
  function run(s) { const sch = schedule(s), cap = capacity(s, sch), bank = bankView(s, sch); return {sch, cap, bank}; }

  /* ============================================================
     ENGINE 4: negotiation levers (re-run the engine with each change)
     ============================================================ */
  function levers(s, R) {
    const out = [], L = s.loan, B = s.biz, P = PRODUCTS[L.product], base = R.bank, yrs = Math.max(1, L.termY);
    if (base.na) return out;
    const avgBal = R.sch.avgBal;
    const worth = d => Math.max(0, d) / 1e4 * avgBal * yrs;
    const tryMod = fn => { const t = clone(s); fn(t); const r = run(t); return {r, dFloor:(base.walkaway - r.bank.walkaway) * 100}; };
    if (s.lev.moreDeposits > 0) {
      const m = tryMod(t => { t.biz.deposits += s.lev.moreDeposits; });
      out.push({id:"deposits", kind:"rate", title:"Move operating deposits to this bank",
        ask:`Offer to keep about ${money(s.lev.moreDeposits)} more in operating accounts, and ask for a lower spread in return.`,
        why:`Deposits are cheap funding for the bank, worth roughly ${money(m.r.bank.depVal - base.depVal)} a year to them after run-off. That can lower the rate they need by about ${bps(m.dFloor)}.`,
        bps:m.dFloor, dollars:worth(m.dFloor)});
    }
    if (s.lev.moreTreasury > 0) {
      const m = tryMod(t => { t.biz.treasuryFees += s.lev.moreTreasury; });
      out.push({id:"treasury", kind:"rate", title:"Bring treasury services (payroll, ACH, cards, lockbox)",
        ask:`Move services you already pay for elsewhere, about ${money(s.lev.moreTreasury)} a year in fees.`,
        why:`The bank books fee income at a margin of about 45%. It lowers the loan rate they need by about ${bps(m.dFloor)}. Only do this if their service is as good and the fees are similar.`,
        bps:m.dFloor, dollars:worth(m.dFloor)});
    }
    const c = COLLATERAL[B.collType];
    if (!B.pg) {
      const m = tryMod(t => { t.biz.pg = true; });
      out.push({id:"guarantee", kind:"rate", title:"Offer a limited personal guarantee",
        ask:"Offer a guarantee capped at a set dollar amount or percent, and ask for a lower rate in return.",
        why:`A guarantee lowers the bank's expected loss if the loan defaults. Worth about ${bps(m.dFloor)} to them. Cap it and ask for it to be released once you hit agreed milestones.`,
        bps:m.dFloor, dollars:worth(m.dFloor)});
    } else {
      out.push({id:"guarantee", kind:"terms", title:"Limit or phase out the personal guarantee",
        ask:"Ask for the guarantee to be capped (for example at 50%) or released once debt to EBITDA falls below 2.0x.",
        why:"You are already giving a full guarantee. Limiting it does not lower your payments, but it reduces your personal risk.",
        bps:0, dollars:0});
    }
    if (c[1] > 0 && R.cap.collCov < 1 && L.product !== "sba504") {
      const m = tryMod(t => { t.biz.collValue = Math.max(t.biz.collValue, t.loan.amount / c[1]); });
      out.push({id:"collateral", kind:"rate", title:"Pledge enough collateral to fully cover the loan",
        ask:`Collateral covers ${pct(R.cap.collCov * 100, 0)} of the loan at the bank's advance rate. Offer more to reach 100%.`,
        why:`Full coverage lowers the bank's loss if you default and the capital they must hold. Worth about ${bps(m.dFloor)}.`,
        bps:m.dFloor, dollars:worth(m.dFloor)});
    }
    if (!P.rev && L.termY > 2) {
      const m = tryMod(t => { t.loan.termY = Math.max(1, t.loan.termY - 2); });
      out.push({id:"shorter_term", kind:"rate", title:"Take a shorter term on the same payment schedule",
        ask:`Ask for a ${L.termY - 2}-year term with the same ${L.amortY}-year schedule. Your payment stays the same, and the bank gets its money back sooner.`,
        why:`A shorter term means less capital held and less risk for the bank, worth about ${bps(m.dFloor)}. The catch is that you refinance or pay a balloon sooner.`,
        bps:m.dFloor, dollars:worth(m.dFloor)});
    }
    if (P.rev && L.utilPct < 70) {
      const newAmt = Math.round(L.amount * L.utilPct / 100 * 1.4 / 10000) * 10000;
      const m = tryMod(t => { t.loan.amount = newAmt; t.loan.utilPct = Math.min(100, L.amount * L.utilPct / newAmt); });
      const saved = (L.amount - newAmt) * L.unusedBps / 1e4 * yrs + (L.amount - newAmt) * L.origPct / 100;
      out.push({id:"right_size", kind:"fee", title:"Right-size the line",
        ask:`You expect to use about ${L.utilPct}%. Ask for a ${money(newAmt)} line instead of ${money(L.amount)}.`,
        why:`Unused commitments cost the bank capital but earn it very little. A smaller line saves you about ${money(saved)} in unused and upfront fees and can lower the rate needed by about ${bps(m.dFloor)}.`,
        bps:m.dFloor, dollars:saved + worth(m.dFloor)});
    }
    if (L.origPct > 0) {
      const t = clone(s); t.loan.origPct = L.origPct / 2; const sch2 = schedule(t); const saved = L.amount * L.origPct / 200;
      out.push({id:"fee", kind:"fee", title:"Cut the origination fee in half",
        ask:`Ask for the ${pct(L.origPct, 2)} fee to be reduced to ${pct(L.origPct / 2, 2)}, or waived if you bring deposits.`,
        why:`It saves ${money(saved)} upfront and lowers your APR from ${pct(R.sch.apr)} to ${pct(sch2.apr)}. Banks often give on fees before they give on rate.`,
        bps:(R.sch.apr - sch2.apr) * 100, dollars:saved});
    }
    if (L.prepay !== "none") out.push({id:"prepay", kind:"terms", title:"Remove or soften the prepayment penalty",
      ask:L.prepay === "ym" ? "Ask to replace yield maintenance with a step-down (3-2-1%), or none after year 2." : "Ask for no penalty when you repay from your own cash (not a refinance), or none after year 2.",
      why:"This keeps you free to refinance if rates fall or to pay the loan down early. It costs the bank little on a floating-rate loan.",
      bps:0, dollars:0});
    if (R.cap.cushion < 0.25) out.push({id:"covenant", kind:"terms", title:"Negotiate covenant headroom",
      ask:`Ask for a minimum DSCR covenant of ${(Math.max(1.05, L.covDSCR - 0.1)).toFixed(2)}x instead of ${L.covDSCR.toFixed(2)}x, tested annually rather than quarterly.`,
      why:`Your EBITDA can only drop about ${pct(Math.max(0, R.cap.cushion * 100), 0)} before you breach. A breach can bring fees, a higher rate or a demand to repay.`,
      bps:0, dollars:0});
    else out.push({id:"covenant", kind:"terms", title:"Lock in covenant terms now",
      ask:"Ask for annual testing, a cure period and EBITDA add-backs spelled out in the agreement.",
      why:`You have a comfortable ${pct(R.cap.cushion * 100, 0)} EBITDA cushion over the ${L.covDSCR.toFixed(2)}x covenant. Covenant terms are easiest to get while things look good.`,
      bps:0, dollars:0});
    if (s.lev.competeRate > 0) {
      const gap = (base.offered - s.lev.competeRate) * 100, name = s.lev.competeName || "the other lender";
      const below = s.lev.competeRate < base.walkaway;
      out.push({id:"competing_offer", kind:"rate", title:`Use the competing offer from ${name}`,
        ask:`Share the competing ${pct(s.lev.competeRate)} term sheet in writing and ask them to match or beat it.`,
        why:below ? `It is below this bank's estimated walk-away rate (${pct(base.walkaway)}), so they probably cannot match on rate alone. Ask for fee or structure concessions, or take the other offer if the terms are as good.`
          : `It is above this bank's estimated walk-away rate (${pct(base.walkaway)}), so a match is financially possible for them. It is worth about ${bps(gap)} if they match.`,
        bps:Math.max(0, gap), dollars:worth(gap)});
    }
    out.sort((a, b) => b.dollars - a.dollars);
    return out;
  }

  /* ============================================================
     OFFER COMPARISON (fixed-rate term quotes)
     ============================================================ */
  function offerSchedule(s, o) {
    const t = clone(s);
    Object.assign(t.loan, {product:"term", amount:o.amount, termY:o.termY, amortY:Math.max(o.amortY, o.termY),
      index:"sofr", spreadBps:(o.rate - s.mkt.sofr) * 100, origPct:o.origPct, closingCost:o.closing, annualFee:o.annualFee});
    return schedule(t);
  }

  return {PRODUCTS, INDUSTRIES, COLLATERAL, INDEXES, PREPAY, PD_BY_RATING, EXAMPLE, BLANK, clone,
    money, moneyShort, pct, bps, x2, ncdf, ninv, irbK, irr, indexRate, statedRate, sbaGuarPct, upfrontFees,
    schedule, capacity, eligibility, riskRating, lossGivenDefault, bankView, run, levers, offerSchedule};
});
