"""P1 Product Distribution — TDD RED phase (REQ-PD-001..005)."""

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from lazograph.ui.app import create_app

FIXTURE = Path("tests/fixtures/sample-whatsapp-localized.txt")


def test_wizard_shows_when_no_datasets(tmp_path, monkeypatch):
    """REQ-PD-002: GET / when no dataset exists renders wizard."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    client = TestClient(create_app())
    r = client.get("/")
    assert r.status_code == 200
    # wizard must contain guidance for empty state (no datasets)
    assert "wizard" in r.text.lower() or "import" in r.text.lower() or "No hay datasets" in r.text or "elige" in r.text.lower()


def test_wizard_preview_no_write(tmp_path, monkeypatch):
    """REQ-PD-002: wizard preview does not write until confirm."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    client = TestClient(create_app())
    with open(FIXTURE, "rb") as f:
        r = client.post(
            "/api/import/preview",
            files={"file": ("sample.txt", f, "text/plain")},
            data={"slug": "sample", "persona": "Samantha"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["parsed_messages"] == 4
    assert not (root / "sample").exists()


def test_migration_bumps_schema(tmp_path, monkeypatch):
    """REQ-PD-003: old schema_version 0.7 migrates to 0.8.0 without data loss."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    # create minimal dataset without embedding (avoid ONNX memory)
    ds_dir = root / "sample"
    ds_dir.mkdir(parents=True)
    (ds_dir / "dataset.json").write_text(
        json.dumps({"slug": "sample", "name": "Samantha", "schema_version": "0.7", "stats": {"messages": 4}}, ensure_ascii=False), encoding="utf-8"
    )
    (ds_dir / "participants.json").write_text(json.dumps({"participants": []}, ensure_ascii=False), encoding="utf-8")
    (ds_dir / "sources").mkdir()
    (ds_dir / "sources" / "chat.jsonl").write_text('{"role":"assistant","content":"hi"}\n', encoding="utf-8")

    client = TestClient(create_app())
    r = client.post("/api/migrate", json={"slug": "sample"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["migrated"] is True
    assert body["from"] == "0.7"
    assert body["to"] == "0.8.0"
    assert any((root / "sample").rglob("*.bak")) or (root / "sample" / ".migrations").exists() or body.get("backup")
    new_data = json.loads((ds_dir / "dataset.json").read_text(encoding="utf-8"))
    assert new_data["schema_version"] == "0.8.0"


def test_migration_fails_on_downgrade(tmp_path, monkeypatch):
    """REQ-PD-003: downgrade must fail closed with human ES error."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    ds_dir = root / "sample"
    ds_dir.mkdir(parents=True)
    (ds_dir / "dataset.json").write_text(
        json.dumps({"slug": "sample", "name": "Samantha", "schema_version": "99.0.0"}, ensure_ascii=False), encoding="utf-8"
    )
    (ds_dir / "participants.json").write_text(json.dumps({"participants": []}, ensure_ascii=False), encoding="utf-8")

    client = TestClient(create_app())
    r = client.post("/api/migrate", json={"slug": "sample", "target": "0.8.0"})
    assert r.status_code == 422
    assert "downgrade" in r.json()["detail"].lower() or "versión" in r.json()["detail"].lower()


def test_backup_round_trip(tmp_path, monkeypatch):
    """REQ-PD-004: backup then restore round-trip preserves dataset."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    ds_dir = root / "sample"
    ds_dir.mkdir(parents=True)
    (ds_dir / "dataset.json").write_text(json.dumps({"slug": "sample", "name": "Samantha", "schema_version": "0.8.0"}, ensure_ascii=False), encoding="utf-8")
    (ds_dir / "participants.json").write_text(json.dumps({"participants": []}, ensure_ascii=False), encoding="utf-8")
    (ds_dir / "sources").mkdir()
    (ds_dir / "sources" / "chat.jsonl").write_text('{"role":"assistant","content":"hi"}\n', encoding="utf-8")
    (ds_dir / "wiki").mkdir()
    (ds_dir / "wiki" / "identity.md").write_text("# hi", encoding="utf-8")

    client = TestClient(create_app())
    r = client.post("/api/backup", json={"slug": "sample"})
    assert r.status_code == 200, r.text
    # endpoint may return zip file or JSON path
    if r.headers.get("content-type", "").startswith("application/zip"):
        zip_path = tmp_path / "backup.zip"
        zip_path.write_bytes(r.content)
    else:
        body = r.json()
        zip_path = Path(body.get("path") or body.get("zip") or body.get("backup") or "")
        # if body returns path inside root, use it
        if not zip_path.exists():
            # fallback: find created zip
            zips = list(root.rglob("*.zip"))
            assert zips, body
            zip_path = zips[0]
        assert zip_path.exists()

    import shutil

    shutil.rmtree(ds_dir)
    assert not ds_dir.exists()

    with open(zip_path, "rb") as f:
        r = client.post("/api/restore", files={"file": ("backup.zip", f, "application/zip")}, data={"slug": "sample"})
    assert r.status_code == 200, r.text
    assert (root / "sample" / "dataset.json").exists()
    assert (root / "sample" / "sources" / "chat.jsonl").exists()


def test_update_check_offline(tmp_path, monkeypatch):
    """REQ-PD-005: update-check offline returns 200 with warning."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    client = TestClient(create_app())
    r = client.get("/api/update-check")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "current" in body and "update_available" in body
    # offline case should not crash, warning may be present
    assert body["update_available"] is False or isinstance(body["update_available"], bool)
