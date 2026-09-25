"""Reference data and default assumptions.

These values must match `web/engine.js`; tests/test_js_parity.py checks that they do.
Rates are in percent (3.65 = 3.65%) and spreads in basis points, the same units a borrower
reads on a term sheet.
"""

from __future__ import annotations

import copy

PRODUCTS: dict[str, dict] = {
    "term": {"label": "Term loan", "termY": 5, "amortY": 7, "index": "sofr", "spread": 300, "orig": 1.0,
             "blurb": "A lump sum repaid on a fixed schedule. Used for expansion, acquisitions and refinancing."},
    "loc": {"label": "Line of credit (revolver)", "rev": True, "termY": 2, "index": "prime", "spread": 75,
            "orig": 0.5, "unused": 25, "util": 40,
            "blurb": "Draw and repay as needed. You pay interest on what you use and a fee on the unused part."},
    "equip": {"label": "Equipment loan", "termY": 5, "amortY": 5, "index": "ust5", "spread": 325, "orig": 0.5,
              "blurb": "Pays for a machine or vehicle, and that equipment is the collateral."},
    "cre": {"label": "Commercial real estate mortgage", "termY": 10, "amortY": 25, "index": "ust5",
            "spread": 250, "orig": 0.75,
            "blurb": "To buy or refinance property. Usually a 5 to 10 year term on a 20 to 25 year "
                     "schedule, so a balloon comes due."},
    "sba7a": {"label": "SBA 7(a) loan", "termY": 10, "amortY": 10, "index": "prime", "spread": 275, "orig": 0,
              "sbaFee": 2.5,
              "blurb": "A bank loan backed 75 to 85% by a federal guarantee. Longer terms and less "
                       "collateral, but more paperwork and a guarantee fee."},
    "sba504": {"label": "SBA 504 loan", "termY": 20, "amortY": 20, "index": "ust5", "spread": 225, "orig": 0.5,
               "sbaFee": 2.2,
               "blurb": "For real estate or major equipment: bank about 50%, CDC about 40%, you 10%. "
                        "Modeled as one blended loan."},
    "invoice": {"label": "Invoice / receivables financing", "rev": True, "termY": 1, "index": "prime",
                "spread": 300, "orig": 1.0, "unused": 0, "util": 70,
                "blurb": "An advance of about 80% of what customers owe you. Fast, but priced higher."},
    "mca": {"label": "Merchant cash advance", "mca": True, "termY": 1, "factor": 1.35, "months": 9, "orig": 2.5,
            "blurb": "Not a loan: you sell future sales for a lump sum and repay daily. Often the most "
                     "expensive money a business can take."},
}

INDUSTRIES: dict[str, tuple[str, int]] = {
    "prof": ("Professional services", 0), "health": ("Healthcare practice", 0),
    "tech": ("Technology / software", 0), "mfg": ("Manufacturing", 0),
    "dist": ("Wholesale / distribution", 0), "constr": ("Construction / trades", 1),
    "trans": ("Transportation / logistics", 1), "retail": ("Retail", 1),
    "rest": ("Restaurant / hospitality", 1), "ag": ("Agriculture", 1), "energy": ("Energy / oil and gas", 2),
}

# collateral type -> (label, bank advance rate, loss given default on the secured part)
COLLATERAL: dict[str, tuple[str, float, float]] = {
    "none": ("None (unsecured)", 0.0, 0.45),
    "blanket": ("Receivables and inventory (blanket lien)", 0.65, 0.32),
    "equip": ("Equipment and vehicles", 0.80, 0.30),
    "re": ("Real estate", 0.75, 0.35),
    "cash": ("Cash or CDs", 0.95, 0.05),
}

INDEXES = {"sofr": "SOFR (floating)", "prime": "Prime (floating)", "ust5": "5-yr Treasury (fixed)"}
PREPAY = {"none": "None", "step": "Step-down (e.g. 3-2-1%)", "ym": "Yield maintenance / make-whole"}

# internal risk rating 1 (best) .. 10 (worst) -> one-year probability of default
PD_BY_RATING = [None, 0.0003, 0.0006, 0.0015, 0.003, 0.005, 0.009, 0.016, 0.035, 0.07, 0.15]

