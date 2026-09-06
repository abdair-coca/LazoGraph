"""P2 Product UX — TDD RED (REQ-PUX-002..006)."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from lazograph.ui.app import create_app


def _make_min_dataset(root: Path, slug="sample"):
    ds = root / slug
    ds.mkdir(parents=True, exist_ok=True)
    (ds / "dataset.json").write_text(json.dumps({"slug": slug, "name": "Samantha", "schema_version": "0.8.0", "timezone": "UTC"}), encoding="utf-8")
    (ds / "participants.json").write_text(json.dumps({"participants": [{"name": "Alex", "aliases": ["Alex"], "identity_type": "contact"}, {"name": "Samantha", "aliases": ["Samantha"], "identity_type": "persona"}]}), encoding="utf-8")
    (ds / "sources").mkdir(exist_ok=True)
    # create 25 messages spanning two days
    msgs = []
    for i in range(25):
        day = "2026-08-10" if i < 10 else "2026-08-11"
        hour = f"{i%24:02d}"
        msgs.append(json.dumps({"role": "user", "content": f"proyecto {i} con Alex", "timestamp": f"{day}T{hour}:00:00", "source_file": "chat.jsonl", "source_type": "whatsapp", "metadata": {"sender": "Alex"}}, ensure_ascii=False))
    (ds / "sources" / "chat.jsonl").write_text("\n".join(msgs) + "\n", encoding="utf-8")
    (ds / "wiki").mkdir(exist_ok=True)
    (ds / "wiki" / "identity.md").write_text("# Identity\nSamantha [chat.jsonl:1]\n", encoding="utf-8")
    (ds / "wiki" / "voice.md").write_text("# Voice\n", encoding="utf-8")
    return ds


def test_search_pagination(tmp_path, monkeypatch):
    """REQ-PUX-002: search with limit/offset, no overlap, has_more."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    _make_min_dataset(root)
    client = TestClient(create_app())
    r1 = client.get("/api/search", params={"slug": "sample", "query": "proyecto", "participant": "Alex", "limit": 10, "offset": 0})
    assert r1.status_code == 200, r1.text
    j1 = r1.json()
    assert "results" in j1 and "total" in j1 and "has_more" in j1
    assert len(j1["results"]) == 10
    r2 = client.get("/api/search", params={"slug": "sample", "query": "proyecto", "participant": "Alex", "limit": 10, "offset": 10})
    assert r2.status_code == 200
    j2 = r2.json()
    assert len(j2["results"]) == 10
    # no overlap
    ids1 = {e["message_id"] for e in j1["results"]}
    ids2 = {e["message_id"] for e in j2["results"]}
    assert not ids1.intersection(ids2)
    assert j1["has_more"] is True


def test_timeline_aggregation(tmp_path, monkeypatch):
    """REQ-PUX-003: timeline aggregates by day respecting timezone."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    _make_min_dataset(root)
    client = TestClient(create_app())
    r = client.get("/api/timeline", params={"slug": "sample", "granularity": "day"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "buckets" in body
    # should have 2 days
    assert len(body["buckets"]) == 2
    assert body["buckets"][0]["count"] == 10
    assert body["buckets"][1]["count"] == 15


def test_graph_json(tmp_path, monkeypatch):
    """REQ-PUX-004: graph returns effective nodes/edges, excludes plan_*."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    _make_min_dataset(root)
    # create minimal KG sqlite via helper? For P2 we mock minimal effective graph
    # create a simple knowledge_graph.sqlite3 with one edge Sam->Alex
    import sqlite3
    ds = root / "sample"
    kg_path = ds / ".mempalace" / "palace" / "knowledge_graph.sqlite3"
    kg_path.parent.mkdir(parents=True, exist_ok=True)
    # fallback: create empty KG via scripts path if needed; for TDD we expect endpoint to return at least empty nodes/edges
    client = TestClient(create_app())
    r = client.get("/api/graph", params={"slug": "sample", "format": "json"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "nodes" in body and "edges" in body
    # edges must not contain plan_*
    for e in body["edges"]:
        assert not e["type"].startswith("plan_")


def test_wiki_render(tmp_path, monkeypatch):
    """REQ-PUX-005: wiki page render and lint summary."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    _make_min_dataset(root)
    client = TestClient(create_app())
    r = client.get("/api/wiki", params={"slug": "sample"})
    assert r.status_code == 200, r.text
    assert "pages" in r.json()
    r = client.get("/api/wiki/identity.md", params={"slug": "sample"})
    # endpoint may be /api/wiki/{page} — if not found, expect 404 or html
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert "Identity" in r.text or "identity" in r.text.lower()


def test_progress_endpoint(tmp_path, monkeypatch):
    """REQ-PUX-006: progress polling exists."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    client = TestClient(create_app())
    r = client.get("/api/progress/any-id")
    # should return 200 with pct or 404 if no job, but not 500
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert "pct" in r.json() or "progress" in r.json()


def test_timeline_date_filter(tmp_path, monkeypatch):
    """REQ-PUX-003: timeline with from_date and to_date filtering."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    _make_min_dataset(root)
    client = TestClient(create_app())
    # Query only second day: 2026-08-11
    r = client.get("/api/timeline", params={"slug": "sample", "granularity": "day", "from_date": "2026-08-11", "to_date": "2026-08-11"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["buckets"]) == 1
    assert body["buckets"][0]["date"] == "2026-08-11"
    assert body["buckets"][0]["count"] == 15
    assert body["total"] == 15


def test_search_date_filter(tmp_path, monkeypatch):
    """REQ-PUX-002: search filtering with from_date and to_date."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    _make_min_dataset(root)
    client = TestClient(create_app())
    r = client.get("/api/search", params={"slug": "sample", "from_date": "2026-08-10", "to_date": "2026-08-10", "limit": 50})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["total"] == 10
    assert all(res["timestamp"].startswith("2026-08-10") for res in j["results"])


def test_wiki_evidence_links(tmp_path, monkeypatch):
    """REQ-PUX-005: wiki pages transform evidence tags into clickable links."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    _make_min_dataset(root)
    client = TestClient(create_app())
    r = client.get("/api/wiki/identity.md", params={"slug": "sample"})
    assert r.status_code == 200, r.text
    assert 'class="citation wiki-evidence-link"' in r.text
    assert 'data-tag="chat.jsonl:1"' in r.text


def test_graph_stats_endpoint(tmp_path, monkeypatch):
    """REQ-PUX-004: graph/stats endpoint returns entity and relationship counts."""
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    _make_min_dataset(root)
    client = TestClient(create_app())
    r = client.get("/api/graph/stats", params={"slug": "sample"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "entities" in body
    assert "relationships" in body
