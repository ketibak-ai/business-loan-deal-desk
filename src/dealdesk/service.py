"""One service layer for the API, the CLI and the Claude agent, so all three report identical numbers.

Every function takes plain dicts and returns JSON-ready dicts: rates in percent, spreads and
rate changes in basis points, money in dollars.
"""

from __future__ import annotations

import copy
import math

from . import engine, rag
from .config import COLLATERAL, INDEXES, INDUSTRIES, PRODUCTS, apply_product_defaults, example
from .models import Market, Offer, Scenario


def _clean(obj):
    """Round floats and turn NaN/inf into None so results serialize as strict JSON."""
    if isinstance(obj, float):
        return round(obj, 4) if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(v) for v in obj]
    return obj


def normalize(scenario: dict | Scenario | None) -> dict:
    """Validate a (possibly partial) scenario and fill every missing field with its default."""
    if scenario is None:
        return example()
    if isinstance(scenario, Scenario):
        return scenario.model_dump()
    return Scenario.model_validate(scenario).model_dump()


def example_scenario() -> dict:
    return example()


def catalog() -> dict:
    """Loan products with their typical terms, plus the industry and collateral codes."""
    return {
        "products": [{"code": k, **{f: v for f, v in p.items() if f != "blurb"}, "description": p["blurb"]}
                     for k, p in PRODUCTS.items()],
        "industries": [{"code": k, "label": v[0], "risk_notch": v[1]} for k, v in INDUSTRIES.items()],
        "collateral": [{"code": k, "label": v[0], "advance_rate": v[1]} for k, v in COLLATERAL.items()],
        "indexes": [{"code": k, "label": v} for k, v in INDEXES.items()],
    }


# ---- analysis ------------------------------------------------------------------------------------
def _yearly(rows: list[dict]) -> list[dict]:
    years: dict[int, dict] = {}
    for r in rows:
        y = (r["m"] - 1) // 12 + 1
        acc = years.setdefault(y, {"year": y, "payments": 0.0, "interest": 0.0, "principal": 0.0,
                                   "fees": 0.0, "ending_balance": 0.0, "_bal": 0.0})
        acc["payments"] += r["pay"]
        acc["interest"] += r["int"]
        acc["principal"] += r["prin"]
        acc["fees"] += r["fee"]
        acc["ending_balance"] = r["bal"]
        acc["_bal"] += r["start"]
    for acc in years.values():  # balance-weighted average rate for the year
        bal = acc.pop("_bal")
        acc["avg_rate_pct"] = acc["interest"] / bal * 1200 if bal > 0 else None
    return list(years.values())


def _rate_sensitivity(s: dict, sch: dict) -> dict | None:
    """What a parallel move in SOFR does to a floating loan: +/-100 bps versus the base path."""
    loan = s["loan"]
    if PRODUCTS[loan["product"]].get("mca") or loan["index"] == "ust5":
        return None
    out = {}
    for shock in (-100, 100):
        t = copy.deepcopy(s)
        t["mkt"]["shockBps"] = (s["mkt"].get("shockBps") or 0) + shock
        x = engine.schedule(t)
        out[f"{shock:+d}bps"] = {"first_payment": x["payment"], "total_cost": x["totalCost"], "apr_pct": x["apr"],
                                 "extra_total_cost": x["totalCost"] - sch["totalCost"]}
    return out


def _cost(s: dict, sch: dict) -> dict:
    return {
        "stated_rate_pct": sch["rate"], "apr_pct": sch["apr"], "average_rate_pct": sch.get("avgRate"),
        "rate_type": "fixed" if s["loan"]["index"] == "ust5" else "floating",
        "uses_sofr_curve": bool(s["mkt"].get("useCurve")), "rate_shock_bps": s["mkt"].get("shockBps") or 0,
        "rate_sensitivity": _rate_sensitivity(s, sch), "monthly_payment": sch["payment"],
        "daily_payment": sch.get("daily"), "cash_received": sch["net"], "upfront_fees": sch["upfront"],
        "total_interest": sch["totalInterest"], "total_fees": sch["totalFees"], "total_cost": sch["totalCost"],
        "balloon": sch["balloon"], "months": sch["months"], "average_balance": sch["avgBal"],
        "first_year_debt_service": sch["firstYearDS"], "by_year": _yearly(sch["rows"]),
    }


