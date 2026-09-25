// Runs the browser engine under Node on a list of scenarios and prints the results as JSON.
// Usage: node tests/js_parity.cjs <scenarios.json>
const fs = require("fs");
const path = require("path");
const E = require(path.join(__dirname, "..", "src", "dealdesk", "web", "engine.js"));

const scenarios = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const num = v => (typeof v === "number" && isFinite(v) ? v : null);

const results = scenarios.map(s => {
  const R = E.run(s);
  const out = {
    sch: {apr: R.sch.apr, rate: num(R.sch.rate), payment: R.sch.payment, totalCost: R.sch.totalCost,
          balloon: R.sch.balloon, avgRate: num(R.sch.avgRate), firstYearDS: R.sch.firstYearDS, avgBal: R.sch.avgBal, net: R.sch.net},
    cap: {dscr: R.cap.dscr, lev: R.cap.lev, maxDSCR: num(R.cap.maxDSCR), maxLev: R.cap.maxLev,
          maxColl: num(R.cap.maxColl), collCov: R.cap.collCov, binding: R.cap.binding ? R.cap.binding[0] : null},
    eligibility: E.eligibility(s, R.cap).map(e => [e.k, e.status]),
    bank: R.bank.na ? null : {rating: R.bank.rr.rating, lgd: R.bank.lgd, EC: R.bank.EC, EL: R.bank.EL,
          standalone: R.bank.standalone, relFloor: R.bank.relFloor, costFloor: R.bank.costFloor,
          walkaway: R.bank.walkaway, cof: R.bank.cof, tier: R.bank.tier,
          negotiable: R.bank.negotiable, opening: R.bank.opening, landing: R.bank.landing, rarocStand: R.bank.rarocStand, rarocRel: R.bank.rarocRel},
    levers: E.levers(s, R).map(l => [l.id, l.bps, l.dollars]),
    offers: (s.offers || []).map(o => { const x = E.offerSchedule(s, o); return [x.apr, x.payment, x.totalCost]; }),
  };
  return out;
});

const constants = {PRODUCTS: E.PRODUCTS, INDUSTRIES: E.INDUSTRIES, COLLATERAL: E.COLLATERAL,
  PD_BY_RATING: E.PD_BY_RATING, SCORE_BANDS: E.SCORE_BANDS, EXAMPLE: E.EXAMPLE};
process.stdout.write(JSON.stringify({results, constants}));
