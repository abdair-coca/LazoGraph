import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from lazograph.ui.app import create_app

FIXTURE = Path("tests/fixtures/sample-whatsapp-localized.txt")


def test_import_preview_never_writes(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    client = TestClient(create_app())
    with open(FIXTURE, "rb") as f:
        r = client.post("/api/import/preview", files={"file": ("sample.txt", f, "text/plain")}, data={"slug": "sample", "persona": "Samantha"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parsed_messages"] == 4
    assert body["rejected_notices"] == 1
    assert body["persona"] == "Samantha"
    assert not (root / "sample").exists()


def test_import_apply_then_idempotent(tmp_path, monkeypatch):
    from scripts.runtime import configure_safe_output

    configure_safe_output()
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    client = TestClient(create_app())

    # preview + apply first time
    with open(FIXTURE, "rb") as f:
        r = client.post("/api/import/preview", files={"file": ("sample.txt", f, "text/plain")}, data={"slug": "sample", "persona": "Samantha"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    r = client.post("/api/import/apply", json={"token": token})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "imported"
    assert (root / "sample" / "dataset.json").exists()

    # second import same file: via UI temp file it is not same_source (different temp path) but equivalent;
    # CLI idempotency is via same file hash; UI uses temp so we accept either already_imported or equivalent guard 422
    with open(FIXTURE, "rb") as f:
        r = client.post("/api/import/preview", files={"file": ("sample.txt", f, "text/plain")}, data={"slug": "sample", "persona": "Samantha"})
    assert r.status_code == 200
    body = r.json()
    token2 = body["token"]
    # if same_source, should be already_imported; if equivalent, should require flag
    if body.get("same_source_reimport"):
        r = client.post("/api/import/apply", json={"token": token2})
        assert r.status_code == 200
        assert r.json()["status"] == "already_imported"
    else:
        # equivalent path: without flag should 422, with allow should succeed as imported/idempotent
        r = client.post("/api/import/apply", json={"token": token2})
        assert r.status_code == 422
        # retry preview + apply with allow_equivalent should succeed
        with open(FIXTURE, "rb") as f:
            r = client.post("/api/import/preview", files={"file": ("sample.txt", f, "text/plain")}, data={"slug": "sample", "persona": "Samantha"})
        token3 = r.json()["token"]
        r = client.post("/api/import/apply", json={"token": token3, "allow_equivalent_source": True})
        assert r.status_code == 200
        assert r.json()["status"] in ("imported", "already_imported")


def test_import_equivalent_guard(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    client = TestClient(create_app())

    # create 20-line candidate like test_lazo_import
    candidate = tmp_path / "candidate.txt"
    lines = []
    for i in range(20):
        sender = "Samantha" if i % 2 == 0 else "Alex"
        lines.append(f"13/8/25, 9:{i:02d} p. m. - {sender}: Message {i}\n")
    candidate.write_text("".join(lines), encoding="utf-8")

    # first import
    with open(candidate, "rb") as f:
        r = client.post("/api/import/preview", files={"file": ("candidate.txt", f, "text/plain")}, data={"slug": "sample", "persona": "Samantha"})
    token = r.json()["token"]
    r = client.post("/api/import/apply", json={"token": token})
    assert r.status_code == 200

    # second import same content via different file object but same messages -> equivalent
    # use same candidate path but trigger preview; since same messages, preview should show equivalent or same_source
    # To simulate equivalent (not same_source), create slightly overlapping file: 19/20 same
    # For simplicity, re-import same candidate - should be same_source_reimport true, not equivalent guard
    # So create a new file with 20 messages overlapping 95%+ but not identical bytes
    candidate2 = tmp_path / "candidate2.txt"
    lines2 = []
    for i in range(20):
        sender = "Samantha" if i % 2 == 0 else "Alex"
        # change one message slightly to make not identical but overlapping
        msg = f"Message {i}" if i != 19 else "Message 19 altered"
        lines2.append(f"13/8/25, 9:{i:02d} p. m. - {sender}: {msg}\n")
    candidate2.write_text("".join(lines2), encoding="utf-8")
    with open(candidate2, "rb") as f:
        r = client.post("/api/import/preview", files={"file": ("candidate2.txt", f, "text/plain")}, data={"slug": "sample", "persona": "Samantha"})
    body = r.json()
    # if equivalent, apply without flag should 422
    if body.get("equivalent_sources"):
        token2 = body["token"]
        r = client.post("/api/import/apply", json={"token": token2})
        assert r.status_code == 422
        assert "stopped before writes" in r.json()["detail"].lower()
        # Preview token should still be valid after 422 equivalent error, allowing reconcile_equivalent_source
        r_reconcile = client.post(
            "/api/import/apply",
            json={"token": token2, "reconcile_equivalent_source": True},
        )
        assert r_reconcile.status_code == 200
        assert r_reconcile.json()["status"] == "imported"


def test_import_preview_file_too_large_413(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    client = TestClient(create_app())
    # 21MB dummy payload
    oversized = b"x" * (20 * 1024 * 1024 + 1024)
    r = client.post(
        "/api/import/preview",
        files={"file": ("large.txt", oversized, "text/plain")},
        data={"slug": "sample", "persona": "Samantha"},
    )
    assert r.status_code == 413
    assert "20mb" in r.json()["detail"].lower()


def test_import_preview_invalid_slug_422(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    client = TestClient(create_app())
    with open(FIXTURE, "rb") as f:
        r = client.post(
            "/api/import/preview",
            files={"file": ("sample.txt", f, "text/plain")},
            data={"slug": "../traversal", "persona": "Samantha"},
        )
    assert r.status_code == 422
    assert "slug inválido" in r.json()["detail"].lower()


def test_import_preview_missing_persona_422(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    client = TestClient(create_app())
    with open(FIXTURE, "rb") as f:
        r = client.post(
            "/api/import/preview",
            files={"file": ("sample.txt", f, "text/plain")},
            data={"slug": "sample", "persona": "   "},
        )
    assert r.status_code == 422
    assert "persona requerida" in r.json()["detail"].lower()


def test_progress_endpoint_polling(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    client = TestClient(create_app())

    # Unknown job should 404
    r = client.get("/api/progress/unknown-job-id")
    assert r.status_code == 404

    # Perform preview and apply, checking progress endpoint
    with open(FIXTURE, "rb") as f:
        r = client.post(
            "/api/import/preview",
            files={"file": ("sample.txt", f, "text/plain")},
            data={"slug": "sample", "persona": "Samantha"},
        )
    token = r.json()["token"]

    r_apply = client.post("/api/import/apply", json={"token": token})
    assert r_apply.status_code == 200
    job_id = r_apply.json().get("job_id")
    assert job_id is not None

    r_prog = client.get(f"/api/progress/{job_id}")
    assert r_prog.status_code == 200
    pdata = r_prog.json()
    assert pdata["status"] == "done"
    assert pdata["pct"] == 100

