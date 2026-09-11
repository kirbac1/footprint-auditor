import sqlite3

import anthropic
import httpx2
from conftest import add_name, add_verified_email, login, reply, text, tool_use

from exposure_auditor.tools.search import SearchResult

SPOKEO_URL = "https://www.spokeo.com/Maija-Meikalainen/p123"


def _run_scan_with_spokeo_hit(ctx, headers):
    """Add scope, then run a scan where the agent finds one Spokeo listing."""
    add_verified_email(ctx, headers)
    name = add_name(ctx, headers)
    city = ctx.client.post(
        "/identifiers", json={"kind": "city", "value": "Helsinki", "attest": True}, headers=headers
    ).json()
    ctx.search.results = [SearchResult(SPOKEO_URL, "Maija Meikäläinen, Helsinki", "Age 30s, phone ...")]
    ctx.llm.script += [
        reply(
            "tool_use",
            tool_use("t1", "search_web", {"query": '"Maija Meikäläinen"', "site": "spokeo.com"}),
            # Out of scope: must be rejected before it reaches the search provider.
            tool_use("t2", "search_web", {"query": "Jane Doe Helsinki", "site": ""}),
        ),
        reply(
            "tool_use",
            # A URL the agent never saw (hallucinated or injected): must be refused.
            tool_use("t3", "record_finding", {
                "result_id": "r99", "category": "data_broker",
                "matched_identifier_ids": [name["id"]], "confidence": "high", "rationale": "x",
            }),
            tool_use("t4", "record_finding", {
                "result_id": "r1", "category": "people_search",
                "matched_identifier_ids": [name["id"], city["id"]], "conflicting_identifier_ids": [],
                "confidence": "medium", "rationale": "Name and city match.",
            }),
        ),
        reply("end_turn", text("Searched the name on Spokeo; one listing recorded.")),
    ]
    r = ctx.client.post("/scan", headers=headers)
    assert r.status_code == 202, r.text
    return r.json()["scan_id"], name


def test_auth_required_and_login(ctx):
    assert ctx.client.get("/identifiers").status_code == 401
    headers = login(ctx.client)
    assert ctx.client.get("/identifiers", headers=headers).status_code == 200
    bad = ctx.client.post("/auth/token", data={"username": "me@example.com", "password": "wrong-password-1"})
    assert bad.status_code == 401
    unknown = ctx.client.post("/auth/token", data={"username": "nobody@example.com", "password": "whatever-12345"})
    assert unknown.status_code == 401


def test_register_does_not_reveal_existing_accounts(ctx):
    body = {"email": "me@example.com", "password": "correct-horse-battery"}
    first = ctx.client.post("/auth/register", json=body)
    second = ctx.client.post("/auth/register", json={**body, "password": "another-password-1"})
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()


def test_email_verification(ctx):
    headers = login(ctx.client)
    r = ctx.client.post("/identifiers", json={"kind": "email", "value": "Me@Example.com"}, headers=headers)
    assert r.status_code == 201
    ident = r.json()
    assert ident["status"] == "pending" and ident["value"] == "me@example.com"

    code = ctx.sender.codes["me@example.com"]
    wrong = "000000" if code != "000000" else "111111"
    assert ctx.client.post(f"/identifiers/{ident['id']}/verify", json={"code": wrong}, headers=headers).status_code == 400
    ok = ctx.client.post(f"/identifiers/{ident['id']}/verify", json={"code": code}, headers=headers)
    assert ok.status_code == 200 and ok.json()["status"] == "verified"
    again = ctx.client.post(f"/identifiers/{ident['id']}/verify", json={"code": code}, headers=headers)
    assert again.status_code == 409


def test_verification_locks_after_repeated_wrong_codes(ctx):
    headers = login(ctx.client)
    ident = ctx.client.post("/identifiers", json={"kind": "phone", "value": "+358 40 123 4567"}, headers=headers).json()
    code = ctx.sender.codes["+358401234567"]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        ctx.client.post(f"/identifiers/{ident['id']}/verify", json={"code": wrong}, headers=headers)
    r = ctx.client.post(f"/identifiers/{ident['id']}/verify", json={"code": code}, headers=headers)
    assert r.status_code == 429