DSCR_MIN = 1.25               # typical bank minimum debt service coverage
LEVERAGE_MAX = 3.5            # typical maximum total debt / EBITDA
REVOLVER_CCF = 0.75           # share of undrawn commitment counted as exposure
EC_MULTIPLIER = 1.06          # economic capital scaler over IRB K
GOV_GUARANTEE_CAPITAL = 0.016  # capital on the SBA-guaranteed share (20% risk weight x 8%)
TREASURY_MARGIN = 0.45        # bank's margin on treasury-management fees (55% cost-to-income)
UNSECURED_LGD = 0.45
PG_LGD_BENEFIT = 0.03         # a personal guarantee trims loss given default by 3 points

EXAMPLE: dict = {
    "loan": {"product": "term", "lender": "First Harbor Bank", "amount": 1200000, "termY": 5, "amortY": 7,
             "index": "sofr", "spreadBps": 325, "utilPct": 40, "unusedBps": 25, "mcaFactor": 1.35,
             "mcaMonths": 9, "origPct": 1.0, "closingCost": 7500, "annualFee": 0, "sbaFeePct": 2.5,
             "prepay": "step", "covDSCR": 1.25},
    "biz": {"name": "Cedar & Pine Millwork", "industry": "mfg", "years": 12, "revenue": 6200000,
            "ebitda": 850000, "existingDebt": 900000, "existingDS": 240000, "fico": 735, "pg": True,
            "collType": "blanket", "collValue": 1400000, "deposits": 150000, "depositRate": 0.25,
            "treasuryFees": 4000},
    # spot rates, plus an illustrative SOFR forward curve (tenor in years -> expected 1-month SOFR, %)
    "mkt": {"sofr": 3.65, "prime": 6.75, "ust5": 3.75, "useCurve": True, "shockBps": 0,
            "curve": [{"t": 0.5, "r": 3.55}, {"t": 1, "r": 3.50}, {"t": 2, "r": 3.55}, {"t": 3, "r": 3.65},
                      {"t": 5, "r": 3.85}, {"t": 7, "r": 4.00}, {"t": 10, "r": 4.15}]},
    "assume": {"hurdle": 12, "tax": 24, "capRate": 3.85, "liqBps": 25, "opexBps": 45, "fixedCost": 4000,
               "runoff": 25, "minCap": 10},
    "lev": {"moreDeposits": 400000, "moreTreasury": 9000, "competeRate": 6.60,
            "competeName": "Lakeside Community Bank"},
    "offers": [
        {"name": "First Harbor Bank", "amount": 1200000, "rate": 6.90, "termY": 5, "amortY": 7,
         "origPct": 1.0, "closing": 7500, "annualFee": 0},
        {"name": "Lakeside Community Bank", "amount": 1200000, "rate": 6.60, "termY": 5, "amortY": 7,
         "origPct": 1.5, "closing": 9000, "annualFee": 1500},
        {"name": "Online lender", "amount": 1200000, "rate": 9.75, "termY": 3, "amortY": 3,
         "origPct": 3.0, "closing": 0, "annualFee": 0},
    ],
}


def example() -> dict:
    """A deep copy of the example scenario (Cedar & Pine Millwork)."""
    return copy.deepcopy(EXAMPLE)


def apply_product_defaults(scenario: dict, product: str) -> dict:
    """Set a loan's term, index, spread and fees to the typical values for a product type."""
    p, loan = PRODUCTS[product], scenario["loan"]
    loan["product"] = product
    loan["termY"] = p["termY"]
    loan["amortY"] = p.get("amortY", p["termY"])
    if "index" in p:
        loan["index"] = p["index"]
    if "spread" in p:
        loan["spreadBps"] = p["spread"]
    loan["origPct"] = p["orig"]
    if p.get("rev"):
        loan["unusedBps"], loan["utilPct"] = p["unused"], p["util"]
    if "sbaFee" in p:
        loan["sbaFeePct"] = p["sbaFee"]
    if p.get("mca"):
        loan["mcaFactor"], loan["mcaMonths"] = p["factor"], p["months"]
    return scenario
