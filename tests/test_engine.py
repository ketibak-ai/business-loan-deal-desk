"""Engine math: known answers, sanity bounds and the direction every negotiation lever should move."""

import copy

import pytest
from scenarios import all_scenarios

from dealdesk import engine
from dealdesk.config import apply_product_defaults, example


def _run(s):
    return engine.run(s)


# ---- engine 1: cost ---------------------------------------------------------------------------
def test_annuity_payment_matches_formula():
    s = example()
    s["mkt"]["useCurve"] = False  # flat rate
    s["loan"].update(amount=100000, termY=5, amortY=5, spreadBps=600 - s["mkt"]["sofr"] * 100, origPct=0,
                     closingCost=0, annualFee=0)
    sch = engine.schedule(s)
    r = 0.06 / 12
    assert sch["payment"] == pytest.approx(100000 * r / (1 - (1 + r) ** -60), rel=1e-12)
    assert sch["balloon"] == 0
    assert sch["apr"] == pytest.approx(6.0, abs=1e-6)  # no fees: APR equals the stated rate


def test_fees_raise_apr_above_stated_rate():
    sch = engine.schedule(example())
    assert sch["apr"] > sch["rate"]
    assert sch["upfront"] == pytest.approx(1200000 * 0.01 + 7500)


def test_balloon_when_amortization_longer_than_term():
    sch = engine.schedule(example())  # 5-year term on a 7-year schedule
    assert 380000 < sch["balloon"] < 430000
    assert sch["rows"][-1]["bal"] == sch["balloon"]


def test_mca_apr_is_far_above_factor_rate():
    s = apply_product_defaults(example(), "mca")
    sch = engine.schedule(s)
    assert sch["apr"] > 70  # a 1.35 factor over 9 months with fees is roughly 80%+ APR
    assert sch["totalInterest"] == pytest.approx(s["loan"]["amount"] * 0.35)


def test_line_of_credit_charges_unused_fee():
    s = apply_product_defaults(example(), "loc")
    sch = engine.schedule(s)
    drawn = s["loan"]["amount"] * 0.40
    assert sch["drawn"] == pytest.approx(drawn)
    assert sch["rows"][0]["fee"] == pytest.approx((s["loan"]["amount"] - drawn) * 25 / 1e4 / 12)


# ---- SOFR forward curve ---------------------------------------------------------------------------
def test_curve_interpolation_and_extrapolation():
    s = example()
    assert engine.fwd_base(s, 0) == s["mkt"]["sofr"]
    assert engine.fwd_base(s, 0.25) == pytest.approx((3.65 + 3.55) / 2)
    assert engine.fwd_base(s, 4) == pytest.approx((3.65 + 3.85) / 2)
    assert engine.fwd_base(s, 30) == 4.15  # flat beyond the last point
    s["mkt"]["useCurve"] = False
    assert engine.fwd_base(s, 7) == s["mkt"]["sofr"]


def test_flat_curve_gives_level_payments():
    s = example()
    s["mkt"]["useCurve"] = False
    pays = {round(r["pay"], 6) for r in engine.schedule(s)["rows"]}
    assert len(pays) == 1


def test_floating_loan_follows_the_curve():
    s = example()
    rows = engine.schedule(s)["rows"]
    assert rows[0]["rate"] == pytest.approx(3.65 + 3.25)
    assert rows[59]["rate"] == pytest.approx(engine.fwd_base(s, 59 / 12) + 3.25)
    flat = copy.deepcopy(s)
    flat["mkt"]["useCurve"] = False
    # the example curve dips then rises above spot, so total interest differs from the flat projection
    assert engine.schedule(s)["totalInterest"] != pytest.approx(engine.schedule(flat)["totalInterest"])


def test_rate_shock_moves_floating_not_fixed():
    s = example()
    up = copy.deepcopy(s)
    up["mkt"]["shockBps"] = 100
    assert engine.schedule(up)["totalCost"] > engine.schedule(s)["totalCost"] + 30000
    fixed = apply_product_defaults(example(), "equip")
    fixed_up = copy.deepcopy(fixed)
    fixed_up["mkt"]["shockBps"] = 100
    assert engine.schedule(fixed_up)["totalCost"] == pytest.approx(engine.schedule(fixed)["totalCost"])


