"""The borrower-side deal engine.

Four engines, each a pure function of a scenario dict (see `config.EXAMPLE` for its shape):

1. `schedule`     payment schedule, true cost (APR by IRR) and totals
2. `capacity`     debt service coverage, leverage, collateral coverage and how much can be borrowed
3. `bank_view`    the bank's side: risk rating, expected loss, capital, and the rates it needs to earn
                  its hurdle (the mirror of a bank RAROC pricing model)
4. `levers`       negotiation options, each valued by re-running the engine with the change applied

`web/engine.js` is a line-for-line port used by the browser; tests keep the two in step.
"""

from __future__ import annotations

import copy
import math

from .config import (
    COLLATERAL,
    DSCR_MIN,
    EC_MULTIPLIER,
    GOV_GUARANTEE_CAPITAL,
    INDUSTRIES,
    LEVERAGE_MAX,
    PD_BY_RATING,
    PG_LGD_BENEFIT,
    PRODUCTS,
    REVOLVER_CCF,
    TREASURY_MARGIN,
    UNSECURED_LGD,
)

NAN = float("nan")


def jround(x: float) -> int:
    """JavaScript Math.round (halves round up), so Python and the browser agree."""
    return math.floor(x + 0.5)


def isfinite(x) -> bool:
    return x is not None and math.isfinite(x)


# ---- formatting (used in lever and brief text) ----------------------------------------------
def money(v: float) -> str:
    if not isfinite(v):
        return "—"
    return ("−" if v < 0 else "") + f"${abs(v):,.0f}"


def pct(v: float, d: int = 2) -> str:
    return f"{v:.{d}f}%" if isfinite(v) else "—"


def bps(v: float) -> str:
    return f"{jround(v)} bps" if isfinite(v) else "—"


def x2(v: float) -> str:
    return f"{v:.2f}x" if isfinite(v) else "—"


# ---- math -------------------------------------------------------------------------------------
def ncdf(x: float) -> float:
    t = 1 / (1 + 0.2316419 * abs(x))
    d = 0.3989422804 * math.exp(-x * x / 2)
    p = d * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    return 1 - p if x > 0 else p


_A = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716,
      2.506628277459239]
_B = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572]
_C = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968,
      2.938163982698783]
_D = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416]


def _horner(coeffs: list[float], x: float) -> float:
    acc = coeffs[0]
    for c in coeffs[1:]:
        acc = acc * x + c
    return acc