def _capacity(cap: dict) -> dict:
    return {
        "dscr": cap["dscr"], "debt_to_ebitda": cap["lev"], "collateral_coverage": cap["collCov"],
        "max_loan_by_cash_flow": cap["maxDSCR"], "max_loan_by_leverage": cap["maxLev"],
        "max_loan_by_collateral": cap["maxColl"],
        "binding_limit": ({"name": cap["binding"][0], "amount": cap["binding"][1]} if cap["binding"] else None),
        "covenant_ebitda_cushion": cap["cushion"], "total_debt_service": cap["totDS"],
    }


def _bank(b: dict) -> dict:
    if b["na"]:
        return {"applicable": False,
                "note": "A merchant cash advance is priced by a non-bank funder, not a bank RAROC model."}
    spread = lambda v: (v - b["idx"]) * 100  # noqa: E731
    small = b["tier"] == "small"
    return {
        "applicable": True,
        "segment": b["tier"],
        "method": ("Small business: credit scorecard band with a pooled default rate, Basel retail capital, "
                   "priced off a rate grid with limited banker discretion" if small else
                   "Commercial: individual risk rating, economic capital (Basel IRB corporate with maturity and "
                   "small-firm adjustments), deal-by-deal relationship RAROC"),
        "credit_score": b["rr"].get("score"),
        "risk_rating": b["rr"]["rating"], "probability_of_default_pct": b["rr"]["pd"] * 100,
        "rating_drivers": b["rr"]["drivers"], "loss_given_default_pct": b["lgd"] * 100,
        "sba_guaranteed_pct": b["g"] * 100,
        "rates_pct": {"offered": b["offered"], "loan_only_target": b["standalone"],
                      "walk_away": b["walkaway"], "cost_floor": b["costFloor"],
                      "opening_ask": b["opening"], "realistic_outcome": b["landing"]},
        "spreads_bps": {"offered": spread(b["offered"]), "loan_only_target": spread(b["standalone"]),
                        "walk_away": spread(b["walkaway"]), "cost_floor": spread(b["costFloor"]),
                        "opening_ask": spread(b["opening"]), "realistic_outcome": spread(b["landing"])},
        "room_to_negotiate_bps": b["negotiable"] * 100, "economic_room_bps": b["room"] * 100,
        "bank_raroc_at_offer_pct": {"loan_only": b["rarocStand"], "with_relationship": b["rarocRel"]},
        "year1": {"funds_used": b["drawn"], "exposure": b["ead"], "cost_of_funds_pct": b["cof"],
                  "revenue_at_offer": b["revenueAtOffer"], "expected_loss": b["EL"], "servicing_cost": b["opex"],
                  "relationship_value": b["relInc"], "deposit_value": b["depVal"],
                  "treasury_value": b["tsVal"], "capital": b["EC"],
                  "capital_basis": "regulatory minimum" if b["ecReg"] >= b["ecIRB"] else "risk model"},
    }


def analyze(scenario: dict | Scenario | None = None) -> dict:
    """Full analysis: true cost, affordability, loan-type fit, the bank's view and negotiation levers."""
    s = normalize(scenario)
    res = engine.run(s)
    lv = engine.levers(s, res)
    savings = 0.0
    if not res["bank"]["na"]:
        b = res["bank"]
        savings = max(0.0, b["offered"] - b["landing"]) / 100 * res["sch"]["avgBal"] * s["loan"]["termY"]
    return _clean({
        "product": s["loan"]["product"], "product_label": PRODUCTS[s["loan"]["product"]]["label"],
        "cost": _cost(s, res["sch"]),
        "capacity": _capacity(res["cap"]),
        "eligibility": engine.eligibility(s, res["cap"]),
        "bank_view": _bank(res["bank"]),
        "savings_at_realistic_outcome": savings,
        "levers": lv,
        "talking_points": brief(s, res, lv),
    })


