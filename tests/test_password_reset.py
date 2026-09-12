"""Forgotten-password flow.

The data is encrypted behind the password, so losing it locks someone out
permanently. The reset has to work -- and must not become a second way in, or
a way to ask whether an address has an account here.
"""

from datetime import timedelta

from conftest import login

from exposure_auditor.models import utcnow

NEW = "a-brand-new-password"
OLD = "correct-horse-battery"


def _code(ctx, email="me@example.com") -> str:
    assert ctx.client.post("/auth/reset/request", json={"email": email}).status_code == 202
    return ctx.sender.codes[email]


def _signs_in(ctx, password, email="me@example.com") -> bool:
    return ctx.client.post("/auth/token", data={"username": email, "password": password}).status_code == 200


def test_a_code_sent_to_the_account_address_sets_a_new_password(ctx):
    login(ctx.client)

    code = _code(ctx)
    r = ctx.client.post("/auth/reset/confirm", json={"email": "me@example.com", "code": code, "password": NEW})

    assert r.status_code == 204
    assert _signs_in(ctx, NEW)
    assert not _signs_in(ctx, OLD)


def test_the_code_works_once(ctx):
    login(ctx.client)
    code = _code(ctx)
    ctx.client.post("/auth/reset/confirm", json={"email": "me@example.com", "code": code, "password": NEW})

    # Replaying it must not set a third password.
    again = ctx.client.post(
        "/auth/reset/confirm", json={"email": "me@example.com", "code": code, "password": "yet-another-password"}
    )

    assert again.status_code == 400
    assert _signs_in(ctx, NEW)


def test_an_unknown_address_is_answered_exactly_like_a_known_one(ctx):
    login(ctx.client)
    known = ctx.client.post("/auth/reset/request", json={"email": "me@example.com"})
    unknown = ctx.client.post("/auth/reset/request", json={"email": "nobody@example.com"})

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    # And nothing was sent for the address with no account.
    assert list(ctx.sender.codes) == ["me@example.com"]


def test_a_wrong_code_is_refused_the_same_way_as_a_missing_account(ctx):
    login(ctx.client)
    _code(ctx)

    wrong = ctx.client.post("/auth/reset/confirm", json={"email": "me@example.com", "code": "000000", "password": NEW})
    stranger = ctx.client.post(
        "/auth/reset/confirm", json={"email": "nobody@example.com", "code": "000000", "password": NEW}
    )

    assert wrong.status_code == stranger.status_code == 400
    assert wrong.json()["detail"] == stranger.json()["detail"]
    assert _signs_in(ctx, OLD)


def test_guessing_stops_after_five_attempts(ctx):
    login(ctx.client)
    code = _code(ctx)

    for _ in range(5):
        ctx.client.post("/auth/reset/confirm", json={"email": "me@example.com", "code": "000000", "password": NEW})
    # Even the right code is refused now: a new one has to be requested.
    r = ctx.client.post("/auth/reset/confirm", json={"email": "me@example.com", "code": code, "password": NEW})

    assert r.status_code == 400
    assert _signs_in(ctx, OLD)


def test_an_expired_code_is_refused(ctx, monkeypatch):
    login(ctx.client)
    code = _code(ctx)
    # Eleven minutes later, from the server's point of view.
    monkeypatch.setattr("exposure_auditor.api.auth.utcnow", lambda: utcnow() + timedelta(minutes=11))

    r = ctx.client.post("/auth/reset/confirm", json={"email": "me@example.com", "code": code, "password": NEW})

    assert r.status_code == 400
    assert _signs_in(ctx, OLD)


def test_a_short_password_is_rejected_before_the_code_is_spent(ctx):
    login(ctx.client)
    code = _code(ctx)

    r = ctx.client.post("/auth/reset/confirm", json={"email": "me@example.com", "code": code, "password": "short"})

    assert r.status_code == 422
    # The code survived a malformed request, so the user can try again.
    assert ctx.client.post(
        "/auth/reset/confirm", json={"email": "me@example.com", "code": code, "password": NEW}
    ).status_code == 204
