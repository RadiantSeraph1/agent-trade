from fastapi.testclient import TestClient

from fxlab.api.app import create_app
from fxlab.config import Settings

H = "x-goog-iap-jwt-assertion"


def fake_verify(token, audience):
    claims = {
        "good": {"email": "me@example.com"},
        "other": {"email": "x@example.com"},
    }
    if token not in claims or audience != "aud1":
        raise ValueError("bad")
    return claims[token]


def client(**kw):
    kw.setdefault("allowed_emails", ["me@example.com"])
    kw.setdefault("iap_audience", "aud1")
    return TestClient(create_app(Settings(_env_file=None, **kw), verify=fake_verify))


def test_health_and_pwa_assets_public():
    c = client()
    assert c.get("/api/health").json() == {"ok": True}
    assert "FX Lab" in c.get("/").text
    assert c.get("/manifest.webmanifest").status_code == 200
    assert c.get("/sw.js").headers["cache-control"] == "no-cache"
    assert c.get("/icons/icon-512.png").status_code == 200
    assert c.get("/").headers["x-frame-options"] == "DENY"


def test_status_requires_valid_allowlisted_iap_user():
    c = client()
    assert c.get("/api/status").status_code == 401
    assert c.get("/api/status", headers={H: "nope"}).status_code == 401
    assert c.get("/api/status", headers={H: "other"}).status_code == 403
    r = c.get("/api/status", headers={H: "good"})
    assert r.status_code == 200 and r.json()["mode"] == "paper / demo only"


def test_plain_email_header_is_not_trusted():
    c = client()
    r = c.get("/api/status", headers={"x-goog-authenticated-user-email": "accounts.google.com:me@example.com"})
    assert r.status_code == 401


def test_fails_closed_without_allowlist_or_audience():
    assert client(allowed_emails=[]).get("/api/status", headers={H: "good"}).status_code == 403
    assert client(iap_audience="").get("/api/status", headers={H: "good"}).status_code == 503


def test_openapi_docs_disabled():
    assert client().get("/docs").status_code == 404