def negotiate(scenario: dict | Scenario | None = None) -> dict:
    """Just the negotiation plan: rates to aim for, ranked levers and talking points."""
    full = analyze(scenario)
    bank = full["bank_view"]
    return {"product": full["product"], "apr_pct": full["cost"]["apr_pct"],
            "rates_pct": bank.get("rates_pct"), "room_to_negotiate_bps": bank.get("room_to_negotiate_bps"),
            "savings_at_realistic_outcome": full["savings_at_realistic_outcome"],
            "levers": full["levers"], "talking_points": full["talking_points"]}


def compare(offers: list[dict | Offer], mkt: dict | Market | None = None) -> dict:
    """Compare fixed-rate term quotes by payment, APR and total cost; flags the lowest APR."""
    s = example()
    if mkt is not None:
        s["mkt"] = (mkt if isinstance(mkt, Market) else Market.model_validate(mkt)).model_dump()
    rows = []
    for o in offers:
        o = (o if isinstance(o, Offer) else Offer.model_validate(o)).model_dump()
        sch = engine.offer_schedule(s, o)
        rows.append({"name": o["name"], "rate_pct": o["rate"], "term_years": o["termY"],
                     "monthly_payment": sch["payment"], "apr_pct": sch["apr"], "upfront_fees": sch["upfront"],
                     "total_interest": sch["totalInterest"], "total_cost": sch["totalCost"],
                     "balloon": sch["balloon"]})
    best = min(rows, key=lambda r: r["apr_pct"])
    for r in rows:
        r["lowest_apr"] = r is best
    same_term = len({r["term_years"] for r in rows}) == 1
    return _clean({"offers": rows, "lowest_apr": best["name"], "same_term": same_term,
                   "note": None if same_term else "Terms differ, so compare APR rather than total cost."})


# ---- quick scenario for the agent ---------------------------------------------------------------
_FLAT = {  # agent/CLI argument -> (section, field)
    "product": ("loan", "product"), "amount": ("loan", "amount"), "term_years": ("loan", "termY"),
    "amortization_years": ("loan", "amortY"), "rate_index": ("loan", "index"), "spread_bps": ("loan", "spreadBps"),
    "utilization_pct": ("loan", "utilPct"), "unused_fee_bps": ("loan", "unusedBps"),
    "mca_factor_rate": ("loan", "mcaFactor"), "mca_months": ("loan", "mcaMonths"),
    "origination_fee_pct": ("loan", "origPct"), "closing_costs": ("loan", "closingCost"),
    "annual_fee": ("loan", "annualFee"), "prepayment_penalty": ("loan", "prepay"),
    "covenant_min_dscr": ("loan", "covDSCR"), "lender": ("loan", "lender"),
    "industry": ("biz", "industry"), "years_in_business": ("biz", "years"), "annual_revenue": ("biz", "revenue"),
    "ebitda": ("biz", "ebitda"), "existing_debt": ("biz", "existingDebt"),
    "existing_annual_debt_payments": ("biz", "existingDS"), "owner_credit_score": ("biz", "fico"),
    "personal_guarantee": ("biz", "pg"), "bank_segment": ("biz", "tier"), "collateral_type": ("biz", "collType"),
    "collateral_value": ("biz", "collValue"), "operating_deposits": ("biz", "deposits"),
    "deposit_rate_pct": ("biz", "depositRate"), "treasury_fees": ("biz", "treasuryFees"),
    "extra_deposits_offered": ("lev", "moreDeposits"), "extra_treasury_fees_offered": ("lev", "moreTreasury"),
    "competing_rate_pct": ("lev", "competeRate"), "competing_lender": ("lev", "competeName"),
    "sofr_pct": ("mkt", "sofr"), "prime_pct": ("mkt", "prime"), "treasury_5y_pct": ("mkt", "ust5"),
    "use_sofr_curve": ("mkt", "useCurve"), "rate_shock_bps": ("mkt", "shockBps"),
}
FLAT_FIELDS = tuple(_FLAT)


