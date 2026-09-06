import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from lazograph.ui.app import create_app


def _make_dataset_with_plans(root: Path):
    from scripts.runtime import configure_safe_output
    from lazograph.features.import_chat.service import build_preview
    from scripts import init_knowledge, ingest

    configure_safe_output()
    fixture = Path("tests/fixtures/sample-whatsapp-localized.txt")
    preview = build_preview(str(fixture), slug="sample", persona="Samantha", root=root)
    init_knowledge.init_dataset("sample", "Samantha", knowledge_root=root)
    ingest.main(["--slug", "sample", "--source", str(fixture), "--adapter", preview.adapter, "--persona-name", "Samantha", "--persona-exact"], knowledge_root=root)


def test_plans_empty_initially(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    _make_dataset_with_plans(root)
    client = TestClient(create_app())
    r = client.get("/api/plans", params={"slug": "sample"})
    assert r.status_code == 200, r.text
    assert "plans" in r.json()


def test_graph_stats_and_wiki_and_corrections(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    _make_dataset_with_plans(root)
    client = TestClient(create_app())
    for endpoint in ["/api/graph/stats", "/api/wiki", "/api/corrections"]:
        r = client.get(endpoint, params={"slug": "sample"})
        assert r.status_code == 200, f"{endpoint} failed: {r.text}"
    # unknown dataset -> 404
    r = client.get("/api/plans", params={"slug": "missing"})
    assert r.status_code in (404, 422)
