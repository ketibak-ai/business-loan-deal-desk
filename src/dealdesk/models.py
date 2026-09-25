"""Request schemas. Field names match the browser app's scenario JSON, so a scenario saved in the
web app can be posted to the API unchanged."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import EXAMPLE

Product = Literal["term", "loc", "equip", "cre", "sba7a", "sba504", "invoice", "mca"]
Index = Literal["sofr", "prime", "ust5"]
Industry = Literal["prof", "health", "tech", "mfg", "dist", "constr", "trans", "retail", "rest", "ag", "energy"]
Collateral = Literal["none", "blanket", "equip", "re", "cash"]

_E = EXAMPLE


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Loan(_Strict):
    product: Product = "term"
    lender: str = Field("", max_length=120)
    amount: float = Field(_E["loan"]["amount"], gt=0, le=1e9)
    termY: float = Field(5, gt=0, le=40)
    amortY: float = Field(7, gt=0, le=40)
    index: Index = "sofr"
    spreadBps: float = Field(325, ge=-500, le=5000)
    utilPct: float = Field(40, ge=0, le=100)
    unusedBps: float = Field(25, ge=0, le=500)
    mcaFactor: float = Field(1.35, ge=1, le=3)
    mcaMonths: float = Field(9, ge=1, le=36)
    origPct: float = Field(1.0, ge=0, le=15)
    closingCost: float = Field(0, ge=0, le=1e7)
    annualFee: float = Field(0, ge=0, le=1e6)
    sbaFeePct: float = Field(2.5, ge=0, le=10)
    prepay: Literal["none", "step", "ym"] = "none"
    covDSCR: float = Field(1.25, ge=0, le=5)


class Business(_Strict):
    name: str = Field("", max_length=120)
    industry: Industry = "prof"
    years: float = Field(5, ge=0, le=200)
    revenue: float = Field(1_000_000, ge=0, le=1e11)
    ebitda: float = Field(150_000, ge=-1e10, le=1e10)
    existingDebt: float = Field(0, ge=0, le=1e11)
    existingDS: float = Field(0, ge=0, le=1e10)
    fico: float = Field(700, ge=300, le=850)
    pg: bool = True
    collType: Collateral = "none"
    collValue: float = Field(0, ge=0, le=1e11)
    deposits: float = Field(0, ge=0, le=1e11)
    depositRate: float = Field(0.25, ge=0, le=20)
    treasuryFees: float = Field(0, ge=0, le=1e8)


class CurvePoint(_Strict):
    t: float = Field(..., gt=0, le=40, description="Tenor in years")
    r: float = Field(..., ge=-2, le=25, description="Expected 1-month SOFR at that tenor, %")


class Market(_Strict):
    sofr: float = Field(_E["mkt"]["sofr"], ge=-2, le=25, description="Spot SOFR, %")
    prime: float = Field(_E["mkt"]["prime"], ge=0, le=30)
    ust5: float = Field(_E["mkt"]["ust5"], ge=-2, le=25)
    useCurve: bool = Field(True, description="Project floating rates along the SOFR forward curve")
    shockBps: float = Field(0, ge=-500, le=1000, description="Parallel shift applied to the SOFR path")
    curve: list[CurvePoint] = Field(default_factory=lambda: [CurvePoint(**p) for p in _E["mkt"]["curve"]],
                                    max_length=30)


class Assumptions(_Strict):
    hurdle: float = Field(12, gt=0, le=50)
    tax: float = Field(24, ge=0, lt=100)
    capRate: float = Field(3.85, ge=0, le=25)
    liqBps: float = Field(25, ge=0, le=500)
    opexBps: float = Field(45, ge=0, le=1000)
    fixedCost: float = Field(4000, ge=0, le=1e6)
    runoff: float = Field(25, ge=0, le=100)
    minCap: float = Field(10, ge=0, le=50)


class Levers(_Strict):
    moreDeposits: float = Field(0, ge=0, le=1e11)
    moreTreasury: float = Field(0, ge=0, le=1e8)
    competeRate: float = Field(0, ge=0, le=100)
    competeName: str = Field("", max_length=120)


class Offer(_Strict):
    name: str = Field("Offer", max_length=120)
    amount: float = Field(..., gt=0, le=1e9)
    rate: float = Field(..., gt=0, le=100)
    termY: float = Field(..., gt=0, le=40)
    amortY: float = Field(..., gt=0, le=40)
    origPct: float = Field(0, ge=0, le=15)
    closing: float = Field(0, ge=0, le=1e7)
    annualFee: float = Field(0, ge=0, le=1e6)


class Scenario(_Strict):
    loan: Loan = Loan()
    biz: Business = Business()
    mkt: Market = Market()
    assume: Assumptions = Assumptions()
    lev: Levers = Levers()
    offers: list[Offer] = Field(default_factory=list, max_length=10)


class CompareIn(_Strict):
    offers: list[Offer] = Field(..., min_length=1, max_length=10)
    mkt: Market = Market()


class QueryIn(_Strict):
    query: str = Field(..., min_length=2, max_length=500)


class AskIn(_Strict):
    question: str = Field(..., min_length=3, max_length=4000)
