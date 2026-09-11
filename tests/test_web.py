import httpx2
import pytest
from conftest import CapturingSender, FakeHibp, add_name, add_verified_email, login
from fastapi.testclient import TestClient

from exposure_auditor.config import Settings
from exposure_auditor.main import SPA_CSP, create_app


def test_meta_describes_capabilities(ctx):
    meta = ctx.client.get("/meta").json()
    assert meta["scans_available"] is True
    assert meta["demo_scans"] is False
    assert meta["breach_check_available"] is True
    assert meta["code_delivery"] == "console"


def test_security_headers_on_api_responses(ctx):
    r = ctx.client.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "DENY"


def test_spa_served_with_strict_csp(settings, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<div id="root"></div><script type="module" src="/assets/app.js"></script>')
    (dist / "assets" / "app.js").write_text("console.log('hi')")
    app = create_app(settings.model_copy(update={"web_dist": str(dist)}), llm=None, search=None)
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200 and 'id="root"' in r.text
        assert r.headers["content-security-policy"] == SPA_CSP
        assert "script-src 'self'" in SPA_CSP and "unsafe-inline" not in SPA_CSP
        assert client.get("/assets/app.js").status_code == 200


def test_demo_mode_runs_the_real_pipeline(settings):
    sender = CapturingSender()
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(FakeHibp()))
    app = create_app(settings.model_copy(update={"demo_scans": True}), sender=sender, http=http)
    with TestClient(app) as client:
        ctx = type("Ctx", (), {"client": client, "sender": sender})
        headers = login(client)
        assert client.get("/meta").json()["demo_scans"] is True
        add_verified_email(ctx, headers)
        add_name(ctx, headers)
        client.post("/identifiers", json={"kind": "city", "value": "Helsinki", "attest": True}, headers=headers)

        scan_id = client.post("/scan", headers=headers).json()["scan_id"]
        scan = client.get(f"/scan/{scan_id}", headers=headers).json()
        assert scan["status"] == "completed"
        assert scan["summary"].startswith("Demo mode")
        assert scan["namesakes_excluded"] == 1  # the Oulu listing
        assert {f["category"] for f in scan["findings"]} == {"people_search", "paste_or_leak"}
        assert all(f["title"].startswith("[DEMO]") for f in scan["findings"])
        spokeo = [f for f in scan["findings"] if f["broker_id"] == "spokeo"]
        assert [f["match_status"] for f in spokeo] == ["likely"]

        imp_id = client.post("/impersonation-check", headers=headers).json()["scan_id"]
        imp = client.get(f"/scan/{imp_id}", headers=headers).json()
        assert {f["category"] for f in imp["findings"]} == {"social_profile", "possible_impersonation"}

        plan = lambda: [i["title"] for i in client.get("/remediation-plan", headers=headers).json()["items"]]  # noqa: E731
        assert "Opt out of Spokeo" in plan()
        # Name-only profiles could be a stranger's real account: nothing to
        # report until the account holder confirms.
        assert not any(t.startswith("Check a possible impersonation profile") for t in plan())
        copy = next(f for f in imp["findings"] if f["category"] == "possible_impersonation")
        client.post(f"/findings/{copy['id']}/confirm", headers=headers)
        assert any(t.startswith("Check a possible impersonation profile") for t in plan())


def test_donate_url_shown_only_when_configured(ctx, settings):
    assert ctx.client.get("/meta").json()["donate_url"] is None
    url = "https://www.paypal.com/donate/?hosted_button_id=ABC123"
    app = create_app(settings.model_copy(update={"donate_url": url}), llm=None, search=None)
    with TestClient(app) as client:
        assert client.get("/meta").json()["donate_url"] == url


@pytest.mark.parametrize(("url", "ok"), [
    ("https://www.paypal.com/donate/?hosted_button_id=ABC123", True),
    ("https://paypal.me/someone", True),
    ("", True),  # empty means no button
    ("http://www.paypal.com/donate/?hosted_button_id=ABC123", False),
    ("https://paypal.com.evil.example/donate", False),
    ("https://example.com/pay", False),
])
def test_donate_url_must_be_paypal(url, ok):
    make = lambda: Settings(  # noqa: E731
        _env_file=None, jwt_secret="s", field_encryption_key="k", blind_index_key="b", donate_url=url,
    )
    if ok:
        make()
    else:
        with pytest.raises(ValueError, match="EA_DONATE_URL"):
            make()


def test_prod_refuses_demo_scans():
    with pytest.raises(ValueError, match="DEMO"):
        Settings(
            _env_file=None, env="prod", database_url="postgresql+asyncpg://db/x",
            verification_delivery="aws", ses_sender="noreply@example.com", demo_scans=True,
            jwt_secret="s", field_encryption_key="k", blind_index_key="b",
        )
