"""REST API: loan analysis, bank-view estimate, negotiation plan, offer comparison, guide search and
the Claude borrower's advisor. Also serves the web app at /.

Run:  uvicorn dealdesk.api:app --reload
"""

from __future__ import annotations

import logging
import os
import secrets
import time
import uuid
from pathlib import Path

import anthropic
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles

from . import __version__, service, site
from .models import AskIn, CompareIn, QueryIn, Scenario
from .observability import METRICS, log_event, request_id, setup_logging

setup_logging(os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("dealdesk.api")

app = FastAPI(
    title="Borrower's Deal Desk API",
    version=__version__,
    description="Business loan calculator and negotiation engine: true cost, affordability, the bank's "
                "estimated pricing floors, negotiation options and a Claude-powered borrower's advisor. "
                "For education and planning; not a credit decision or financial advice.",
)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Security(_api_key_header)) -> None:
    """If APP_API_KEY is set, every data endpoint requires a matching X-API-Key header."""
    expected = os.getenv("APP_API_KEY")
    if expected and not (key and secrets.compare_digest(key, expected)):
        raise HTTPException(status_code=401, detail="invalid or missing API key")


@app.middleware("http")
async def observe(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    token = request_id.set(rid)
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        METRICS.inc("http_requests_total", method=request.method, path=path, status=status)
        METRICS.observe("http_request_seconds", elapsed, path=path)
        log_event(log, "request", method=request.method, path=path, status=status,
                  latency_ms=round(elapsed * 1000, 1))
        request_id.reset(token)


# ---------- endpoints --------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "products": len(service.catalog()["products"])}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return METRICS.render()


@app.get("/api/catalog", dependencies=[Depends(require_api_key)])
def catalog() -> dict:
    return service.catalog()


@app.get("/api/example", dependencies=[Depends(require_api_key)])
def example() -> dict:
    return service.example_scenario()


@app.post("/api/analyze", dependencies=[Depends(require_api_key)])
def analyze(scenario: Scenario) -> dict:
    return service.analyze(scenario)


@app.post("/api/negotiate", dependencies=[Depends(require_api_key)])
def negotiate(scenario: Scenario) -> dict:
    return service.negotiate(scenario)


@app.post("/api/compare", dependencies=[Depends(require_api_key)])
def compare(body: CompareIn) -> dict:
    return service.compare(body.offers, body.mkt)


@app.post("/api/guides/search", dependencies=[Depends(require_api_key)])
def guides_search(q: QueryIn) -> list[dict]:
    return service.guide_search(q.query)


@app.post("/api/ask", dependencies=[Depends(require_api_key)])
def ask(body: AskIn) -> dict:
    from .agent import ask as agent_ask  # lazy: the API works without LLM credentials

    try:
        r = agent_ask(body.question)
    except (anthropic.AuthenticationError, TypeError) as exc:  # TypeError: no credentials
        raise HTTPException(503, "LLM credentials not configured (set ANTHROPIC_API_KEY)") from exc
    except anthropic.RateLimitError as exc:
        raise HTTPException(429, "LLM rate limited; retry shortly") from exc
    except anthropic.APIConnectionError as exc:
        raise HTTPException(502, "LLM service unreachable") from exc
    except anthropic.APIStatusError as exc:
        log.exception("llm_error")
        raise HTTPException(502, f"LLM error {exc.status_code}") from exc
    return {"answer": r.answer, "tool_calls": r.tool_calls, "usage": r.usage,
            "model": r.model, "stop_reason": r.stop_reason, "latency_s": r.latency_s}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> str:
    return site.index_html()


# The browser app's scripts (same engine, ported to JS) are served last so API routes take precedence.
app.mount("/", StaticFiles(directory=Path(__file__).with_name("web"), html=True), name="web")