def test_prime_moves_with_sofr():
    s = apply_product_defaults(example(), "loc")
    assert engine.path_rate(s, s["loan"], 1) == pytest.approx(6.75 + 0.75)
    assert engine.path_rate(s, s["loan"], 61) == pytest.approx(6.75 + (engine.fwd(s, 5) - 3.65) + 0.75)


def test_fixed_loan_funded_at_curve_swap_rate():
    s = apply_product_defaults(example(), "equip")
    b = engine.run(s)["bank"]
    assert b["cof"] == pytest.approx(engine.swap_rate(s, 5))
    s["mkt"]["useCurve"] = False
    assert engine.run(s)["bank"]["cof"] == s["mkt"]["ust5"]


def test_rate_risk_lever_only_for_floating():
    assert "rate_risk" in {x["id"] for x in engine.levers(example())}
    assert "rate_risk" not in {x["id"] for x in engine.levers(apply_product_defaults(example(), "equip"))}


# ---- engine 2: capacity -----------------------------------------------------------------------
def test_dscr_and_capacity():
    s = example()
    r = _run(s)
    cap = r["cap"]
    assert cap["dscr"] == pytest.approx(850000 / (240000 + r["sch"]["firstYearDS"]))
    assert cap["maxLev"] == pytest.approx(3.5 * 850000 - 900000)
    assert cap["maxColl"] == pytest.approx(0.65 * 1400000)
    assert cap["binding"][0] == "collateral"


def test_weak_cash_flow_is_flagged():
    s = example()
    s["biz"]["ebitda"] = 300000
    r = _run(s)
    assert r["cap"]["dscr"] < 1.0
    fit = {e["k"]: e["status"] for e in engine.eligibility(s, r["cap"])}
    assert fit["term"] == "bad"


# ---- engine 3: bank view ----------------------------------------------------------------------
def test_basel_irb_reference_point():
    # Basel reference: PD 1%, LGD 45%, M 2.5 -> K of about 7.4%
    assert engine.irb_k(0.01, 0.45, 2.5) == pytest.approx(0.0739, abs=5e-4)


def test_normal_inverse_roundtrip():
    for p in (0.001, 0.02, 0.3, 0.5, 0.9, 0.999):
        assert engine.ncdf(engine.ninv(p)) == pytest.approx(p, abs=2e-6)


@pytest.mark.parametrize("name,s", [x for x in all_scenarios() if x[1]["loan"]["product"] != "mca"])
def test_floor_ordering_and_hurdle(name, s):
    b = _run(s)["bank"]
    assert b["walkaway"] == pytest.approx(max(b["costFloor"], b["relFloor"]))
    assert b["relFloor"] <= b["standalone"] + 1e-9  # the relationship can only lower the floor
    # at the loan-only target the bank earns exactly its hurdle. Repricing changes the payment and so
    # DSCR; if that moves the risk rating, the bank earns at least the hurdle instead of exactly it.
    t = copy.deepcopy(s)
    t["loan"]["spreadBps"] = (b["standalone"] - b["idx"]) * 100
    tb = _run(t)["bank"]
    if tb["rr"]["rating"] == b["rr"]["rating"]:
        assert tb["rarocStand"] == pytest.approx(s["assume"]["hurdle"], abs=1e-6)
    else:
        assert tb["rr"]["rating"] < b["rr"]["rating"] and tb["rarocStand"] > s["assume"]["hurdle"]


def test_example_bank_view_is_plausible():
    b = _run(example())["bank"]
    assert b["rr"]["rating"] == 4
    assert b["ecReg"] > b["ecIRB"]  # small-business loans price off the regulatory minimum
    assert 100 < b["room"] * 100 < 250
    assert b["rarocRel"] > 12


def test_sba_guarantee_cuts_bank_capital_and_loss():
    s = apply_product_defaults(example(), "sba7a")
    guaranteed = _run(s)["bank"]
    s["loan"]["product"] = "term"
    plain = _run(s)["bank"]
    assert guaranteed["EC"] < plain["EC"] / 2
    assert guaranteed["EL"] < plain["EL"] / 2


def test_prime_loans_are_funded_at_sofr():
    s = apply_product_defaults(example(), "loc")
    b = _run(s)["bank"]
    assert b["cof"] == s["mkt"]["sofr"] and b["idx"] == s["mkt"]["prime"]


