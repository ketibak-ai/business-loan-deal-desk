"""Offline retrieval eval (runs in CI, no API key): does guide search surface the right section?

Usage: python evals/retrieval_eval.py [--min-hit3 1.0]
"""

import argparse
import json
import sys
from pathlib import Path

from dealdesk.rag import search

CASES = [
    ("What is the difference between the interest rate and APR?", "Interest Rate and APR"),
    ("Why is my balloon payment so large?", "Amortization, Term and Balloon"),
    ("How do banks decide the lowest rate they can accept?", "Pricing Floors"),
    ("Why does moving my operating deposits get me a better rate?", "Relationship Pricing"),
    ("Is Prime plus 1 a good deal compared with SOFR pricing?", "Cost of Funds"),
    ("What hurdle rate do banks use for return on capital?", "Capital and the Hurdle Rate"),
    ("How much does the SBA guarantee on a 7(a) loan?", "SBA 7(a) Basics"),
    ("What fees does an SBA 7(a) loan charge?", "SBA 7(a) Rates and Fees"),
    ("How does the SBA 504 program split the financing?", "SBA 504 Loans"),
    ("Is a merchant cash advance with a 1.35 factor rate expensive?", "Merchant Cash Advances"),
    ("Should I use a line of credit or a term loan for inventory?", "Choosing the Right Loan"),
    ("What unused commitment fee should I expect on a revolver?", "Lines of Credit"),
    ("How should I use a competing term sheet?", "Using a Competing Offer"),
    ("Can I get the origination fee waived?", "Fee Negotiation"),
    ("When should I walk away from a loan offer?", "When to Walk Away"),
    ("What happens if I break a DSCR covenant?", "Financial Covenants"),
    ("How much covenant headroom do I need?", "Covenant Headroom"),
    ("Can a personal guarantee be capped or released?", "Personal Guarantees"),
    ("Is yield maintenance worse than a step-down prepayment penalty?", "Prepayment Penalties"),
    ("What does debt service coverage ratio mean?", "Debt Service Coverage Ratio"),
    ("What is expected loss and how does collateral change it?", "Expected Loss"),
    ("What is a compensating balance?", "Compensating Balance"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-hit3", type=float, default=1.0)
    ap.add_argument("--out", default="evals/results/retrieval.json")
    args = ap.parse_args()

    rows, hit1, hit3 = [], 0, 0
    for q, expected in CASES:
        got = [r["citation"] for r in search(q, k=3)]
        h1 = bool(got) and got[0].endswith(expected)
        h3 = any(c.endswith(expected) for c in got)
        hit1, hit3 = hit1 + h1, hit3 + h3
        rows.append({"query": q, "expected": expected, "retrieved": got, "hit@1": h1, "hit@3": h3})
        print(f"{'PASS' if h3 else 'FAIL'}  hit@1={int(h1)}  {q}")

    n = len(CASES)
    summary = {"cases": n, "hit@1": round(hit1 / n, 3), "hit@3": round(hit3 / n, 3)}
    print(json.dumps(summary))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    return 0 if summary["hit@3"] >= args.min_hit3 else 1


if __name__ == "__main__":
    sys.exit(main())
