"""API and agent tests. The agent runs against a scripted fake Claude client, so no API key is needed."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from dealdesk import agent, service
from dealdesk.api import app
from dealdesk.config import example
from dealdesk.rag import search

client = TestClient(app)


def test_health_and_metrics():
    assert client.get("/health").json()["status"] == "ok"
    assert "http_requests_total" in client.get("/metrics").text


def test_request_id_header_propagates():
    assert client.get("/health", headers={"X-Request-ID": "abc123"}).headers["X-Request-ID"] == "abc123"


def test_web_app_is_served():
    r = client.get("/")
    assert r.status_code == 200 and "Deal Desk" in r.text
    assert r.text.startswith("<!doctype html>") and 'name="viewport"' in r.text  # standards mode, mobile-ready
    assert r.text.index("</head>") < r.text.index('<div class="wrap">')
    assert client.get("/engine.js").status_code == 200


def test_analyze_example_round_trip():
    r = client.post("/api/analyze", json=client.get("/api/example").json())
    assert r.status_code == 200
    body = r.json()
    assert body["bank_view"]["applicable"] is True
    assert body["bank_view"]["rates_pct"]["walk_away"] < body["bank_view"]["rates_pct"]["offered"]
    assert body["cost"]["apr_pct"] > body["cost"]["stated_rate_pct"]
    assert "TALKING POINTS" in body["talking_points"]


def test_small_business_segment_in_api():
    r = client.post("/api/analyze", json={"loan": {"amount": 250000},
                                          "biz": {"revenue": 1500000, "ebitda": 250000}}).json()
    bv = r["bank_view"]
    assert bv["segment"] == "small" and bv["risk_rating"] in "ABCDE" and bv["credit_score"] is not None
    assert bv["room_to_negotiate_bps"] <= 50 + 1e-6


def test_analyze_partial_scenario_uses_defaults():
    r = client.post("/api/analyze", json={"loan": {"product": "equip", "amount": 300000}})
    assert r.status_code == 200 and r.json()["product"] == "equip"


def test_validation_errors():
    assert client.post("/api/analyze", json={"loan": {"amount": -5}}).status_code == 422
    assert client.post("/api/analyze", json={"loan": {"product": "yacht"}}).status_code == 422
    assert client.post("/api/analyze", json={"loan": {"surprise": 1}}).status_code == 422


def test_mca_analysis_is_strict_json():
    r = client.post("/api/analyze", json={"loan": {"product": "mca", "amount": 100000}})
    assert r.status_code == 200
    body = r.json()
    assert body["cost"]["stated_rate_pct"] is None and body["bank_view"]["applicable"] is False
    json.loads(r.text)  # no NaN tokens


def test_negotiate_and_compare():
    n = client.post("/api/negotiate", json=example()).json()
    assert n["levers"] and n["room_to_negotiate_bps"] > 0
    c = client.post("/api/compare", json={"offers": example()["offers"]}).json()
    # the lowest rate is not the cheapest loan: Lakeside's 6.60% carries higher fees than First Harbor's 6.90%
    by_name = {o["name"]: o for o in c["offers"]}
    assert by_name["Lakeside Community Bank"]["rate_pct"] < by_name["First Harbor Bank"]["rate_pct"]
    assert by_name["Lakeside Community Bank"]["apr_pct"] > by_name["First Harbor Bank"]["apr_pct"]
    assert c["lowest_apr"] == "First Harbor Bank"
    assert sum(o["lowest_apr"] for o in c["offers"]) == 1


def test_api_key_enforced(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "s3cret")
    assert client.get("/api/catalog").status_code == 401
    assert client.get("/api/catalog", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/health").status_code == 200  # health stays open


def test_guide_search_cites_sections():
    top = search("how does a personal guarantee work and can it be limited")[0]
    assert top["citation"].endswith("Personal Guarantees")


def test_quick_scenario_maps_flat_fields():
    s = service.quick_scenario(product="sba7a", amount=400000, ebitda=120000, personal_guarantee=False)
    assert s["loan"]["product"] == "sba7a" and s["loan"]["index"] == "prime"
    assert s["biz"]["ebitda"] == 120000 and s["biz"]["pg"] is False
    with pytest.raises(ValueError):
        service.quick_scenario(bogus=1)


# ---------- agent loop with a scripted fake client ------------------------------------------
def _block(**kw):
    return SimpleNamespace(**kw)


def _msg(content, stop):
    usage = SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0)
    return SimpleNamespace(content=content, stop_reason=stop, usage=usage, model="fake-model")


class FakeClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})  # snapshot
        return self.script.pop(0)


def test_agent_runs_tools_and_returns_answer(monkeypatch):
    monkeypatch.setattr(agent, "MODEL", "fake-model")
    script = [
        _msg([_block(type="tool_use", id="t1", name="negotiate_loan",
                     input={"amount": 1200000, "spread_bps": 325, "ebitda": 850000}),
              _block(type="tool_use", id="t2", name="search_guides", input={"query": "competing offer"})],
             "tool_use"),
        _msg([_block(type="text", text="Ask for SOFR + 245 bps.")], "end_turn"),
    ]
    fake = FakeClient(script)
    r = agent.ask("How much room do I have?", client=fake)
    assert r.answer == "Ask for SOFR + 245 bps."
    assert [c["tool"] for c in r.tool_calls] == ["negotiate_loan", "search_guides"]
    results = fake.calls[1]["messages"][-1]["content"]  # both results in ONE user message
    assert len(results) == 2 and not any(x["is_error"] for x in results)
    assert "walk_away" in json.loads(results[0]["content"])["rates_pct"]
    assert r.usage["input_tokens"] == 200


def test_agent_tool_errors_go_back_to_model(monkeypatch):
    monkeypatch.setattr(agent, "MODEL", "fake-model")
    script = [
        _msg([_block(type="tool_use", id="t1", name="analyze_loan", input={"amount": -1})], "tool_use"),
        _msg([_block(type="text", text="That amount is not valid.")], "end_turn"),
    ]
    fake = FakeClient(script)
    r = agent.ask("Loan of -1?", client=fake)
    assert r.tool_calls[0]["is_error"] is True
    assert fake.calls[1]["messages"][-1]["content"][0]["is_error"] is True


def test_agent_handles_refusal(monkeypatch):
    monkeypatch.setattr(agent, "MODEL", "fake-model")
    assert "declined" in agent.ask("x", client=FakeClient([_msg([], "refusal")])).answer


def test_agent_uses_fallbacks_on_opus(monkeypatch):
    monkeypatch.setattr(agent, "MODEL", "claude-opus-5")
    fake = FakeClient([_msg([_block(type="text", text="ok")], "end_turn")])
    agent.ask("hi", client=fake)
    assert fake.calls[0]["betas"] == ["server-side-fallback-2026-07-01"]
    assert fake.calls[0]["thinking"] == {"type": "adaptive"}


@pytest.mark.parametrize("tool", [t["name"] for t in agent.TOOLS])
def test_every_tool_has_handler(tool):
    assert tool in agent._HANDLERS


def test_every_tool_runs_on_minimal_input():
    samples = {"analyze_loan": {}, "negotiate_loan": {"product": "loc"},
               "compare_offers": {"offers": example()["offers"]}, "list_loan_products": {},
               "search_guides": {"query": "SBA guarantee fee"}}
    for name, args in samples.items():
        _, is_error = agent.run_tool(name, args)
        assert not is_error, name
