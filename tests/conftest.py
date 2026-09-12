import json
from types import SimpleNamespace
from urllib.parse import unquote

import httpx2
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from exposure_auditor.config import Settings
from exposure_auditor.main import create_app
from exposure_auditor.tools.search import SearchResult


def tool_use(id, name, input):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def text(t):
    return SimpleNamespace(type="text", text=t)


def reply(stop_reason, *blocks):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks))


class ScriptedLLM:
    """Stands in for AsyncAnthropicBedrockMantle: returns canned responses in order."""

    def __init__(self, script=None):
        self.script = list(script or [])
        self.calls = []
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.script.pop(0)


class FakeSearch:
    def __init__(self):
        self.results: list[SearchResult] = []
        self.queries: list[str] = []

    async def search(self, query, count=10):
        self.queries.append(query)
        return self.results


class CapturingSender:
    def __init__(self):
        self.codes: dict[str, str] = {}

    async def send(self, kind, destination, code):
        self.codes[destination] = code


class FakeHibp:
    """MockTransport handler for the outside services (HIBP, and the GitHub and
    Bluesky profile APIs used for username proofs); records what was sent."""

    def __init__(self):
        self.breaches: dict[str, list[dict]] = {}
        self.bios: dict[tuple[str, str], str] = {}  # (platform, handle) -> bio
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.host == "api.github.com":
            handle = unquote(request.url.path.rsplit("/", 1)[-1])
            bio = self.bios.get(("github", handle.lower()))
            if bio is None:
                return httpx2.Response(404, json={"message": "Not Found"})
            return httpx2.Response(200, json={"login": handle, "bio": bio})
        if request.url.host == "public.api.bsky.app":
            handle = request.url.params.get("actor", "")
            bio = self.bios.get(("bluesky", handle.lower()))
            if bio is None:
                return httpx2.Response(400, json={"error": "InvalidRequest", "message": "Profile not found"})
            return httpx2.Response(200, json={"handle": handle, "description": bio})
        if request.url.host == "haveibeenpwned.com":
            email = unquote(request.url.path.rsplit("/", 1)[-1])
            found = self.breaches.get(email)
            return httpx2.Response(200, json=found) if found else httpx2.Response(404)
        if request.url.host == "api.pwnedpasswords.com":
            return httpx2.Response(
                200,
                text="0018A45C4D1DEF81644B54AB7F969B88D65:3\r\n00D4F6E8FA6EECAD2A3AA415EEC418D38EC:0\r\n",
            )
        return httpx2.Response(500)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        env="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
        jwt_secret="test-jwt-secret-that-is-long-enough-32b",
        field_encryption_key=Fernet.generate_key().decode(),
        blind_index_key="test-blind-index-key-0123456789abcdef",
        hibp_api_key="test-hibp-key",
    )


@pytest.fixture
def ctx(settings, tmp_path):
    llm, search, sender, hibp = ScriptedLLM(), FakeSearch(), CapturingSender(), FakeHibp()
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(hibp))
    app = create_app(settings, llm=llm, search=search, sender=sender, http=http)
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client, llm=llm, search=search, sender=sender, hibp=hibp,
            db_path=tmp_path / "test.db",
        )


def login(client, email="me@example.com", password="correct-horse-battery"):
    client.post("/auth/register", json={"email": email, "password": password})
    r = client.post("/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def add_verified_email(ctx, headers, email="me@example.com"):
    r = ctx.client.post("/identifiers", json={"kind": "email", "value": email}, headers=headers)
    assert r.status_code == 201, r.text
    ident = r.json()
    r = ctx.client.post(
        f"/identifiers/{ident['id']}/verify", json={"code": ctx.sender.codes[email]}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()


def add_name(ctx, headers, name="Maija Meikäläinen"):
    r = ctx.client.post(
        "/identifiers", json={"kind": "name", "value": name, "attest": True}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


def dump(obj) -> str:
    return json.dumps(obj, default=str)
