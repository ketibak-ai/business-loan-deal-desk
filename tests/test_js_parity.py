"""The browser engine (web/engine.js) must reproduce the Python engine on every scenario."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from scenarios import all_scenarios

from dealdesk import config, engine

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")
SCRIPT = Path(__file__).with_name("js_parity.cjs")
SCENARIOS = all_scenarios()


@pytest.fixture(scope="module")
def js(tmp_path_factory):
    f = tmp_path_factory.mktemp("js") / "scenarios.json"
    f.write_text(json.dumps([s for _, s in SCENARIOS]))
    out = subprocess.run([NODE, str(SCRIPT), str(f)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _approx(v):
    return None if v is None or not engine.isfinite(v) else pytest.approx(v, rel=1e-9, abs=1e-6)


def _same(got, want, path):
    """Deep compare a JS result with the Python one: numbers approximately, everything else exactly."""
    if isinstance(want, dict):
        assert isinstance(got, dict) and set(got) == set(want), path
        for k in want:
            _same(got[k], want[k], f"{path}.{k}")
    elif isinstance(want, list | tuple):
        assert len(got) == len(want), path
        for i, (g, w) in enumerate(zip(got, want, strict=True)):
            _same(g, w, f"{path}[{i}]")
    elif isinstance(want, bool) or want is None or isinstance(want, str):
        assert got == want, path
    else:
        assert got == _approx(want), path


def test_reference_data_matches(js):
    c = js["constants"]
    assert c["PD_BY_RATING"] == config.PD_BY_RATING
    assert c["SCORE_BANDS"] == config.SCORE_BANDS
    assert c["SBA_SPREAD_CAPS"] == config.SBA_SPREAD_CAPS
    assert c["EXAMPLE"] == config.EXAMPLE
    assert {k: list(v) for k, v in config.INDUSTRIES.items()} == c["INDUSTRIES"]
    assert {k: list(v) for k, v in config.COLLATERAL.items()} == c["COLLATERAL"]
    for k, p in config.PRODUCTS.items():  # numbers and labels (descriptions may be worded differently)
        assert {f: v for f, v in p.items() if f != "blurb"} == {f: v for f, v in c["PRODUCTS"][k].items()
                                                                if f != "blurb"}


@pytest.mark.parametrize("i", range(len(SCENARIOS)), ids=[n for n, _ in SCENARIOS])
def test_scenario_matches(js, i):
    s, got = SCENARIOS[i][1], js["results"][i]
    r = engine.run(s)
    for k, v in got["sch"].items():
        assert v == _approx(r["sch"].get(k)), f"sch.{k}"
    for k, v in got["cap"].items():
        want = r["cap"][k]
        if k == "binding":
            assert v == (want[0] if want else None)
        else:
            assert v == _approx(want), f"cap.{k}"
    assert got["eligibility"] == [[e["k"], e["status"]] for e in engine.eligibility(s, r["cap"])]
    if r["bank"]["na"]:
        assert got["bank"] is None
    else:
        b = r["bank"]
        assert got["bank"]["rating"] == b["rr"]["rating"]
        assert got["bank"]["tier"] == b["tier"]
        for k in ("lgd", "EC", "EL", "standalone", "relFloor", "costFloor", "walkaway", "cof",
                  "rarocStand", "rarocRel", "negotiable", "opening", "landing"):
            assert got["bank"][k] == _approx(b[k]), f"bank.{k}"
    lv = engine.levers(s, r)
    assert [x[0] for x in got["levers"]] == [x["id"] for x in lv]
    for (_, bps, dollars), want in zip(got["levers"], lv, strict=True):
        assert bps == _approx(want["bps"]) and dollars == _approx(want["dollars"])
    _same(got["sba"], engine.sba_review(s, r), "sba")
    _same(got["grad"], engine.graduation(s, r), "grad")
    for (apr, pay, total), o in zip(got["offers"], s["offers"], strict=True):
        sch = engine.offer_schedule(s, o)
        assert (apr, pay, total) == (_approx(sch["apr"]), _approx(sch["payment"]), _approx(sch["totalCost"]))
