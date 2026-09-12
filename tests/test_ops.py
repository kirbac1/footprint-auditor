import functools
import json
import sqlite3
from types import SimpleNamespace

import pytest
from conftest import add_name, add_verified_email, login, reply, text, tool_use

from exposure_auditor.config import Settings
from exposure_auditor.llm import FALLBACK_BETA, LLM, make_llm
from exposure_auditor.openai_compat import ModelUnavailable
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


def test_the_trace_is_written_while_the_scan_is_still_running(ctx):
    """The page follows a scan by polling the trace, so steps have to land as
    they happen, not in one batch when the scan is over."""
    headers = login(ctx.client)
    add_verified_email(ctx, headers)
    add_name(ctx, headers)
    ctx.search.results = [SearchResult("https://www.spokeo.com/Maija/p1", "Maija Meikäläinen", "Helsinki")]
    ctx.llm.script += [
        reply("tool_use", tool_use("s1", "search_web", {"query": "Maija Meikäläinen", "site": ""})),
        # Stopping without recording earns one nudge, then the scan ends.
        reply("end_turn", text("Nothing to record.")),
        reply("end_turn", text("Nothing in those results was about them.")),
    ]

    seen: list[int] = []
    original = ctx.search.search

    async def counting_search(query, count=10):
        # The first model call is finished by the time a tool runs: its row
        # must already be readable from another connection.
        rows = sqlite3.connect(ctx.db_path).execute("select count(*) from scan_events").fetchone()[0]
        seen.append(rows)
        return await original(query, count)

    ctx.search.search = counting_search
    r = ctx.client.post("/scan", headers=headers)
    assert r.status_code == 202, r.text

    assert seen == [1], "the first model call should be visible before the scan ends"
    scan_id = r.json()["scan_id"]
    trace = ctx.client.get(f"/scan/{scan_id}/trace", headers=headers).json()
    assert [e["kind"] for e in trace] == ["model_call", "tool_call", "model_call", "model_call"]
    assert [e["seq"] for e in trace] == [0, 1, 2, 3]

    # Following a scan is one request per tick: two would spend the rate limit
    # twice as fast as the page polls.
    with_trace = ctx.client.get(f"/scan/{scan_id}?trace=true", headers=headers).json()
    assert [e["seq"] for e in with_trace["trace"]] == [0, 1, 2, 3]
    assert ctx.client.get(f"/scan/{scan_id}", headers=headers).json()["trace"] is None


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


def test_an_operator_can_set_a_password_without_a_reset_link(ctx, settings, monkeypatch, capsys):
    """Break-glass at the machine: no email, no token. It must still use the
    same email normalization as login, or it silently finds no account."""
    from argparse import Namespace

    import exposure_auditor.cli as cli

    login(ctx.client, email="me@example.com", password="correct-horse-battery")
    typed = iter(["a-much-longer-password", "a-much-longer-password"])
    monkeypatch.setattr("getpass.getpass", lambda *_: next(typed))
    monkeypatch.setattr("exposure_auditor.config.get_settings", lambda: settings)

    with pytest.raises(SystemExit) as exit_code:
        cli._set_password(Namespace(email="ME@Example.com  "))  # mixed case and spaces, as typed
    assert exit_code.value.code == 0
    assert "Password set" in capsys.readouterr().out

    # The old password is gone and the new one works.
    assert ctx.client.post(
        "/auth/token", data={"username": "me@example.com", "password": "correct-horse-battery"}
    ).status_code == 401
    assert ctx.client.post(
        "/auth/token", data={"username": "me@example.com", "password": "a-much-longer-password"}
    ).status_code == 200


def test_a_short_password_is_refused_and_changes_nothing(ctx, settings, monkeypatch):
    from argparse import Namespace

    import exposure_auditor.cli as cli

    login(ctx.client, email="me@example.com", password="correct-horse-battery")
    monkeypatch.setattr("getpass.getpass", lambda *_: "short")
    monkeypatch.setattr("exposure_auditor.config.get_settings", lambda: settings)

    with pytest.raises(SystemExit) as exit_code:
        cli._set_password(Namespace(email="me@example.com"))
    assert exit_code.value.code == 1
    assert ctx.client.post(
        "/auth/token", data={"username": "me@example.com", "password": "correct-horse-battery"}
    ).status_code == 200


def test_a_scan_that_loses_the_model_keeps_what_it_already_found(ctx):
    """A long scan on a slow model is minutes of work. Losing the connection
    on turn fourteen used to throw away the thirteen turns before it."""
    headers = login(ctx.client)
    add_verified_email(ctx, headers)
    name = add_name(ctx, headers)
    ctx.search.results = [
        SearchResult("https://www.spokeo.com/Maija-Meikalainen/p1", "Maija Meikäläinen, Helsinki", "Age 30s")
    ]

    class DiesAfterRecording:
        def __init__(self):
            self.messages = self
            self.calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return reply("tool_use", tool_use("s1", "search_web", {"query": "Maija Meikäläinen", "site": ""}))
            if self.calls == 2:
                return reply("tool_use", tool_use("r1", "record_finding", {
                    "result_id": "r1", "category": "people_search", "matched_identifier_ids": [name["id"]],
                    "conflicting_identifier_ids": [], "confidence": "medium", "rationale": "name and city",
                }))
            raise ModelUnavailable("ollama: RuntimeError")

    ctx.client.app.state.services.llm = DiesAfterRecording()
    scan_id = ctx.client.post("/scan", headers=headers).json()["scan_id"]
    scan = ctx.client.get(f"/scan/{scan_id}", headers=headers).json()

    assert scan["status"] == "failed"
    assert "lost contact" in scan["error"]
    assert [f["url"] for f in scan["findings"]] == ["https://www.spokeo.com/Maija-Meikalainen/p1"]
    # And the trace of the turns that did happen is still there.
    trace = ctx.client.get(f"/scan/{scan_id}/trace", headers=headers).json()
    assert [e["status"] for e in trace][-1] == "error"
