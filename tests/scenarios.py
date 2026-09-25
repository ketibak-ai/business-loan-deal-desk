"""Shared test scenarios: every product type plus edge cases (weak credit, no collateral, small SBA)."""

from dealdesk.config import PRODUCTS, apply_product_defaults, example


def _variant(product: str | None = None, **edits) -> dict:
    s = example()
    if product:
        apply_product_defaults(s, product)
    for path, value in edits.items():
        section, field = path.split("__")
        s[section][field] = value
    return s


def all_scenarios() -> list[tuple[str, dict]]:
    out = [("example", example())]
    out += [(f"product-{p}", _variant(p)) for p in PRODUCTS]
    out += [
        ("no-guarantee-unsecured", _variant(biz__pg=False, biz__collType="none", biz__collValue=0)),
        ("weak-cash-flow", _variant(biz__ebitda=260000, biz__years=1.5, biz__fico=630, biz__industry="rest")),
        ("strong-credit-cash", _variant(biz__ebitda=3000000, biz__fico=790, biz__collType="cash",
                                        biz__collValue=2000000, biz__industry="tech")),
        ("small-sba", _variant("sba7a", loan__amount=120000, biz__years=1, biz__collType="none")),
        ("real-estate-cre", _variant("cre", loan__amount=2500000, biz__collType="re", biz__collValue=3400000,
                                     loan__prepay="ym")),
        ("line-low-use", _variant("loc", loan__utilPct=20, loan__amount=1000000)),
        ("big-deposits", _variant(biz__deposits=2000000, biz__treasuryFees=40000)),
        ("zero-fee-no-compete", _variant(loan__origPct=0, loan__closingCost=0, lev__competeRate=0,
                                         lev__moreDeposits=0, lev__moreTreasury=0)),
        ("mca-short", _variant("mca", loan__mcaMonths=6, loan__mcaFactor=1.25)),
        ("flat-rates", _variant(mkt__useCurve=False)),
        ("shock-up-200", _variant(mkt__shockBps=200)),
        ("line-shock-down", _variant("loc", mkt__shockBps=-100)),
        ("fixed-no-curve", _variant("equip", mkt__useCurve=False)),
        ("small-auto", _variant(loan__amount=300000, biz__revenue=2000000, biz__ebitda=350000,
                                biz__existingDebt=100000, biz__existingDS=30000, biz__collValue=400000)),
        ("small-forced-example", _variant(biz__tier="small")),
        ("commercial-forced-small", _variant(loan__amount=300000, biz__revenue=2000000, biz__ebitda=350000,
                                             biz__existingDebt=100000, biz__existingDS=30000, biz__tier="commercial")),
        ("small-sba-weak", _variant("sba7a", loan__amount=250000, biz__revenue=1500000, biz__ebitda=160000,
                                    biz__existingDebt=0, biz__existingDS=0, biz__fico=655, biz__years=1.5,
                                    biz__collType="none", biz__collValue=0)),
        ("small-line-tight-grid", _variant("loc", loan__amount=400000, biz__revenue=3000000, biz__ebitda=300000,
                                           biz__existingDebt=200000, biz__existingDS=50000, assume__discretionBps=25)),
    ]
    return out