def test_names_must_be_attested_full_and_capped(ctx):
    headers = login(ctx.client)
    post = lambda body: ctx.client.post("/identifiers", json=body, headers=headers)  # noqa: E731
    assert post({"kind": "name", "value": "Maija Meikäläinen"}).status_code == 422  # not attested
    assert post({"kind": "name", "value": "Maija", "attest": True}).status_code == 422  # one token
    for n in ("Maija Meikäläinen", "Maija Virtanen", "Maija Korhonen"):
        assert post({"kind": "name", "value": n, "attest": True}).status_code == 201
    assert post({"kind": "name", "value": "Maija Nieminen", "attest": True}).status_code == 422  # cap of 3
    assert post({"kind": "name", "value": "maija  MEIKÄLÄINEN", "attest": True}).status_code == 409  # duplicate


def test_scan_requires_a_verified_identifier(ctx):
    headers = login(ctx.client)
    add_name(ctx, headers)
    r = ctx.client.post("/scan", headers=headers)
    assert r.status_code == 409
    assert "Verify at least one email" in r.json()["detail"]
    assert ctx.llm.calls == []


def test_exposure_scan_keeps_agent_in_scope_and_on_real_results(ctx):
    headers = login(ctx.client)
    scan_id, _ = _run_scan_with_spokeo_hit(ctx, headers)

    scan = ctx.client.get(f"/scan/{scan_id}", headers=headers).json()
    assert scan["status"] == "completed"
    assert scan["summary"].startswith("Searched the name")
    assert [f["url"] for f in scan["findings"]] == [SPOKEO_URL]
    assert scan["findings"][0]["broker_id"] == "spokeo"

    # Only the in-scope query reached the provider.
    assert ctx.search.queries == ['"Maija Meikäläinen" site:spokeo.com']
    turn2 = {r["tool_use_id"]: r for r in ctx.llm.calls[1]["messages"][-1]["content"]}
    assert turn2["t2"]["is_error"] is True
    turn3 = {r["tool_use_id"]: r for r in ctx.llm.calls[2]["messages"][-1]["content"]}
    assert turn3["t3"]["is_error"] is True
    assert "is_error" not in turn3["t4"]

    # The identifiers go in the first user turn, never the (cached) system prompt.
    first = ctx.llm.calls[0]
    assert "Maija" not in first["system"] and "Maija" in first["messages"][0]["content"]


def test_scan_refused_up_front_when_nothing_can_search(ctx):
    headers = login(ctx.client)
    add_verified_email(ctx, headers)
    ctx.client.app.state.services.search = None
    r = ctx.client.post("/scan", headers=headers)
    assert r.status_code == 503 and "EA_BRAVE_API_KEY" in r.json()["detail"]
    assert ctx.llm.calls == []


def test_scan_refused_up_front_without_model(ctx):
    headers = login(ctx.client)
    add_verified_email(ctx, headers)
    ctx.client.app.state.services.llm = None
    assert ctx.client.post("/scan", headers=headers).status_code == 503


def test_model_api_error_fails_scan_with_operator_message(ctx):
    headers = login(ctx.client)
    add_verified_email(ctx, headers)

    class Unreachable:
        messages = None

        def __init__(self):
            self.messages = self

        async def create(self, **kwargs):
            raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://bedrock.invalid"))

    ctx.client.app.state.services.llm = Unreachable()
    scan_id = ctx.client.post("/scan", headers=headers).json()["scan_id"]
    scan = ctx.client.get(f"/scan/{scan_id}", headers=headers).json()
    assert scan["status"] == "failed"
    assert "could not be reached" in scan["error"]


def test_one_scan_at_a_time_and_daily_quota(ctx, settings):
    headers = login(ctx.client)
    _run_scan_with_spokeo_hit(ctx, headers)
    for _ in range(settings.scans_per_day - 1):
        ctx.llm.script.append(reply("end_turn", text("nothing new")))
        assert ctx.client.post("/scan", headers=headers).status_code == 202
    assert ctx.client.post("/scan", headers=headers).status_code == 429


def test_tenant_isolation(ctx):
    alice = login(ctx.client, "alice@example.com")
    scan_id, name = _run_scan_with_spokeo_hit(ctx, alice)
    item_id = ctx.client.get("/remediation-plan", headers=alice).json()["items"][0]["id"]

    bob = login(ctx.client, "bob@example.com")
    assert ctx.client.get(f"/scan/{scan_id}", headers=bob).status_code == 404
    assert ctx.client.post(f"/identifiers/{name['id']}/verify", json={"code": "123456"}, headers=bob).status_code == 404
    assert ctx.client.delete(f"/identifiers/{name['id']}", headers=bob).status_code == 404
    assert ctx.client.patch(f"/remediation-plan/items/{item_id}", json={"status": "done"}, headers=bob).status_code == 404
    assert ctx.client.get("/identifiers", headers=bob).json() == []
    assert ctx.client.get("/scans", headers=bob).json() == []