def quick_scenario(**kw) -> dict:
    """Build a full scenario from flat arguments. Loan terms not given take the product's typical values;
    business fields not given take neutral defaults (see models.Business)."""
    s = Scenario().model_dump()
    s["mkt"] = copy.deepcopy(example()["mkt"])
    apply_product_defaults(s, kw.get("product", "term"))
    for key, value in kw.items():
        if value is None:
            continue
        if key not in _FLAT:
            raise ValueError(f"unknown field {key}")
        section, field = _FLAT[key]
        s[section][field] = value
    return normalize(s)


# ---- talking points --------------------------------------------------------------------------------
def brief(s: dict, res: dict, lv: list[dict]) -> str:
    b, loan, biz, cap, sch = res["bank"], s["loan"], s["biz"], res["cap"], res["sch"]
    p = PRODUCTS[loan["product"]]
    lender, name = loan["lender"] or "the bank", biz["name"] or "our business"
    idx_name = INDEXES[loan["index"]].split(" ")[0]
    lines = [f"TALKING POINTS: {name} and {lender}", f"{p['label']}, {engine.money(loan['amount'])}", "",
             "OUR PROFILE",
             f"- {biz['years']:g} years in business, {engine.money(biz['revenue'])} revenue, "
             f"{engine.money(biz['ebitda'])} EBITDA",
             f"- Debt service coverage after this loan: {engine.x2(cap['dscr'])}. "
             f"Debt to EBITDA: {engine.x2(cap['lev'])}"]
    if COLLATERAL[biz["collType"]][1] > 0:
        lines.append(f"- Collateral: {COLLATERAL[biz['collType']][0].lower()}, about "
                     f"{engine.money(biz['collValue'])}")
    lines.append("")
    if b["na"]:
        lines += ["WHAT WE ARE ASKING",
                  f"- A term loan or line of credit to replace an MCA priced at {engine.pct(sch['apr'], 0)} APR"]
        return "\n".join(lines)
    lines.append("WHAT WE ARE ASKING")
    if b["negotiable"] > 0:
        lines.append(f"- Rate: {idx_name} + {engine.jround((b['opening'] - b['idx']) * 100)} bps "
                     f"(offered: + {loan['spreadBps']:g} bps)")
    else:
        lines.append(f"- Rate: we accept the offered spread of {loan['spreadBps']:g} bps, subject to the terms below")
    lines += ["- " + x["ask"] for x in lv if x["kind"] == "fee"]
    lines += ["- " + x["ask"] for x in lv if x["kind"] == "terms"]
    give = [x for x in lv if x["kind"] == "rate" and x["bps"] > 0 and x["id"] != "competing_offer"]
    if give:
        lines += ["", "WHAT WE CAN OFFER IN RETURN"] + ["- " + x["ask"] for x in give]
    if any(x["id"] == "competing_offer" for x in lv):
        lines += ["", "COMPETING OFFER",
                  f"- {s['lev']['competeName'] or 'Another lender'} has offered "
                  f"{engine.pct(s['lev']['competeRate'])}. We prefer to stay with {lender} if you can come close."]
    lines += ["", "OUR LIMITS (DO NOT SHARE)",
              f"- Target: about {engine.pct(b['landing'])}. Their walk-away is probably near "
              f"{engine.pct(b['walkaway'])}.",
              f"- True cost of the current offer: {engine.pct(sch['apr'])} APR, {engine.money(sch['totalCost'])} "
              "in interest and fees over the term."]
    return "\n".join(lines)


def guide_search(query: str, k: int = 3) -> list[dict]:
    return rag.search(query, k)
