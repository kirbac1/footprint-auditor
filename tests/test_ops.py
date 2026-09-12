import functools
import json
import sqlite3
from types import SimpleNamespace

import pytest
from conftest import add_name, add_verified_email, login, reply, text, tool_use

from exposure_auditor.config import Settings
from exposure_auditor.llm import FALLBACK_BETA, LLM, make_llm
from exposure_auditor.tools.search import SearchResult
from exposure_auditor.worker import run_worker


def _usage(i, o, cache_read=0, cache_write=0):
    return SimpleNamespace(
        input_tokens=i, output_tokens=o, cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_write
    )


def _with_usage(response, usage):
    response.usage = usage
    return response


def test_scan_records_usage_cost_and_a_trace_free_of_personal_data(ctx):
    headers = login(ctx.client)
    add_verified_email(ctx, headers)
    name = add_name(ctx, headers)
    ctx.search.results = [
        SearchResult("https://www.spokeo.com/Maija-Meikalainen/p1", "Maija Meikäläinen, Helsinki", "Age 30s")
    ]
    ctx.llm.script += [
        _with_usage(reply(
            "tool_use",
            tool_use("s1", "search_web", {"query": "Maija Meikäläinen", "site": ""}),
            tool_use("s2", "search_web", {"query": "Jane Doe", "site": ""}),
        ), _usage(1000, 100, 0, 2000)),
        _with_usage(reply("tool_use", tool_use("r1", "record_finding", {
            "result_id": "r1", "category": "people_search", "matched_identifier_ids": [name["id"]],
            "conflicting_identifier_ids": [], "confidence": "high", "rationale": "Name matches.",
        })), _usage(200, 50, 2000)),
        _with_usage(reply("end_turn", text("done")), _usage(100, 20, 2100)),
    ]
    scan_id = ctx.client.post("/scan", headers=headers).json()["scan_id"]
    scan = ctx.client.get(f"/scan/{scan_id}", headers=headers).json()

    assert (scan["model_calls"], scan["tool_calls"]) == (3, 3)
    assert (scan["input_tokens"], scan["output_tokens"]) == (1300, 170)
    assert (scan["cache_read_tokens"], scan["cache_write_tokens"]) == (4100, 2000)
    expected = (1300 * 5 + 170 * 25 + 4100 * 5 * 0.1 + 2000 * 5 * 1.25) / 1_000_000
    assert scan["cost_usd"] == pytest.approx(expected)
    assert scan["duration_ms"] is not None

    trace = ctx.client.get(f"/scan/{scan_id}/trace", headers=headers).json()
    assert sum(e["kind"] == "model_call" for e in trace) == 3
    outcomes = {(e["name"], e["detail"]) for e in trace if e["kind"] == "tool_call"}
    assert {("search_web", "results:1"), ("search_web", "out_of_scope"), ("record_finding", "unclear")} <= outcomes
    blob = json.dumps(trace)
    for personal in ("Maija", "Meik", "Jane", "me@example.com", "spokeo", "Helsinki"):
        assert personal not in blob

    bob = login(ctx.client, "bob@example.com")
    assert ctx.client.get(f"/scan/{scan_id}/trace", headers=bob).status_code == 404


def _worker_mode(ctx):
    services = ctx.client.app.state.services
    services.settings = services.settings.model_copy(update={"scan_execution": "worker"})
    return services


def test_worker_mode_queues_and_the_worker_runs_it(ctx):
    services = _worker_mode(ctx)
    headers = login(ctx.client)
    add_verified_email(ctx, headers)
    ctx.llm.script.append(reply("end_turn", text("Nothing found.")))
    scan_id = ctx.client.post("/scan", headers=headers).json()["scan_id"]
    assert ctx.client.get(f"/scan/{scan_id}", headers=headers).json()["status"] == "queued"

    assert ctx.client.portal.call(functools.partial(run_worker, services, once=True)) == 1
    assert ctx.client.get(f"/scan/{scan_id}", headers=headers).json()["status"] == "completed"


