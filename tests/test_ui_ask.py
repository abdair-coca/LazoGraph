import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from lazograph.ui.app import create_app


def _setup_dataset(root: Path):
    from scripts import init_knowledge, ingest
    from scripts.runtime import configure_safe_output
    from lazograph.features.import_chat.service import build_preview

    configure_safe_output()
    fixture = Path("tests/fixtures/sample-whatsapp-localized.txt")
    preview = build_preview(str(fixture), slug="sample", persona="Samantha", root=root)
    init_knowledge.init_dataset("sample", "Samantha", knowledge_root=root)
    ingest.main(["--slug", "sample", "--source", str(fixture), "--adapter", preview.adapter, "--persona-name", "Samantha", "--persona-exact"], knowledge_root=root)


def test_ask_via_ui_parity(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    _setup_dataset(root)

    client = TestClient(create_app())
    # ask about Samantha with content that exists in fixture (Primera línea)
    r = client.post("/api/ask", json={"question": "¿Qué dijo Samantha?", "about": "Samantha", "slug": "sample"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "text" in body and "citations" in body
    # fixture has 2 Samantha messages; asking generically should return something or abstain deterministically
    # accept either grounded answer with Samantha citations OR abstention with zero citations (both valid per pipeline)
    if body.get("abstained"):
        assert body["citations"] == []
    else:
        assert len(body["citations"]) >= 1
        assert all(c["sender"] == "Samantha" for c in body["citations"])


def test_ask_alias_isolation(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    # minimal dataset like test_ask_person: manually create sources
    dataset = root / "sample"
    sources = dataset / "sources"
    sources.mkdir(parents=True)
    (dataset / "wiki").mkdir()
    (dataset / "wiki" / "values.md").write_text("# Values\n", encoding="utf-8")
    messages = [
        {"role": "assistant", "content": "Me gusta pintar paisajes los domingos.", "timestamp": "2026-01-01T10:01:00", "source_file": "chat.txt", "source_type": "whatsapp", "metadata": {"sender": "Samantha"}},
        {"role": "assistant", "content": "Trabajo en un proyecto de grafos.", "timestamp": "2026-01-01T10:02:00", "source_file": "chat.txt", "source_type": "whatsapp", "metadata": {"sender": "Samantha"}},
        {"role": "user", "content": "Me gusta bailar salsa.", "timestamp": "2026-01-01T10:03:00", "source_file": "chat.txt", "source_type": "whatsapp", "metadata": {"sender": "Alex"}},
    ]
    sources.joinpath("chat.jsonl").write_text("".join(json.dumps(m, ensure_ascii=False)+"\n" for m in messages), encoding="utf-8")
    (dataset / "dataset.json").write_text(json.dumps({"slug": "sample", "name": "Samantha"}), encoding="utf-8")
    (dataset / "participants.json").write_text(json.dumps({"participants": [
        {"name": "Samantha", "aliases": ["Samantha", "Sam"], "identity_type": "persona", "message_count": 2},
        {"name": "Alex", "aliases": ["Alex"], "identity_type": "contact", "message_count": 1},
    ]}), encoding="utf-8")

    client = TestClient(create_app())
    # ask with alias Sam should resolve to Samantha and not leak Alex
    r = client.post("/api/ask", json={"question": "¿Qué le gusta a Sam?", "about": "Sam", "slug": "sample"})
    # With minimal dataset and real Chroma absent, may abstain; we just verify no Alex leakage if citations present
    if r.status_code == 200:
        body = r.json()
        for c in body.get("citations", []):
            assert c["sender"] != "Alex"
    else:
        # 422 is also acceptable for this minimal fixture without vectors
        assert r.status_code in (200, 422)


def test_ask_facts_and_inferences_separation(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    dataset = root / "sample"
    dataset.mkdir(parents=True)
    (dataset / "dataset.json").write_text(json.dumps({"slug": "sample", "name": "Samantha"}), encoding="utf-8")

    from lazograph.domain.answer import Answer, Evidence

    fake_answer = Answer(
        text="A Samantha le gusta pintar.",
        citations=(
            Evidence(
                message_id="m1",
                sender="Samantha",
                source_file="chat.jsonl",
                timestamp="2026-01-01T10:01:00",
                excerpt="Me gusta pintar paisajes",
                score=0.92,
            ),
        ),
        confidence=0.88,
        entities=("Samantha",),
        retrieval_summary={"docs_retrieved": 3, "focal_ratio": 1.0},
        abstained=False,
        facts=("Le gusta pintar paisajes.",),
        inferences=("Probablemente disfruta actividades tranquilas.",),
        suggestions=("Regalarle pinturas o lienzos.",),
        missing_information=("No especifica qué tipo de pinturas.",),
    )

    with patch("lazograph.features.ask_person.service.answer_about_person", return_value=fake_answer):
        client = TestClient(create_app())
        r = client.post("/api/ask", json={"question": "¿Qué le gusta a Samantha?", "about": "Samantha", "slug": "sample"})
        assert r.status_code == 200
        body = r.json()
        assert body["text"] == "A Samantha le gusta pintar."
        assert body["confidence"] == 0.88
        assert body["facts"] == ["Le gusta pintar paisajes."]
        assert body["inferences"] == ["Probablemente disfruta actividades tranquilas."]
        assert body["suggestions"] == ["Regalarle pinturas o lienzos."]
        assert body["missing_information"] == ["No especifica qué tipo de pinturas."]
        assert len(body["citations"]) == 1
        assert body["citations"][0]["sender"] == "Samantha"
        assert body["retrieval_summary"]["docs_retrieved"] == 3


def test_ask_abstention_response(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    dataset = root / "sample"
    dataset.mkdir(parents=True)
    (dataset / "dataset.json").write_text(json.dumps({"slug": "sample", "name": "Samantha"}), encoding="utf-8")

    from lazograph.domain.answer import Answer

    abstained_answer = Answer(
        text="No encontré evidencia suficiente en las conversaciones.",
        citations=(),
        confidence=0.15,
        entities=("Samantha",),
        retrieval_summary={},
        abstained=True,
        facts=(),
        inferences=(),
        suggestions=(),
        missing_information=(),
    )

    with patch("lazograph.features.ask_person.service.answer_about_person", return_value=abstained_answer):
        client = TestClient(create_app())
        r = client.post("/api/ask", json={"question": "¿Dónde nació?", "about": "Samantha", "slug": "sample"})
        assert r.status_code == 200
        body = r.json()
        assert body["abstained"] is True
        assert body["confidence"] < 0.4
        assert body["citations"] == []


def test_datasets_endpoint_includes_participants(tmp_path, monkeypatch):
    root = tmp_path / "knowledge"
    root.mkdir()
    monkeypatch.setenv("OPENPERSONA_KNOWLEDGE", str(root))
    dataset = root / "sample"
    dataset.mkdir(parents=True)
    (dataset / "dataset.json").write_text(json.dumps({"slug": "sample", "name": "Samantha"}), encoding="utf-8")
    (dataset / "participants.json").write_text(json.dumps({
        "participants": [
            {"name": "Samantha", "identity_type": "persona"},
            {"name": "Alex", "identity_type": "contact"},
        ]
    }), encoding="utf-8")

    client = TestClient(create_app())
    r = client.get("/api/datasets")
    assert r.status_code == 200
    datasets = r.json().get("datasets", [])
    assert len(datasets) == 1
    assert datasets[0]["slug"] == "sample"
    assert datasets[0]["participants"] == ["Samantha", "Alex"]

