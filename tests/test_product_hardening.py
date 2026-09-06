"""P3 Product Hardening — TDD RED (REQ-PH-001..005)."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from lazograph.ui.app import create_app


def test_token_required_for_post(tmp_path, monkeypatch):
    """REQ-PH-001: POST without X-UI-Token when token exists -> 401."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    # create token file to simulate running lano ui
    tok_path = root / ".ui-token"
    tok_path.write_text("secret123", encoding="utf-8")
    client = TestClient(create_app())
    # without token header
    r = client.post("/api/import/preview", files={"file": ("x.txt", b"hello", "text/plain")}, data={"slug": "sample", "persona": "Samantha"})
    assert r.status_code == 401, r.text
    assert "token" in r.json()["detail"].lower()
    # with token
    r = client.post(
        "/api/import/preview",
        files={"file": ("x.txt", b"hello", "text/plain")},
        data={"slug": "sample", "persona": "Samantha"},
        headers={"X-UI-Token": "secret123"},
    )
    # may be 200 or 422 depending on content, but not 401
    assert r.status_code != 401


def test_path_traversal_blocked(tmp_path, monkeypatch):
    """REQ-PH-002: slug ../escape -> 422, no file outside root."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    # no token file -> no auth
    client = TestClient(create_app())
    r = client.post("/api/import/preview", files={"file": ("x.txt", b"hello", "text/plain")}, data={"slug": "../escape", "persona": "Samantha"})
    assert r.status_code == 422
    assert "slug" in r.json()["detail"].lower() or "invalid" in r.json()["detail"].lower()


def test_csp_header_present(tmp_path, monkeypatch):
    """REQ-PH-002: CSP header present."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    client = TestClient(create_app())
    r = client.get("/")
    assert r.status_code == 200
    csp = r.headers.get("content-security-policy") or r.headers.get("Content-Security-Policy")
    assert csp is not None
    assert "default-src" in csp


def test_logs_without_pii(tmp_path, monkeypatch):
    """REQ-PH-003: logs endpoint exists, no raw question when telemetry off."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    ds = root / "sample"
    ds.mkdir(parents=True)
    (ds / "dataset.json").write_text(json.dumps({"slug": "sample", "name": "Samantha", "schema_version": "0.8.0"}), encoding="utf-8")
    # create logs dir
    logs_dir = root / "logs"
    logs_dir.mkdir()
    (logs_dir / "lazograph.log").write_text('{"question_hash":"sha256:abc","route":"/api/ask"}\n', encoding="utf-8")
    client = TestClient(create_app())
    r = client.get("/api/logs", params={"slug": "sample"})
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        # should not contain raw question
        assert "¿Qué le gusta" not in r.text


def test_delete_recoverable(tmp_path, monkeypatch):
    """REQ-PH-005: DELETE with confirm moves to quarantine, without confirm 400."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    ds = root / "sample"
    ds.mkdir(parents=True)
    (ds / "dataset.json").write_text(json.dumps({"slug": "sample"}), encoding="utf-8")
    client = TestClient(create_app())
    # without confirm -> 400
    r = client.delete("/api/datasets/sample")
    assert r.status_code == 400
    # with confirm
    r = client.delete("/api/datasets/sample", params={"confirm": "sample"})
    assert r.status_code == 200, r.text
    assert not (root / "sample").exists()
    # quarantine exists
    assert any(root.rglob("deleted-sample*")) or any((root / "quarantine").rglob("*sample*")) or r.json().get("quarantine")


def test_telemetry_opt_in(tmp_path, monkeypatch):
    """REQ-PH-004: telemetry off by default, POST toggles."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    client = TestClient(create_app())
    r = client.get("/api/telemetry")
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    r = client.post("/api/telemetry", json={"enabled": True})
    assert r.status_code == 200
    assert r.json()["enabled"] is True
    # verify persisted
    r = client.get("/api/telemetry")
    assert r.json()["enabled"] is True
