import sqlite3

from conftest import add_verified_email, login, reply, text, tool_use


def _add_username(ctx, headers, value="maija_m"):
    r = ctx.client.post("/identifiers", json={"kind": "username", "value": value, "attest": True}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _start(ctx, headers, ident, platform="github"):
    return ctx.client.post(f"/identifiers/{ident['id']}/proof", json={"platform": platform}, headers=headers)


def _check(ctx, headers, ident):
    return ctx.client.post(f"/identifiers/{ident['id']}/proof/check", headers=headers)


def test_unproven_usernames_are_left_out_of_scans(ctx):
    headers = login(ctx.client)
    add_verified_email(ctx, headers)
    _add_username(ctx, headers)
    ctx.llm.script += [
        reply("tool_use", tool_use("s", "search_web", {"query": "maija_m", "site": ""})),
        reply("end_turn", text("done")),
    ]
    assert ctx.client.post("/scan", headers=headers).status_code == 202
    assert "maija_m" not in ctx.llm.calls[0]["messages"][0]["content"]
    rejected = ctx.llm.calls[1]["messages"][-1]["content"][0]
    assert rejected["is_error"] and "in-scope" in rejected["content"]
    # And it doesn't count as a profile for the impersonation check either.
    assert ctx.client.post("/impersonation-check", headers=headers).status_code == 409


def test_github_bio_proof(ctx):
    headers = login(ctx.client)
    add_verified_email(ctx, headers)
    ident = _add_username(ctx, headers)

    r = _start(ctx, headers, ident)
    assert r.status_code == 200
    code = r.json()["proof_code"]
    assert code.startswith("footprint-verify-") and r.json()["proof_platform"] == "github"

    ctx.hibp.bios[("github", "maija_m")] = "Designer in Helsinki"
    r = _check(ctx, headers, ident)
    assert r.status_code == 400 and "Bio field" in r.json()["detail"]

    ctx.hibp.bios[("github", "maija_m")] = f"Designer in Helsinki {code}"
    r = _check(ctx, headers, ident)
    assert r.status_code == 200
    assert r.json()["status"] == "verified" and r.json()["proof_platform"] == "github"
    assert r.json()["proof_code"] is None
    assert str(ctx.hibp.requests[-1].url) == "https://api.github.com/users/maija_m"

    # Proven, so it's a search term now.
    ctx.llm.script.append(reply("end_turn", text("done")))
    ctx.client.post("/scan", headers=headers)
    assert "value=maija_m" in ctx.llm.calls[-1]["messages"][0]["content"]


def test_bluesky_bio_proof(ctx):
    headers = login(ctx.client)
    ident = _add_username(ctx, headers, "maija.bsky.social")
    code = _start(ctx, headers, ident, "bluesky").json()["proof_code"]
    ctx.hibp.bios[("bluesky", "maija.bsky.social")] = f"Hei! {code}"
    r = _check(ctx, headers, ident)
    assert r.status_code == 200 and r.json()["status"] == "verified"
    sent = ctx.hibp.requests[-1].url
    assert sent.host == "public.api.bsky.app" and sent.params.get("actor") == "maija.bsky.social"


def test_a_proven_username_alone_does_not_open_the_gate(ctx):
    headers = login(ctx.client)
    ident = _add_username(ctx, headers)
    code = _start(ctx, headers, ident).json()["proof_code"]
    ctx.hibp.bios[("github", "maija_m")] = code
    assert _check(ctx, headers, ident).status_code == 200
    r = ctx.client.post("/scan", headers=headers)
    assert r.status_code == 409 and "email address or phone number" in r.json()["detail"]


def test_unknown_profile(ctx):
    headers = login(ctx.client)
    ident = _add_username(ctx, headers, "nobody_here")
    _start(ctx, headers, ident)
    r = _check(ctx, headers, ident)
    assert r.status_code == 422 and "No GitHub account" in r.json()["detail"]


def test_proof_rules(ctx):
    headers = login(ctx.client)
    email = ctx.client.post("/identifiers", json={"kind": "email", "value": "me@example.com"}, headers=headers).json()
    assert _start(ctx, headers, email).status_code == 409  # only usernames
    ident = _add_username(ctx, headers)
    assert _start(ctx, headers, ident, "instagram").status_code == 422  # no public API to check
    assert _check(ctx, headers, ident).status_code == 409  # no code issued yet

    bob = login(ctx.client, "bob@example.com")
    assert _start(ctx, bob, ident).status_code == 404
    assert _check(ctx, bob, ident).status_code == 404


def test_expired_code(ctx):
    headers = login(ctx.client)
    ident = _add_username(ctx, headers)
    _start(ctx, headers, ident)
    db = sqlite3.connect(ctx.db_path)
    db.execute("UPDATE identifiers SET proof_expires_at = '2000-01-01 00:00:00.000000' WHERE id = ?", (ident["id"],))
    db.commit()
    assert _check(ctx, headers, ident).status_code == 410


def test_checks_are_rate_limited(ctx):
    headers = login(ctx.client)
    ident = _add_username(ctx, headers)
    _start(ctx, headers, ident)
    for _ in range(10):
        _check(ctx, headers, ident)
    assert _check(ctx, headers, ident).status_code == 429