def test_worker_fails_scans_a_dead_worker_left_running(ctx):
    services = _worker_mode(ctx)
    headers = login(ctx.client)
    add_verified_email(ctx, headers)
    scan_id = ctx.client.post("/scan", headers=headers).json()["scan_id"]
    db = sqlite3.connect(ctx.db_path)
    db.execute(
        "UPDATE scans SET status = 'running', started_at = '2000-01-01 00:00:00.000000' WHERE id = ?", (scan_id,)
    )
    db.commit()

    assert ctx.client.portal.call(functools.partial(run_worker, services, once=True)) == 0
    scan = ctx.client.get(f"/scan/{scan_id}", headers=headers).json()
    assert scan["status"] == "failed" and "interrupted" in scan["error"]


def test_token_refresh(ctx):
    headers = login(ctx.client)
    r = ctx.client.post("/auth/refresh", headers=headers)
    assert r.status_code == 200
    fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert ctx.client.get("/me", headers=fresh).status_code == 200
    assert ctx.client.post("/auth/refresh").status_code == 401


def test_reading_the_plan_does_not_rebuild_it(ctx):
    headers = login(ctx.client)
    add_verified_email(ctx, headers)
    assert ctx.client.get("/remediation-plan", headers=headers).json()["items"] == []

    built = ctx.client.post("/remediation-plan?jurisdiction=FI", headers=headers).json()["items"]
    stored = ctx.client.get("/remediation-plan", headers=headers).json()["items"]
    assert built and [i["id"] for i in stored] == [i["id"] for i in built]
    assert any("dvv.fi" in (i["url"] or "") for i in stored)

    # Rebuilding for another jurisdiction retires the items that no longer apply.
    ctx.client.post("/remediation-plan?jurisdiction=US", headers=headers)
    stored = ctx.client.get("/remediation-plan", headers=headers).json()["items"]
    assert not any("dvv.fi" in (i["url"] or "") for i in stored)


def test_rate_limits_are_shared_through_the_database(ctx):
    services = ctx.client.app.state.services
    hit = functools.partial(services.limiter.hit, "test:key", 2, 60)
    assert ctx.client.portal.call(hit) is None
    assert ctx.client.portal.call(hit) is None
    retry = ctx.client.portal.call(hit)
    assert retry is not None and 0 < retry <= 60


class _FakeClient:
    def __init__(self):
        self.calls = []
        self.messages = SimpleNamespace(create=self._plain)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._beta))

    async def _plain(self, **kwargs):
        self.calls.append(("plain", kwargs))

    async def _beta(self, **kwargs):
        self.calls.append(("beta", kwargs))


async def test_server_side_fallbacks_only_where_the_provider_supports_them():
    anthropic_api = _FakeClient()
    await LLM(anthropic_api, "anthropic", server_fallbacks=True).messages.create(model="claude-opus-5")
    kind, kwargs = anthropic_api.calls[0]
    assert kind == "beta" and kwargs["fallbacks"] == "default" and kwargs["betas"] == [FALLBACK_BETA]

    bedrock = _FakeClient()
    await LLM(bedrock, "bedrock", server_fallbacks=False).messages.create(model="anthropic.claude-opus-5")
    assert bedrock.calls[0][0] == "plain" and "fallbacks" not in bedrock.calls[0][1]


def test_provider_selection(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    base = {"_env_file": None, "jwt_secret": "s", "field_encryption_key": "k", "blind_index_key": "b"}

    assert Settings(**base).resolved_model_id == "anthropic.claude-opus-5"
    assert Settings(**base, llm_provider="foundry").resolved_model_id == "claude-opus-5"
    assert Settings(**base, llm_provider="anthropic", model_id="claude-sonnet-5").resolved_model_id == "claude-sonnet-5"

    assert make_llm(Settings(**base, llm_provider="anthropic")) is None  # no key anywhere
    assert make_llm(Settings(**base, llm_provider="foundry")) is None  # no resource
    llm = make_llm(Settings(**base, llm_provider="anthropic", anthropic_api_key="sk-test"))
    assert llm is not None and llm.provider == "anthropic"
