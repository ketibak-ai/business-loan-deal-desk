"""Command line: `dealdesk analyze | compare | ask | build-site`."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from . import service
from .engine import money, pct


def _load(path: str | None) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else service.example_scenario()


def cmd_analyze(a: argparse.Namespace) -> None:
    r = service.analyze(_load(a.file))
    if a.json:
        print(json.dumps(r, indent=2))
        return
    c, cap, b = r["cost"], r["capacity"], r["bank_view"]
    print(f"\n{r['product_label']}")
    print(f"  Stated rate {pct(c['stated_rate_pct'] or float('nan'))}   APR {pct(c['apr_pct'])}   "
          f"payment {money(c['monthly_payment'])}/mo   total cost {money(c['total_cost'])}")
    print(f"  DSCR {cap['dscr']:.2f}x   debt/EBITDA {cap['debt_to_ebitda']:.2f}x   "
          f"binding limit: {cap['binding_limit']['name']} {money(cap['binding_limit']['amount'])}")
    if b["applicable"]:
        rt, sp = b["rates_pct"], b["spreads_bps"]
        print(f"\nBank view (estimated, risk rating {b['risk_rating']})")
        for k in ("offered", "loan_only_target", "walk_away", "cost_floor", "opening_ask", "realistic_outcome"):
            print(f"  {k.replace('_', ' '):<20} {pct(rt[k]):>7}  ({sp[k]:.0f} bps)")
        print(f"  room to negotiate    {b['room_to_negotiate_bps']:.0f} bps, worth about "
              f"{money(r['savings_at_realistic_outcome'])} at the realistic outcome")
    print("\nNegotiation options")
    for lv in r["levers"]:
        worth = money(lv["dollars"]) if lv["dollars"] else "terms"
        print(f"  {worth:>10}  {lv['title']}")
    print("\n" + r["talking_points"])


def cmd_compare(a: argparse.Namespace) -> None:
    s = _load(a.file)
    r = service.compare(s["offers"], s.get("mkt"))
    for o in r["offers"]:
        flag = "  <- lowest APR" if o["lowest_apr"] else ""
        print(f"  {o['name']:<28} rate {pct(o['rate_pct'])}  APR {pct(o['apr_pct'])}  "
              f"payment {money(o['monthly_payment'])}  total {money(o['total_cost'])}{flag}")
    if r["note"]:
        print(f"\n{r['note']}")


def cmd_ask(a: argparse.Namespace) -> None:
    from .agent import ask

    r = ask(a.question)
    print(r.answer)
    print(f"\n[{r.model} · {len(r.tool_calls)} tool calls · {r.usage['input_tokens']} in / "
          f"{r.usage['output_tokens']} out tokens · {r.latency_s}s]")


def cmd_build_site(a: argparse.Namespace) -> None:
    src, out = Path(__file__).with_name("web"), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, out / f.name)
    (out / "example.json").write_text(json.dumps(service.example_scenario(), indent=2), encoding="utf-8")
    print(f"Site written to {out}")


def main() -> None:
    p = argparse.ArgumentParser(prog="dealdesk", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    an = sub.add_parser("analyze", help="analyze a loan scenario (default: the built-in example)")
    an.add_argument("--file", help="scenario JSON, same shape as the web app's")
    an.add_argument("--json", action="store_true", help="print the full JSON result")
    an.set_defaults(func=cmd_analyze)

    cp = sub.add_parser("compare", help="compare the offers in a scenario file")
    cp.add_argument("--file")
    cp.set_defaults(func=cmd_compare)

    q = sub.add_parser("ask", help="ask the borrower's advisor (needs ANTHROPIC_API_KEY)")
    q.add_argument("question")
    q.set_defaults(func=cmd_ask)

    b = sub.add_parser("build-site", help="copy the web app into a folder for GitHub Pages")
    b.add_argument("--out", default="docs")
    b.set_defaults(func=cmd_build_site)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