def test_mca_has_no_bank_view():
    assert _run(apply_product_defaults(example(), "mca"))["bank"] == {"na": True}


# ---- small business vs commercial tiers ----------------------------------------------------------
def _small_biz():
    s = example()
    s["loan"]["amount"] = 300000
    s["biz"].update(revenue=2000000, ebitda=350000, existingDebt=100000, existingDS=30000, collValue=400000)
    return s


def test_tier_is_chosen_by_size_and_can_be_overridden():
    assert engine.tier_of(example()) == "commercial"  # $6.2M revenue
    assert engine.tier_of(_small_biz()) == "small"
    s = _small_biz()
    s["biz"]["tier"] = "commercial"
    assert engine.tier_of(s) == "commercial"


def test_small_tier_uses_scorecard_band_and_retail_capital():
    b = engine.run(_small_biz())["bank"]
    assert b["tier"] == "small" and b["rr"]["rating"] in "ABCDE"
    assert b["rr"]["pd"] == dict((x[0], x[2]) for x in engine.SCORE_BANDS)[b["rr"]["rating"]]
    assert b["K"] == pytest.approx(engine.irb_retail_k(b["rr"]["pd"], b["lgd"]))


def test_retail_capital_is_below_corporate_for_same_risk():
    assert engine.irb_retail_k(0.02, 0.45) < engine.irb_k(0.02, 0.45, 2.5)


def test_sme_size_adjustment_lowers_corporate_capital():
    assert engine.irb_k(0.01, 0.45, 2.5, size_adj=0.04) < engine.irb_k(0.01, 0.45, 2.5)


def test_small_risk_weight_drives_regulatory_capital():
    s = _small_biz()
    full = engine.run(s)["bank"]["ecReg"]
    s["assume"]["smallRW"] = 75
    assert engine.run(s)["bank"]["ecReg"] == pytest.approx(full * 0.75)


def test_small_tier_room_is_capped_by_banker_discretion():
    s = _small_biz()
    b = engine.run(s)["bank"]
    assert b["room"] * 100 > 50  # the model has more room than a banker can give
    assert b["negotiable"] * 100 == pytest.approx(50)
    assert b["landing"] == pytest.approx(b["offered"] - 0.25)
    assert all(x["bps"] <= 50 + 1e-9 for x in engine.levers(s) if x["id"] != "competing_offer")


def test_commercial_tier_room_is_the_full_economic_room():
    b = engine.run(example())["bank"]
    assert b["negotiable"] == pytest.approx(b["room"])


def test_better_owner_credit_improves_small_business_band():
    s = _small_biz()
    s["biz"]["fico"] = 640
    weak = engine.run(s)["bank"]
    s["biz"]["fico"] = 790
    strong = engine.run(s)["bank"]
    assert strong["rr"]["score"] > weak["rr"]["score"] and strong["rr"]["pd"] < weak["rr"]["pd"]


# ---- engine 4: levers -------------------------------------------------------------------------
def test_levers_move_the_floor_the_right_way():
    s = example()
    lv = {x["id"]: x for x in engine.levers(s)}
    assert lv["deposits"]["bps"] > 0 and lv["treasury"]["bps"] > 0
    assert lv["collateral"]["bps"] >= 0
    assert lv["fee"]["dollars"] == pytest.approx(1200000 * 0.005)
    assert lv["competing_offer"]["bps"] == pytest.approx(30, abs=1e-6)


def test_levers_sorted_by_value():
    values = [x["dollars"] for x in engine.levers(example())]
    assert values == sorted(values, reverse=True)


def test_guarantee_lever_when_none_given():
    s = example()
    s["biz"]["pg"] = False
    lv = {x["id"]: x for x in engine.levers(s)}
    assert lv["guarantee"]["kind"] == "rate" and lv["guarantee"]["bps"] >= 0


def test_right_size_line_lever():
    s = apply_product_defaults(example(), "loc")
    s["loan"]["utilPct"] = 20
    lv = {x["id"]: x for x in engine.levers(s)}
    assert lv["right_size"]["dollars"] > 0


def test_js_rounding_helper():
    assert engine.jround(2.5) == 3 and engine.jround(-2.5) == -2 and engine.jround(0.49) == 0
