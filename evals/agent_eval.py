"""End-to-end eval of the Claude borrower's advisor (calls the live API; costs a few cents per run).

Each case is graded with deterministic checks, so no LLM judge is needed:
  * tools    - the agent must call these tools (grounding, not guessing); "a|b" means either
  * contains - the answer must mention each phrase (case-insensitive)
  * numbers  - a ground-truth value computed by the engine must appear in the answer (% or bps, within tolerance)

Usage: ANTHROPIC_API_KEY=... python evals/agent_eval.py [--only 3]
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from dealdesk import service
from dealdesk.agent import ask
from dealdesk.config import example

EXAMPLE_Q = ("I run a manufacturing business: 12 years, $6.2M revenue, $850K EBITDA, $900K existing debt with "
             "$240K a year in payments, owner credit score 735, personal guarantee, and a blanket lien on "
             "receivables and inventory worth $1.4M. First Harbor Bank offered a $1.2M term loan, 5-year term, "
             "7-year amortization, SOFR + 325 bps, 1% origination fee and $7,500 closing costs. We keep $150K "
             "in deposits there and pay about $4K a year in treasury fees.")


def _flat_example() -> dict:
    return dict(product="term", amount=1200000, term_years=5, amortization_years=7, rate_index="sofr",
                spread_bps=325, origination_fee_pct=1.0, closing_costs=7500, industry="mfg",
                years_in_business=12, annual_revenue=6200000, ebitda=850000, existing_debt=900000,
                existing_annual_debt_payments=240000, owner_credit_score=735, personal_guarantee=True,
                collateral_type="blanket", collateral_value=1400000, operating_deposits=150000,
                treasury_fees=4000)


def cases():
    base = service.analyze(service.quick_scenario(**_flat_example()))
    mca = service.analyze(service.quick_scenario(product="mca", amount=100000))
    cmp_ = service.compare(example()["offers"])
    lakeside = next(o for o in cmp_["offers"] if o["name"].startswith("Lakeside"))
    return [
        {"id": "true-cost", "q": EXAMPLE_Q + " What does this loan really cost me per year, fees included?",
         "tools": ["analyze_loan|negotiate_loan"], "contains": ["APR"],
         "numbers": [("pct", base["cost"]["apr_pct"], 0.05)]},
        {"id": "afford", "q": EXAMPLE_Q + " Can my business afford it? What is my debt service coverage?",
         "tools": ["analyze_loan|negotiate_loan"], "contains": ["1.8"], "numbers": []},
        {"id": "walk-away", "q": EXAMPLE_Q + " What is the lowest rate this bank would likely accept?",
         "tools": ["analyze_loan|negotiate_loan"], "contains": [],
         "numbers": [("pct", base["bank_view"]["rates_pct"]["walk_away"], 0.05)]},
        {"id": "best-lever", "q": EXAMPLE_Q + " I could move another $400K of operating deposits. How much "
                                             "is that worth in rate?",
         "tools": ["negotiate_loan"], "contains": ["deposit"], "numbers": []},
        {"id": "compare", "q": "Compare these: First Harbor $1.2M at 6.90%, 5y term, 7y amortization, 1% fee, "
                               "$7,500 closing; Lakeside $1.2M at 6.60%, 5y/7y, 1.5% fee, $9,000 closing, "
                               "$1,500 annual fee; online lender $1.2M at 9.75%, 3y/3y, 3% fee. Which is cheapest?",
         "tools": ["compare_offers"], "contains": ["First Harbor"],
         "numbers": [("pct", lakeside["apr_pct"], 0.05)]},
        {"id": "mca", "q": "A funder offered me a $100,000 merchant cash advance at a 1.35 factor over 9 months "
                           "with a 2.5% fee. What APR is that?",
         "tools": ["analyze_loan|negotiate_loan"], "contains": [],
         "numbers": [("pct", mca["cost"]["apr_pct"], 1.0)]},
        {"id": "sba-guarantee", "q": "How much of an SBA 7(a) loan does the SBA guarantee?",
         "tools": ["search_guides"], "contains": ["75"], "numbers": []},
        {"id": "guarantee", "q": "Can I limit the personal guarantee the bank is asking for?",
         "tools": ["search_guides"], "contains": ["cap"], "numbers": []},
        {"id": "out-of-scope", "q": "What's the weather in Chicago tomorrow?",
         "tools": [], "contains": [], "numbers": [], "max_tools": 0},
    ]


def _numbers_in(text):
    out = []
    for m in re.finditer(r"(-?\d[\d,]*\.?\d*)\s*(%|bps|basis points)", text):
        out.append((float(m.group(1).replace(",", "")), "pct" if m.group(2) == "%" else "bps"))
    return out


def grade(case, r):
    called = {c["tool"] for c in r.tool_calls}
    checks = {}
    for t in case["tools"]:
        checks[f"tool:{t}"] = any(opt in called for opt in t.split("|"))
    for phrase in case["contains"]:
        checks[f"contains:{phrase}"] = phrase.lower() in r.answer.lower()
    found = _numbers_in(r.answer)
    for kind, value, tol in case["numbers"]:
        checks[f"{kind}:{value:.2f}"] = any(u == kind and abs(v - value) <= tol for v, u in found)
    if "max_tools" in case:
        checks["no_tools"] = len(r.tool_calls) <= case["max_tools"]
    return checks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, help="run only the first N cases")
    ap.add_argument("--out", default="evals/results/agent.json")
    args = ap.parse_args()

    all_cases = cases()[: args.only] if args.only else cases()
    rows, passed, tokens, model = [], 0, {"input": 0, "output": 0}, None
    t0 = time.time()
    for case in all_cases:
        r = ask(case["q"])
        checks = grade(case, r)
        ok = all(checks.values())
        passed += ok
        tokens["input"] += r.usage["input_tokens"]
        tokens["output"] += r.usage["output_tokens"]
        model = r.model
        rows.append({"id": case["id"], "pass": ok, "checks": checks, "answer": r.answer,
                     "tool_calls": r.tool_calls, "usage": r.usage, "latency_s": r.latency_s})
        print(f"{'PASS' if ok else 'FAIL'}  {case['id']:<14} {[k for k, v in checks.items() if not v] or ''}")

    summary = {"cases": len(all_cases), "passed": passed, "pass_rate": round(passed / len(all_cases), 3),
               "tokens": tokens, "wall_s": round(time.time() - t0, 1), "model": model}
    print(json.dumps(summary))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, default=str))
    return 0 if summary["pass_rate"] >= 0.75 else 1


if __name__ == "__main__":
    sys.exit(main())