def ninv(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation)."""
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return _horner(_C, q) / _horner([*_D, 1], q)
    if p <= 1 - pl:
        q = p - 0.5
        r = q * q
        return _horner(_A, r) * q / _horner([*_B, 1], r)
    q = math.sqrt(-2 * math.log(1 - p))
    return -_horner(_C, q) / _horner([*_D, 1], q)


def irb_k(pd: float, lgd: float, m: float) -> float:
    """Basel IRB corporate capital requirement K per $1 of exposure (99.9% confidence)."""
    pd = min(max(pd, 0.0003), 0.9999)
    e = (1 - math.exp(-50 * pd)) / (1 - math.exp(-50))
    r = 0.12 * e + 0.24 * (1 - e)
    b = (0.11852 - 0.05478 * math.log(pd)) ** 2
    k = (lgd * ncdf((ninv(pd) + math.sqrt(r) * 3.090232) / math.sqrt(1 - r)) - pd * lgd) \
        * (1 + (m - 2.5) * b) / (1 - 1.5 * b)
    return max(k, 0.0)


def irr(net: float, cfs: list[float]) -> float:
    """Periodic rate i solving net = sum(cf_t / (1+i)^t), t = 1..n, by bisection on [0, 1]."""
    def f(i: float) -> float:
        s, df = 0.0, 1.0
        for cf in cfs:
            df /= 1 + i
            s += cf * df
        return s - net

    if net <= 0 or f(0) <= 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(90):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---- engine 1: schedule and true cost --------------------------------------------------------
def index_rate(s: dict, idx: str) -> float:
    return {"sofr": s["mkt"]["sofr"], "prime": s["mkt"]["prime"], "ust5": s["mkt"]["ust5"]}.get(idx, 0.0)


def stated_rate(s: dict, loan: dict | None = None) -> float:
    loan = loan or s["loan"]
    return index_rate(s, loan["index"]) + loan["spreadBps"] / 100


def sba_guarantee(loan: dict) -> float:
    if loan["product"] != "sba7a":
        return 0.0
    return 0.85 if loan["amount"] <= 150000 else 0.75


def upfront_fees(loan: dict) -> float:
    f = loan["amount"] * loan["origPct"] / 100 + loan["closingCost"]
    if loan["product"] == "sba7a":
        f += loan["amount"] * sba_guarantee(loan) * loan["sbaFeePct"] / 100
    if loan["product"] == "sba504":
        f += loan["amount"] * loan["sbaFeePct"] / 100
    return f


def schedule(s: dict, loan: dict | None = None) -> dict:
    loan = loan or s["loan"]
    p, a = PRODUCTS[loan["product"]], max(0.0, loan["amount"])
    out: dict = {"rows": [], "balloon": 0.0, "upfront": upfront_fees(loan)}
    upfront = out["upfront"]

    if p.get("mca"):
        months = max(1, loan["mcaMonths"])
        n = max(1, jround(months * 21))
        total = a * loan["mcaFactor"]
        pay = total / n
        i = irr(a - upfront, [pay] * n)
        paid = 0.0
        for m in range(1, math.ceil(months) + 1):
            days = min(21, n - (m - 1) * 21)
            if days <= 0:
                break
            amt = pay * days
            paid += amt
            interest = amt * (loan["mcaFactor"] - 1) / loan["mcaFactor"]
            out["rows"].append({"m": m, "pay": amt, "int": interest, "prin": amt - interest, "fee": 0.0,
                                "bal": max(0.0, total - paid), "start": total - paid + amt})
        out.update(rate=NAN, apr=i * 252 * 100, net=a - upfront, payment=pay * 21, daily=pay,
                   totalInterest=a * (loan["mcaFactor"] - 1), totalFees=upfront,
                   firstYearDS=min(total, pay * 252), avgBal=a / 2, months=months, drawn=a)
    elif p.get("rev"):
        rate = stated_rate(s, loan)
        r = rate / 1200
        t_months = max(1, jround(loan["termY"] * 12))
        drawn = a * loan["utilPct"] / 100
        cfs, ti, tf = [], 0.0, 0.0
        for m in range(1, t_months + 1):
            interest = drawn * r
            unused = (a - drawn) * loan["unusedBps"] / 1e4 / 12
            fee = loan["annualFee"] / 12
            pay = interest + unused + fee
            ti += interest
            tf += unused + fee
            cfs.append(pay + (drawn if m == t_months else 0.0))
            out["rows"].append({"m": m, "pay": pay, "int": interest, "prin": 0.0, "fee": unused + fee,
                                "bal": drawn, "start": drawn})
        i = irr(drawn - upfront, cfs)
        first12 = sum(row["pay"] for row in out["rows"][:12])
        out.update(rate=rate, apr=i * 1200, net=drawn - upfront, payment=out["rows"][0]["pay"],
                   totalInterest=ti, totalFees=tf + upfront,
                   firstYearDS=first12 * (12 / min(12, t_months)), avgBal=drawn, months=t_months,
                   drawn=drawn, balloon=drawn)
    else:
        rate = stated_rate(s, loan)
        r = rate / 1200
        n = max(1, jround(loan["amortY"] * 12))
        t_months = max(1, jround(min(loan["termY"], loan["amortY"]) * 12))
        pmt = a * r / (1 - (1 + r) ** -n) if r else a / n
        bal, ti, tf, sum_bal, cfs = a, 0.0, 0.0, 0.0, []
        for m in range(1, t_months + 1):
            start = bal
            interest = bal * r
            prin = min(bal, pmt - interest)
            bal -= prin
            fee = loan["annualFee"] / 12
            ti += interest
            tf += fee
            sum_bal += start
            cf = interest + prin + fee
            if m == t_months and bal > 0.5:
                out["balloon"] = bal
                cf += bal
            cfs.append(cf)
            out["rows"].append({"m": m, "pay": interest + prin + fee, "int": interest, "prin": prin, "fee": fee,
                                "bal": out["balloon"] if m == t_months and out["balloon"] else bal,
                                "start": start})
        i = irr(a - upfront, cfs)
        out.update(rate=rate, apr=i * 1200, net=a - upfront, payment=pmt + loan["annualFee"] / 12,
                   totalInterest=ti, totalFees=tf + upfront, firstYearDS=(pmt + loan["annualFee"] / 12) * 12,
                   avgBal=sum_bal / t_months, months=t_months, drawn=a)
    out["totalCost"] = out["totalInterest"] + out["totalFees"]
    return out


# ---- engine 2: affordability and capacity ----------------------------------------------------
def capacity(s: dict, sch: dict) -> dict:
    b, loan = s["biz"], s["loan"]
    eb = max(1.0, b["ebitda"])
    tot_ds = b["existingDS"] + sch["firstYearDS"]
    dscr = b["ebitda"] / max(1.0, tot_ds)
    lev = (b["existingDebt"] + loan["amount"]) / eb
    per_dollar = sch["firstYearDS"] / loan["amount"] if loan["amount"] > 0 else 0.0
    max_dscr = max(0.0, b["ebitda"] / DSCR_MIN - b["existingDS"]) / per_dollar if per_dollar > 0 else NAN
    max_lev = max(0.0, LEVERAGE_MAX * b["ebitda"] - b["existingDebt"])
    adv = COLLATERAL[b["collType"]][1]
    max_coll = adv * b["collValue"] if adv > 0 else NAN
    cands = [c for c in [("cash flow (1.25x DSCR)", max_dscr), ("leverage (3.5x EBITDA)", max_lev),
                         ("collateral", max_coll)] if isfinite(c[1])]
    cands.sort(key=lambda c: c[1])
    coll_cov = adv * b["collValue"] / loan["amount"] if loan["amount"] > 0 and adv > 0 else 0.0
    cushion = 1 - loan["covDSCR"] / dscr if dscr > 0 else NAN
    return {"dscr": dscr, "lev": lev, "maxDSCR": max_dscr, "maxLev": max_lev, "maxColl": max_coll,
            "binding": list(cands[0]) if cands else None, "collCov": coll_cov, "cushion": cushion,
            "totDS": tot_ds, "newDS": sch["firstYearDS"]}


def eligibility(s: dict, cap: dict) -> list[dict]:
    b, d, out = s["biz"], cap["dscr"], []

    def add(k: str, status: str, why: str) -> None:
        out.append({"k": k, "label": PRODUCTS[k]["label"], "status": status, "why": why})

    has_re, has_ar = b["collType"] == "re", b["collType"] == "blanket"
    if d >= 1.25 and b["years"] >= 2 and b["fico"] >= 660:
        add("term", "good", "Cash flow, history and credit meet common bank standards.")
    elif d >= 1.1 and b["years"] >= 2:
        add("term", "warn", "Possible, but expect tighter terms or a smaller amount.")
    else:
        add("term", "bad", "Most banks want 2 or more years in business." if b["years"] < 2
            else "Cash flow does not cover the debt with enough cushion.")
    if b["years"] >= 2 and b["revenue"] >= 250000 and (has_ar or d >= 1.5):
        add("loc", "good", "Receivables or strong cash flow support a working capital line.")
    elif b["years"] >= 1:
        add("loc", "warn", "Likely a smaller line, often with a personal guarantee.")
    else:
        add("loc", "bad", "Lines usually need at least a year of operating history.")
    add("equip", "good" if d >= 1.15 and b["years"] >= 1 else "warn",
        "The equipment secures itself, so these are easier to get. Lenders advance about 80 to 100% of cost.")
    if has_re and d >= 1.2:
        add("cre", "good", "You have real estate and the cash flow to support it.")
    else:
        add("cre", "warn" if has_re else "bad", "Cash flow is thin for a property loan." if has_re
            else "Only fits if you are buying or own property.")
    if b["fico"] >= 650 and d >= 1.15:
        gap = b["years"] < 2 or cap["collCov"] < 1
        add("sba7a", "good" if gap else "warn",
            "Built for your gap: short history or not enough collateral." if gap
            else "You may qualify for a conventional loan. SBA adds fees and paperwork.")
    else:
        add("sba7a", "bad", "SBA lenders still need cash flow of about 1.15x and fair credit.")
    add("sba504", "good" if (has_re or b["collType"] == "equip") and d >= 1.15 else "warn",
        "Only for fixed assets like buildings or major equipment. Needs about 10% down.")
    add("invoice", "good" if has_ar else "warn",
        "You sell on terms to other businesses, which is what this finances." if has_ar
        else "Only works if customers pay you on invoice terms.")
    add("mca", "warn", "Almost always available, and almost always the most expensive. Treat it as a last resort.")
    return out


# ---- engine 3: the bank's view ---------------------------------------------------------------
def risk_rating(s: dict, cap: dict) -> dict:
    b, drivers = s["biz"], []
    r = 6  # small and mid-size businesses start below investment grade

    def push(name: str, val: str, delta: int) -> None:
        nonlocal r
        r += delta
        drivers.append({"name": name, "val": val, "delta": delta})

    d = cap["dscr"]
    push("Debt service coverage", x2(d), -2 if d >= 2 else -1 if d >= 1.5 else 0 if d >= 1.25
         else 1 if d >= 1.1 else 2 if d >= 1 else 3)
    lev = cap["lev"]
    push("Debt to EBITDA", x2(lev), -1 if lev <= 1.5 else 0 if lev <= 3 else 1 if lev <= 4 else 2)
    y = b["years"]
    push("Years in business", f"{y:g} yrs", -1 if y >= 10 else 0 if y >= 3 else 1 if y >= 2 else 2)
    f = b["fico"]
    push("Owner credit score", f"{f:g}", -1 if f >= 760 else 0 if f >= 680 else 1 if f >= 640 else 2)
    name, delta = INDUSTRIES[b["industry"]]
    push("Industry risk", name, delta)
    rating = min(9, max(2, jround(r)))
    return {"rating": rating, "pd": PD_BY_RATING[rating], "drivers": drivers}


def loss_given_default(s: dict) -> float:
    b, loan = s["biz"], s["loan"]
    _, adv, sec_lgd = COLLATERAL[b["collType"]]
    if loan["product"] == "sba504":
        return 0.15
    cov = min(1.0, adv * b["collValue"] / loan["amount"]) if loan["amount"] > 0 else 0.0
    lgd = cov * sec_lgd + (1 - cov) * UNSECURED_LGD
    if b["pg"]:
        lgd -= PG_LGD_BENEFIT
    return max(0.05, lgd)


def bank_view(s: dict, sch: dict) -> dict:
    loan, b, a = s["loan"], s["biz"], s["assume"]
    p = PRODUCTS[loan["product"]]
    if p.get("mca"):
        return {"na": True}
    cap = capacity(s, sch)
    rr = risk_rating(s, cap)
    lgd = loss_given_default(s)
    idx = index_rate(s, loan["index"])
    cof = s["mkt"]["sofr"] if loan["index"] == "prime" else idx  # Prime loans are funded at market rates
    liq, h, t, cr = a["liqBps"] / 100, a["hurdle"] / 100, a["tax"] / 100, a["capRate"] / 100
    drawn = max(1.0, loan["amount"] * loan["utilPct"] / 100 if p.get("rev") else loan["amount"])
    ead = drawn + REVOLVER_CCF * (loan["amount"] - drawn) if p.get("rev") else loan["amount"]
    g = sba_guarantee(loan)
    m = min(5, max(1, loan["termY"]))
    k = irb_k(rr["pd"], lgd, m)
    ec_irb = EC_MULTIPLIER * k * ead * (1 - g) + GOV_GUARANTEE_CAPITAL * ead * g
    ec_reg = a["minCap"] / 100 * ead * (1 - g) + GOV_GUARANTEE_CAPITAL * ead * g
    ec = max(ec_irb, ec_reg)  # banks price to the higher of economic and regulatory capital
    el = rr["pd"] * lgd * ead * (1 - g)
    opex = a["opexBps"] / 1e4 * ead + a["fixedCost"]
    fees = loan["amount"] * loan["origPct"] / 100 / max(1, loan["termY"]) + loan["annualFee"] \
        + (loan["unusedBps"] / 1e4 * (loan["amount"] - drawn) if p.get("rev") else 0.0)
    nii_req = h * ec / (1 - t) - cr * ec + opex + el
    dep_val = b["deposits"] * max(0.0, cof / 100 - b["depositRate"] / 100) * (1 - a["runoff"] / 100)
    ts_val = b["treasuryFees"] * TREASURY_MARGIN
    rel_inc = dep_val + ts_val

    def rate_from(nii: float) -> float:
        return cof + liq + (nii - fees) / drawn * 100

    standalone = rate_from(nii_req)
    rel_floor = rate_from(nii_req - rel_inc)
    cost_floor = cof + liq + max(0.0, el + opex - fees) / drawn * 100
    walkaway = max(cost_floor, rel_floor)
    offered = sch["rate"]

    def nii_at(rate: float) -> float:
        return (rate - cof - liq) / 100 * drawn + fees

    def raroc(rate: float, rel: bool) -> float:
        return ((nii_at(rate) + (rel_inc if rel else 0.0)) - opex - el + cr * ec) * (1 - t) / ec * 100

    room = offered - walkaway
    return {"na": False, "cap": cap, "rr": rr, "lgd": lgd, "idx": idx, "cof": cof, "liq": liq, "drawn": drawn,
            "ead": ead, "g": g, "K": k, "EC": ec, "ecIRB": ec_irb, "ecReg": ec_reg, "EL": el, "opex": opex,
            "fees": fees, "niiReq": nii_req, "depVal": dep_val, "tsVal": ts_val, "relInc": rel_inc,
            "standalone": standalone, "relFloor": rel_floor, "costFloor": cost_floor, "walkaway": walkaway,
            "offered": offered, "room": room, "rarocStand": raroc(offered, False),
            "rarocRel": raroc(offered, True), "opening": walkaway + max(0.0, room) * 0.25,
            "landing": walkaway + max(0.0, room) * 0.5, "revenueAtOffer": nii_at(offered)}


def run(s: dict) -> dict:
    sch = schedule(s)
    return {"sch": sch, "cap": capacity(s, sch), "bank": bank_view(s, sch)}


# ---- engine 4: negotiation levers -----------------------------------------------------------
def levers(s: dict, res: dict | None = None) -> list[dict]:
    res = res or run(s)
    out: list[dict] = []
    loan, b, base = s["loan"], s["biz"], res["bank"]
    p = PRODUCTS[loan["product"]]
    yrs = max(1, loan["termY"])
    if base["na"]:
        return out
    avg_bal = res["sch"]["avgBal"]

    def worth(d: float) -> float:
        return max(0.0, d) / 1e4 * avg_bal * yrs

    def try_mod(fn) -> tuple[dict, float]:
        t = copy.deepcopy(s)
        fn(t)
        r = run(t)
        return r, (base["walkaway"] - r["bank"]["walkaway"]) * 100

    lev = s["lev"]
    if lev["moreDeposits"] > 0:
        r, d = try_mod(lambda t: t["biz"].__setitem__("deposits", t["biz"]["deposits"] + lev["moreDeposits"]))
        out.append({"id": "deposits", "kind": "rate", "title": "Move operating deposits to this bank",
                    "ask": f"Offer to keep about {money(lev['moreDeposits'])} more in operating accounts, "
                           "and ask for a lower spread in return.",
                    "why": f"Deposits are cheap funding for the bank, worth roughly "
                           f"{money(r['bank']['depVal'] - base['depVal'])} a year to them after run-off. "
                           f"That can lower the rate they need by about {bps(d)}.",
                    "bps": d, "dollars": worth(d)})
    if lev["moreTreasury"] > 0:
        r, d = try_mod(lambda t: t["biz"].__setitem__("treasuryFees",
                                                      t["biz"]["treasuryFees"] + lev["moreTreasury"]))
        out.append({"id": "treasury", "kind": "rate",
                    "title": "Bring treasury services (payroll, ACH, cards, lockbox)",
                    "ask": f"Move services you already pay for elsewhere, about {money(lev['moreTreasury'])} "
                           "a year in fees.",
                    "why": f"The bank books fee income at a margin of about 45%. It lowers the loan rate they "
                           f"need by about {bps(d)}. Only do this if their service is as good and the fees "
                           "are similar.",
                    "bps": d, "dollars": worth(d)})
    _, adv, _ = COLLATERAL[b["collType"]]
    if not b["pg"]:
        r, d = try_mod(lambda t: t["biz"].__setitem__("pg", True))
        out.append({"id": "guarantee", "kind": "rate", "title": "Offer a limited personal guarantee",
                    "ask": "Offer a guarantee capped at a set dollar amount or percent, and ask for a lower "
                           "rate in return.",
                    "why": f"A guarantee lowers the bank's expected loss if the loan defaults. Worth about "
                           f"{bps(d)} to them. Cap it and ask for it to be released once you hit agreed "
                           "milestones.",
                    "bps": d, "dollars": worth(d)})
    else:
        out.append({"id": "guarantee", "kind": "terms", "title": "Limit or phase out the personal guarantee",
                    "ask": "Ask for the guarantee to be capped (for example at 50%) or released once debt to "
                           "EBITDA falls below 2.0x.",
                    "why": "You are already giving a full guarantee. Limiting it does not lower your payments, "
                           "but it reduces your personal risk.",
                    "bps": 0.0, "dollars": 0.0})
    if adv > 0 and res["cap"]["collCov"] < 1 and loan["product"] != "sba504":
        r, d = try_mod(lambda t: t["biz"].__setitem__("collValue",
                                                      max(t["biz"]["collValue"], t["loan"]["amount"] / adv)))
        out.append({"id": "collateral", "kind": "rate",
                    "title": "Pledge enough collateral to fully cover the loan",
                    "ask": f"Collateral covers {pct(res['cap']['collCov'] * 100, 0)} of the loan at the bank's "
                           "advance rate. Offer more to reach 100%.",
                    "why": f"Full coverage lowers the bank's loss if you default and the capital they must "
                           f"hold. Worth about {bps(d)}.",
                    "bps": d, "dollars": worth(d)})
    if not p.get("rev") and loan["termY"] > 2:
        r, d = try_mod(lambda t: t["loan"].__setitem__("termY", max(1, t["loan"]["termY"] - 2)))
        out.append({"id": "shorter_term", "kind": "rate",
                    "title": "Take a shorter term on the same payment schedule",
                    "ask": f"Ask for a {loan['termY'] - 2:g}-year term with the same {loan['amortY']:g}-year "
                           "schedule. Your payment stays the same, and the bank gets its money back sooner.",
                    "why": f"A shorter term means less capital held and less risk for the bank, worth about "
                           f"{bps(d)}. The catch is that you refinance or pay a balloon sooner.",
                    "bps": d, "dollars": worth(d)})
    if p.get("rev") and loan["utilPct"] < 70:
        new_amt = jround(loan["amount"] * loan["utilPct"] / 100 * 1.4 / 10000) * 10000

        def right_size(t: dict) -> None:
            t["loan"]["amount"] = new_amt
            t["loan"]["utilPct"] = min(100, loan["amount"] * loan["utilPct"] / new_amt)

        r, d = try_mod(right_size)
        saved = (loan["amount"] - new_amt) * loan["unusedBps"] / 1e4 * yrs \
            + (loan["amount"] - new_amt) * loan["origPct"] / 100
        out.append({"id": "right_size", "kind": "fee", "title": "Right-size the line",
                    "ask": f"You expect to use about {loan['utilPct']:g}%. Ask for a {money(new_amt)} line "
                           f"instead of {money(loan['amount'])}.",
                    "why": f"Unused commitments cost the bank capital but earn it very little. A smaller line "
                           f"saves you about {money(saved)} in unused and upfront fees and can lower the rate "
                           f"needed by about {bps(d)}.",
                    "bps": d, "dollars": saved + worth(d)})
    if loan["origPct"] > 0:
        t = copy.deepcopy(s)
        t["loan"]["origPct"] = loan["origPct"] / 2
        sch2 = schedule(t)
        saved = loan["amount"] * loan["origPct"] / 200
        out.append({"id": "fee", "kind": "fee", "title": "Cut the origination fee in half",
                    "ask": f"Ask for the {pct(loan['origPct'])} fee to be reduced to {pct(loan['origPct'] / 2)}, "
                           "or waived if you bring deposits.",
                    "why": f"It saves {money(saved)} upfront and lowers your APR from {pct(res['sch']['apr'])} "
                           f"to {pct(sch2['apr'])}. Banks often give on fees before they give on rate.",
                    "bps": (res["sch"]["apr"] - sch2["apr"]) * 100, "dollars": saved})
    if loan["prepay"] != "none":
        out.append({"id": "prepay", "kind": "terms", "title": "Remove or soften the prepayment penalty",
                    "ask": "Ask to replace yield maintenance with a step-down (3-2-1%), or none after year 2."
                    if loan["prepay"] == "ym" else "Ask for no penalty when you repay from your own cash "
                    "(not a refinance), or none after year 2.",
                    "why": "This keeps you free to refinance if rates fall or to pay the loan down early. It "
                           "costs the bank little on a floating-rate loan.",
                    "bps": 0.0, "dollars": 0.0})
    cushion = res["cap"]["cushion"]
    if cushion < 0.25:
        out.append({"id": "covenant", "kind": "terms", "title": "Negotiate covenant headroom",
                    "ask": f"Ask for a minimum DSCR covenant of {max(1.05, loan['covDSCR'] - 0.1):.2f}x instead "
                           f"of {loan['covDSCR']:.2f}x, tested annually rather than quarterly.",
                    "why": f"Your EBITDA can only drop about {pct(max(0.0, cushion * 100), 0)} before you "
                           "breach. A breach can bring fees, a higher rate or a demand to repay.",
                    "bps": 0.0, "dollars": 0.0})
    else:
        out.append({"id": "covenant", "kind": "terms", "title": "Lock in covenant terms now",
                    "ask": "Ask for annual testing, a cure period and EBITDA add-backs spelled out in the "
                           "agreement.",
                    "why": f"You have a comfortable {pct(cushion * 100, 0)} EBITDA cushion over the "
                           f"{loan['covDSCR']:.2f}x covenant. Covenant terms are easiest to get while things "
                           "look good.",
                    "bps": 0.0, "dollars": 0.0})
    if lev["competeRate"] > 0:
        gap = (base["offered"] - lev["competeRate"]) * 100
        name = lev["competeName"] or "the other lender"
        below = lev["competeRate"] < base["walkaway"]
        out.append({"id": "competing_offer", "kind": "rate", "title": f"Use the competing offer from {name}",
                    "ask": f"Share the competing {pct(lev['competeRate'])} term sheet in writing and ask them to "
                           "match or beat it.",
                    "why": f"It is below this bank's estimated walk-away rate ({pct(base['walkaway'])}), so they "
                           "probably cannot match on rate alone. Ask for fee or structure concessions, or take "
                           "the other offer if the terms are as good." if below else
                           f"It is above this bank's estimated walk-away rate ({pct(base['walkaway'])}), so a "
                           f"match is financially possible for them. It is worth about {bps(gap)} if they match.",
                    "bps": max(0.0, gap), "dollars": worth(gap)})
    out.sort(key=lambda x: x["dollars"], reverse=True)
    return out


# ---- offer comparison ----------------------------------------------------------------------------
def offer_schedule(s: dict, o: dict) -> dict:
    """Schedule for a fixed-rate term quote, expressed as SOFR + spread so fees and APR work the same."""
    t = copy.deepcopy(s)
    t["loan"].update(product="term", amount=o["amount"], termY=o["termY"], amortY=max(o["amortY"], o["termY"]),
                     index="sofr", spreadBps=(o["rate"] - s["mkt"]["sofr"]) * 100, origPct=o["origPct"],
                     closingCost=o["closing"], annualFee=o["annualFee"])
    return schedule(t)
