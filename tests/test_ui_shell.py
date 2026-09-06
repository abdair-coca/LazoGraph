import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from lazograph.ui.app import create_app


def test_health():
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_index_serves_html():
    client = TestClient(create_app())
    r = client.get("/")
    assert r.status_code == 200
    assert "LazoGraph" in r.text


def test_datasets_empty_and_list(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    client = TestClient(create_app())
    r = client.get("/api/datasets")
    assert r.status_code == 200
    assert r.json()["datasets"] == []

    ds = root / "sample"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"slug": "sample", "name": "Samantha"}), encoding="utf-8")
    r = client.get("/api/datasets")
    assert len(r.json()["datasets"]) == 1
    assert r.json()["datasets"][0]["slug"] == "sample"


def test_diagnose_on_fixture(tmp_path, monkeypatch):
    from scripts import ingest
    from scripts.runtime import configure_safe_output

    configure_safe_output()
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    fixture = Path("tests/fixtures/sample-whatsapp-localized.txt")
    # create dataset via ingest directly
    dataset = root / "sample"
    # use build_preview style via direct ingest
    from lazograph.features.import_chat.service import build_preview

    preview = build_preview(str(fixture), slug="sample", persona="Samantha", root=root)
    # init dataset
    from scripts import init_knowledge

    init_knowledge.init_dataset("sample", "Samantha", knowledge_root=root)
    ingest.main(["--slug", "sample", "--source", str(fixture), "--adapter", preview.adapter, "--persona-name", "Samantha", "--persona-exact"], knowledge_root=root)

    client = TestClient(create_app())
    r = client.get("/api/diagnose", params={"slug": "sample"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == "sample"
    assert body["sources"]["messages"] == 4
    assert body["participants"]["profiles"] >= 2
