"""An instance opened to invited people, with real search and no mail.

Two properties matter. Each person gets an account of their own, because a
shared login would show everyone the others' real details. And the shortcuts
that make this work without a mailbox -- codes on the page -- stay off in
production, where they would let anyone verify an address they don't own.
"""

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr, ValidationError

from exposure_auditor.config import Settings

PASSWORD = "correct-horse-battery"


def _invited(ctx, settings, **extra):
    ctx.client.app.state.services.settings = settings.model_copy(
        update={"registration_code": SecretStr("the-invite"), **extra}
    )


def _register(ctx, email, invite=None):
    body = {"email": email, "password": PASSWORD}
    if invite is not None:
        body["invite_code"] = invite
    return ctx.client.post("/auth/register", json=body)


def test_registration_needs_the_invite_when_one_is_set(ctx, settings):
    _invited(ctx, settings)

    missing = _register(ctx, "a@example.com")
    wrong = _register(ctx, "b@example.com", invite="a-guess")
    right = _register(ctx, "c@example.com", invite="the-invite")

    assert missing.status_code == wrong.status_code == 403
    # No difference between a missing code and a wrong one to learn from.
    assert missing.json() == wrong.json()
    assert right.status_code == 202


def test_every_invited_person_gets_an_account_of_their_own(ctx, settings):
    """The reason for invites instead of a shared login: real details must not
    be visible to the next person who signs in."""
    _invited(ctx, settings)
    for email in ("first@example.com", "second@example.com"):
        assert _register(ctx, email, invite="the-invite").status_code == 202

    def headers(email):
        token = ctx.client.post("/auth/token", data={"username": email, "password": PASSWORD}).json()
        return {"Authorization": f"Bearer {token['access_token']}"}

    first, second = headers("first@example.com"), headers("second@example.com")
    ctx.client.post("/identifiers", json={"kind": "email", "value": "first@example.com"}, headers=first)

    assert ctx.client.get("/identifiers", headers=second).json() == []


def test_codes_can_be_shown_on_the_page_without_demo_mode(ctx, settings):
    _invited(ctx, settings, codes_on_page=True)
    _register(ctx, "me@example.com", invite="the-invite")
    token = ctx.client.post("/auth/token", data={"username": "me@example.com", "password": PASSWORD}).json()
    headers = {"Authorization": f"Bearer {token['access_token']}"}

    added = ctx.client.post("/identifiers", json={"kind": "email", "value": "me@example.com"}, headers=headers).json()

    assert added["demo_code"] == ctx.sender.codes["me@example.com"]


def test_meta_tells_the_page_what_this_instance_does(ctx, settings):
    _invited(ctx, settings, codes_on_page=True)

    meta = ctx.client.get("/meta").json()

    assert meta["invite_required"] is True
    assert meta["codes_on_page"] is True


def test_production_refuses_codes_on_the_page():
    with pytest.raises(ValidationError, match="EA_CODES_ON_PAGE"):
        Settings(
            _env_file=None,
            env="prod",
            database_url="postgresql+asyncpg://user:pass@db.example.com/app",
            verification_delivery="aws",
            ses_sender="no-reply@example.com",
            jwt_secret="a-production-jwt-secret-long-enough",
            field_encryption_key=Fernet.generate_key().decode(),
            blind_index_key="a-production-blind-index-key-0123",
            codes_on_page=True,
        )
