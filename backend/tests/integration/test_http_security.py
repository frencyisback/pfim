"""Browser/HTTP mutation defenses, without file-backed database access."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from app.main import app
from app.maintenance import maintenance_gate
from app.schemas.backup import BackupInfo
from app.security import CAPABILITY_HEADER, capability_authority
from app.services.backup_service import BackupService

ALLOWED_ORIGIN = "http://localhost:5173"


def local_client(**kwargs) -> TestClient:
    return TestClient(app, base_url="http://localhost", **kwargs)


def fake_backup() -> BackupInfo:
    return BackupInfo(
        filename="pfim_backup_20260817_120000_000000_deadbeef.db",
        size_bytes=4096,
        created_at=dt.datetime.now(dt.UTC),
        verified=True,
        sha256="a" * 64,
        alembic_revision="test",
        manifest_filename="pfim_backup_20260817_120000_000000_deadbeef.manifest.json",
    )


def test_capability_bootstrap_is_no_store_and_high_entropy():
    response = local_client().get(
        "/api/v1/security/capability",
        headers={"Origin": ALLOWED_ORIGIN},
    )

    assert response.status_code == 200
    assert response.json()["header_name"] == CAPABILITY_HEADER
    assert len(response.json()["token"]) >= 43
    assert response.headers["cache-control"].startswith("no-store")


def test_capability_bootstrap_rejects_cross_origin_reader():
    response = local_client().get(
        "/api/v1/security/capability",
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "ORIGIN_FORBIDDEN"
    assert "access-control-allow-origin" not in response.headers


def test_simple_cross_origin_post_is_blocked_before_handler(monkeypatch):
    invoked = False

    def spy(self):
        nonlocal invoked
        invoked = True
        return fake_backup()

    monkeypatch.setattr(BackupService, "create_backup", spy)
    response = local_client().post(
        "/api/v1/backup",
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "ORIGIN_FORBIDDEN"
    assert invoked is False


def test_missing_or_invalid_capability_is_blocked_before_handler(monkeypatch):
    invoked = False

    def spy(self):
        nonlocal invoked
        invoked = True
        return fake_backup()

    monkeypatch.setattr(BackupService, "create_backup", spy)
    client = local_client()

    missing = client.post("/api/v1/backup", headers={"Origin": ALLOWED_ORIGIN})
    no_origin = client.post("/api/v1/backup")
    invalid = client.post(
        "/api/v1/backup",
        headers={"Origin": ALLOWED_ORIGIN, CAPABILITY_HEADER: "not-the-token"},
    )

    assert missing.status_code == 403
    assert missing.json()["error_code"] == "CAPABILITY_REQUIRED"
    assert no_origin.status_code == 403
    assert no_origin.json()["error_code"] == "CAPABILITY_REQUIRED"
    assert invalid.status_code == 403
    assert invalid.json()["error_code"] == "CAPABILITY_INVALID"
    for response in (missing, invalid):
        assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
        assert response.headers["cache-control"].startswith("no-store")
    assert invoked is False


def test_null_origin_is_rejected_even_with_valid_capability(monkeypatch):
    invoked = False

    def spy(self):
        nonlocal invoked
        invoked = True
        return fake_backup()

    monkeypatch.setattr(BackupService, "create_backup", spy)
    response = local_client().post(
        "/api/v1/backup",
        headers={"Origin": "null", CAPABILITY_HEADER: capability_authority.issue()},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "ORIGIN_FORBIDDEN"
    assert invoked is False


def test_valid_browser_and_cli_capabilities_reach_handler(monkeypatch):
    calls = 0

    def spy(self):
        nonlocal calls
        calls += 1
        return fake_backup()

    # This test checks only middleware. It must not even
    # resolve the configured database path (which may be ``:memory:``
    # in the suite or an operational file in production).
    monkeypatch.setattr(BackupService, "__init__", lambda self: None)
    monkeypatch.setattr(BackupService, "create_backup", spy)
    token = capability_authority.issue()
    client = local_client()

    browser = client.post(
        "/api/v1/backup",
        headers={"Origin": ALLOWED_ORIGIN, CAPABILITY_HEADER: token},
    )
    cli = client.post("/api/v1/backup", headers={CAPABILITY_HEADER: token})
    swagger = client.post(
        "/api/v1/backup",
        headers={"Origin": "http://localhost:8000", CAPABILITY_HEADER: token},
    )

    assert browser.status_code == 201
    assert cli.status_code == 201
    assert swagger.status_code == 201
    assert calls == 3


def test_untrusted_host_is_rejected_before_routing():
    response = local_client().get(
        "/api/v1/health",
        headers={"Host": "attacker.example"},
    )

    assert response.status_code == 400
    assert response.text == "Invalid host header"


def test_ipv6_host_is_intentionally_rejected_by_ipv4_only_profile():
    # An IPv6 base_url triggers a bug in the current TestClient transport;
    # the header is what TrustedHost actually validates.
    response = local_client().get("/api/v1/health", headers={"Host": "[::1]"})

    assert response.status_code == 400


def test_openapi_marks_every_mutation_with_capability_api_key():
    schema = local_client().get("/openapi.json").json()

    capability = schema["components"]["securitySchemes"]["PFIMCapability"]
    assert capability == {
        "type": "apiKey",
        "in": "header",
        "name": CAPABILITY_HEADER,
        "description": "Temporary token obtained from GET /api/v1/security/capability",
    }
    for path_item in schema["paths"].values():
        for method in ("post", "put", "patch", "delete"):
            if method in path_item:
                assert path_item[method]["security"] == [{"PFIMCapability": []}]


def test_cors_preflight_allows_only_configured_origin_and_capability_header():
    request_headers = {
        "Origin": ALLOWED_ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": CAPABILITY_HEADER,
    }
    allowed = local_client().options("/api/v1/backup", headers=request_headers)
    blocked = local_client().options(
        "/api/v1/backup",
        headers={**request_headers, "Origin": "https://attacker.example"},
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert CAPABILITY_HEADER.lower() in allowed.headers["access-control-allow-headers"].lower()
    assert blocked.status_code == 400
    assert "access-control-allow-origin" not in blocked.headers


def test_browser_can_refresh_capability_after_backend_token_rotation(monkeypatch):
    calls = []
    monkeypatch.setattr(BackupService, "__init__", lambda self: None)

    def spy(self):
        calls.append("handler")
        return fake_backup()

    monkeypatch.setattr(BackupService, "create_backup", spy)
    client = local_client()
    old_token = capability_authority.issue()
    monkeypatch.setattr(capability_authority, "_token", "rotated-token-for-isolated-test")
    rejected = client.post(
        "/api/v1/backup",
        headers={"Origin": ALLOWED_ORIGIN, CAPABILITY_HEADER: old_token},
    )
    assert rejected.status_code == 403
    assert rejected.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert rejected.json()["error_code"] == "CAPABILITY_INVALID"
    assert calls == []

    bootstrap = client.get("/api/v1/security/capability", headers={"Origin": ALLOWED_ORIGIN})
    assert bootstrap.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    accepted = client.post(
        "/api/v1/backup",
        headers={"Origin": ALLOWED_ORIGIN, CAPABILITY_HEADER: bootstrap.json()["token"]},
    )
    assert accepted.status_code == 201
    assert accepted.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert calls == ["handler"]


def test_maintenance_responses_are_readable_and_preflight_cannot_bypass_gate(monkeypatch):
    calls = []
    monkeypatch.setattr(BackupService, "__init__", lambda self: None)

    def spy(self):
        calls.append("handler")
        return fake_backup()

    monkeypatch.setattr(BackupService, "create_backup", spy)
    client = local_client()
    with maintenance_gate.exclusive(
        "test-cors-maintenance", current_request_tracked=False, timeout=0
    ):
        allowed = client.options(
            "/api/v1/backup",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": CAPABILITY_HEADER,
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
        for response in (
            client.get("/api/v1/transactions", headers={"Origin": ALLOWED_ORIGIN}),
            client.post(
                "/api/v1/backup",
                headers={"Origin": ALLOWED_ORIGIN, CAPABILITY_HEADER: capability_authority.issue()},
            ),
        ):
            assert response.status_code == 503
            assert response.json()["error_code"] == "MAINTENANCE_MODE"
            assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
            assert response.headers["retry-after"] == "1"
        blocked = client.options(
            "/api/v1/backup",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": CAPABILITY_HEADER,
            },
        )
        assert blocked.status_code == 400
        assert "access-control-allow-origin" not in blocked.headers
        assert calls == []


def test_wrong_host_is_still_rejected_for_actual_mutations(monkeypatch):
    calls = []
    monkeypatch.setattr(BackupService, "create_backup", lambda self: calls.append("handler"))
    response = local_client().post(
        "/api/v1/backup",
        headers={
            "Host": "attacker.example",
            "Origin": ALLOWED_ORIGIN,
            CAPABILITY_HEADER: capability_authority.issue(),
        },
    )
    assert response.status_code == 400
    assert calls == []