def test_pii_is_encrypted_at_rest(ctx):
    headers = login(ctx.client)
    add_verified_email(ctx, headers)
    add_name(ctx, headers)
    db = sqlite3.connect(ctx.db_path)
    rows = db.execute("SELECT value FROM identifiers").fetchall() + db.execute("SELECT email FROM users").fetchall()
    blob = b"".join(r[0] for r in rows)
    assert b"me@example.com" not in blob
    assert "Meikäläinen".encode() not in blob


def test_breach_check_only_for_verified_email(ctx):
    headers = login(ctx.client)
    ctx.client.post("/identifiers", json={"kind": "email", "value": "me@example.com"}, headers=headers)
    assert ctx.client.post("/breach-check", headers=headers).status_code == 409
    assert ctx.hibp.requests == []

    ctx.hibp.breaches["me@example.com"] = [{
        "Name": "ExampleForum", "Title": "Example Forum", "Domain": "forum.example",
        "BreachDate": "2021-03-01", "DataClasses": ["Email addresses", "Passwords"], "IsVerified": True,
    }]
    ident = ctx.client.get("/identifiers", headers=headers).json()[0]
    ctx.client.post(f"/identifiers/{ident['id']}/verify", json={"code": ctx.sender.codes["me@example.com"]}, headers=headers)
    r = ctx.client.post("/breach-check", headers=headers)
    assert r.status_code == 200
    assert [b["breach_name"] for b in r.json()["breaches"]] == ["ExampleForum"]
    assert ctx.hibp.requests[-1].headers["hibp-api-key"] == "test-hibp-key"


def test_password_range_accepts_only_a_prefix(ctx):
    headers = login(ctx.client)
    r = ctx.client.post("/breach-check/password-range", json={"sha1_prefix": "abcde"}, headers=headers)
    assert r.status_code == 200
    assert r.json() == {"prefix": "ABCDE", "suffixes": [{"suffix": "0018A45C4D1DEF81644B54AB7F969B88D65", "count": 3}]}
    assert str(ctx.hibp.requests[-1].url) == "https://api.pwnedpasswords.com/range/ABCDE"
    full_hash = "5BAA61E4C9B93F3F0682250B6CF8331B7EE68FD8"
    assert ctx.client.post("/breach-check/password-range", json={"sha1_prefix": full_hash}, headers=headers).status_code == 422


def test_remediation_plan(ctx):
    headers = login(ctx.client)
    _run_scan_with_spokeo_hit(ctx, headers)
    ctx.hibp.breaches["me@example.com"] = [{
        "Name": "ExampleForum", "Title": "Example Forum", "Domain": "forum.example",
        "BreachDate": "2021-03-01", "DataClasses": ["Email addresses", "Passwords"],
    }]
    ctx.client.post("/breach-check", headers=headers)

    plan = ctx.client.get("/remediation-plan?jurisdiction=EU", headers=headers).json()
    items = plan["items"]
    assert items[0]["action_type"] == "change_password" and items[0]["priority"] == 0
    spokeo = next(i for i in items if i["title"] == "Opt out of Spokeo")
    assert spokeo["url"] == "https://www.spokeo.com/optout"
    assert "Article 17" in spokeo["draft"] and SPOKEO_URL in spokeo["draft"]
    assert "Maija Meikäläinen" in spokeo["draft"]

    r = ctx.client.patch(f"/remediation-plan/items/{spokeo['id']}", json={"status": "sent"}, headers=headers)
    assert r.status_code == 200
    ca = ctx.client.get("/remediation-plan?jurisdiction=US-CA", headers=headers).json()["items"]
    spokeo_ca = next(i for i in ca if i["title"] == "Opt out of Spokeo")
    assert spokeo_ca["id"] == spokeo["id"] and spokeo_ca["status"] == "sent"
    assert "1798.105" in spokeo_ca["draft"]
    assert any("DROP" in i["title"] for i in ca)


def test_account_erasure(ctx):
    headers = login(ctx.client)
    _run_scan_with_spokeo_hit(ctx, headers)
    ctx.client.get("/remediation-plan", headers=headers)
    assert ctx.client.delete("/me", headers=headers).status_code == 204
    assert ctx.client.get("/identifiers", headers=headers).status_code == 401

    db = sqlite3.connect(ctx.db_path)
    for table in ("users", "identifiers", "scans", "findings", "remediation_items"):
        assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    actions = [r[0] for r in db.execute("SELECT action FROM audit_events")]
    assert "account_erased" in actions
