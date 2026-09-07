"""FastAPI app for local LazoGraph UI."""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.templating import Jinja2Templates

from lazograph.config import knowledge_root, resolve_dataset
from lazograph.features.import_chat.service import ImportValidationError, build_preview
from lazograph.features.pending_plans import PlanProjectionError, list_plans, show_plan

def _get_build_diagnosis():
    try:
        from scripts.diagnose import build_diagnosis as _bd  # type: ignore

        return _bd
    except Exception:
        # fallback: import via path
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent / "scripts"))
        try:
            from diagnose import build_diagnosis as _bd2  # type: ignore

            return _bd2
        except Exception:
            return None

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# In-memory preview store: token -> {tmp_path, slug, persona, adapter, source_name}
_PREVIEWS: dict[str, dict[str, Any]] = {}
_JOBS: dict[str, dict[str, Any]] = {}

CURRENT_SCHEMA = "0.8.0"


def _compare_versions(a: str, b: str) -> int:
    """Compare semver strings: -1 if a<b, 0 if equal, 1 if a>b."""
    def _parts(v: str):
        return [int(x) if x.isdigit() else x for x in v.split(".")]

    pa, pb = _parts(a), _parts(b)
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


def _check_token(request) -> None:
    """REQ-PH-001: if .ui-token exists, require X-UI-Token."""
    try:
        root = knowledge_root()
        tok_path = root / ".ui-token"
        if tok_path.exists():
            expected = tok_path.read_text(encoding="utf-8").strip()
            got = request.headers.get("X-UI-Token") or request.headers.get("x-ui-token")
            if not got or got != expected:
                raise HTTPException(status_code=401, detail="token requerido: X-UI-Token inválido o ausente")
    except HTTPException:
        raise
    except Exception:
        pass


def _validate_slug(slug: str) -> None:
    import re

    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", slug):
        raise HTTPException(status_code=422, detail="slug inválido: debe ser [a-z0-9][a-z0-9_-]*")


def create_app() -> FastAPI:
    app = FastAPI(title="LazoGraph UI", version="0.8.0")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.middleware("http")
    async def _csp_middleware(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    @app.middleware("http")
    async def _token_middleware(request: Request, call_next):
        if request.method in ("POST", "DELETE", "PUT", "PATCH") and request.url.path.startswith("/api/"):
            try:
                root = knowledge_root()
                tok_path = root / ".ui-token"
                if tok_path.exists():
                    expected = tok_path.read_text(encoding="utf-8").strip()
                    got = request.headers.get("X-UI-Token") or request.headers.get("x-ui-token")
                    if not got or got != expected:
                        return JSONResponse({"detail": "token requerido: X-UI-Token inválido o ausente"}, status_code=401)
            except Exception:
                pass
        return await call_next(request)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": "0.8.0"}

    @app.get("/api/datasets")
    def datasets() -> dict:
        root = knowledge_root()
        if not root.exists():
            return {"datasets": []}
        items = []
        for path in sorted(root.iterdir()):
            if path.is_dir() and (path / "dataset.json").exists():
                try:
                    meta = json.loads((path / "dataset.json").read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
                participants = []
                p_file = path / "participants.json"
                if p_file.exists():
                    try:
                        p_data = json.loads(p_file.read_text(encoding="utf-8"))
                        participants = [
                            p.get("name")
                            for p in p_data.get("participants", [])
                            if isinstance(p, dict) and p.get("name")
                        ]
                    except Exception:
                        participants = []
                items.append({
                    "slug": path.name,
                    "name": meta.get("name", path.name),
                    "path": str(path),
                    "participants": participants,
                })
        return {"datasets": items, "knowledge_root": str(root)}

    @app.get("/api/diagnose")
    def diagnose(slug: str) -> JSONResponse:
        try:
            from scripts.runtime import configure_safe_output

            configure_safe_output()
        except Exception:
            pass
        try:
            dataset_dir = resolve_dataset(slug)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        builder = _get_build_diagnosis()
        if builder is None:
            raise HTTPException(status_code=500, detail="diagnose unavailable")
        try:
            report = builder(dataset_dir)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
        status_code = 200 if report.get("ok") else 200  # always 200, client inspects report.ok
        return JSONResponse(report, status_code=status_code)

    @app.post("/api/import/preview")
    async def import_preview(
        request: Request,
        file: UploadFile = File(...),
        slug: str = Form(...),
        persona: str = Form(...),
        adapter: str | None = Form(None),
    ) -> dict:
        _check_token(request)
        _validate_slug(slug)
        if not persona or not persona.strip():
            raise HTTPException(status_code=422, detail="Persona requerida — indicá el nombre de la persona focal del chat.")
        content = await file.read()
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Archivo muy grande (máx 20MB) — probá con un archivo menor a 20MB.")
        # persist to temp file for build_preview (needs path)
        tmp_dir = Path(tempfile.mkdtemp(prefix="lazograph-ui-"))
        tmp_path = tmp_dir / (file.filename or "upload.txt")
        tmp_path.write_bytes(content)

        def _build() -> Any:
            return build_preview(
                str(tmp_path),
                slug=slug,
                persona=persona,
                adapter_name=adapter,
                root=knowledge_root(),
            )

        try:
            preview = await run_in_threadpool(_build)
        except ImportValidationError as exc:
            # cleanup
            try:
                tmp_path.unlink(missing_ok=True)
                tmp_dir.rmdir()
            except Exception:
                pass
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            try:
                tmp_path.unlink(missing_ok=True)
                tmp_dir.rmdir()
            except Exception:
                pass
            msg = str(exc)
            if "Embedding model mismatch" in msg or "embeddinggemma_300m vs" in msg or "An embedding function already exists" in msg:
                raise HTTPException(status_code=422, detail="Modelo de embeddings desactualizado — el dataset 'prueba' usa 'minilm' y el sistema ahora usa 'embeddinggemma'. Solución rápida: set MEMPALACE_EMBEDDING_MODEL=minilm y reintentá. O migrá definitivo: `mempalace --palace \"C:\\Users\\abdai\\.openpersona\\knowledge\\prueba\\.mempalace\\palace\" repair rebuild-index --yes` o `python scripts/ingest.py --slug prueba --rebuild-vectors`. Ver README: diagnose reporta mismatch hasta re-embed.") from exc
            raise HTTPException(status_code=500, detail=msg) from exc

        token = uuid.uuid4().hex
        _PREVIEWS[token] = {
            "tmp_path": str(tmp_path),
            "tmp_dir": str(tmp_dir),
            "slug": slug,
            "persona": persona,
            "adapter": adapter,
            "source_name": file.filename,
        }
        return {
            "token": token,
            "source": str(preview.source),
            "slug": preview.slug,
            "adapter": preview.adapter,
            "parsed_messages": preview.parsed_messages,
            "rejected_notices": preview.rejected_notices,
            "participants": [
                {"name": p.name, "identity": p.identity, "messages": p.messages, "new_messages": p.new_messages}
                for p in preview.participants
            ],
            "persona": preview.persona,
            "duplicates": preview.duplicates,
            "new_messages": preview.new_messages,
            "pii_flags": list(preview.pii_flags),
            "equivalent_sources": list(preview.equivalent_sources),
            "same_source_reimport": bool(preview.same_source_reimport),
            "dataset_exists": bool(preview.dataset_exists),
        }

    @app.post("/api/import/apply")
    async def import_apply(payload: dict) -> dict:
        token = payload.get("token")
        if not token or token not in _PREVIEWS:
            raise HTTPException(status_code=404, detail="preview not found or expired")
        info = _PREVIEWS[token]
        # allow override flags
        allow_equivalent = bool(payload.get("allow_equivalent_source"))
        reconcile_equivalent = bool(payload.get("reconcile_equivalent_source"))

        from lazograph.features.pending_plans import rebuild_extracted_projection
        from scripts import dataset_invariants, init_knowledge, ingest

        root = knowledge_root()

        job_id = uuid.uuid4().hex
        _JOBS[job_id] = {"pct": 5, "stored": 0, "total": 0, "elapsed": 0, "eta": 0, "status": "running"}

        def _progress_cb(stored: int, total: int, elapsed: float, eta: float) -> None:
            pct = int((stored / total) * 90) if total else 10
            _JOBS[job_id].update({
                "pct": max(5, min(95, pct)),
                "stored": stored,
                "total": total,
                "elapsed": round(elapsed, 1),
                "eta": round(eta, 1),
                "status": "running",
            })

        def _apply() -> dict:
            try:
                from scripts.runtime import configure_safe_output

                configure_safe_output()
            except Exception:
                pass
            # need preview again to check dataset_exists
            preview = build_preview(
                info["tmp_path"],
                slug=info["slug"],
                persona=info["persona"],
                adapter_name=info["adapter"],
                root=root,
            )
            dataset_dir = root / info["slug"]
            # same-source reimport fast path (mirrors cli)
            if preview.same_source_reimport:
                result = dataset_invariants.validate_dataset(dataset_dir)
                return {"status": "already_imported", "invariants": result, "preview": preview}

            if preview.equivalent_sources and not (allow_equivalent or reconcile_equivalent):
                raise ImportValidationError(
                    "Import stopped before writes. Use reconcile or allow flag."
                )

            if not preview.dataset_exists:
                init_knowledge.init_dataset(info["slug"], preview.persona, knowledge_root=root)

            ingest_args = [
                "--slug", info["slug"],
                "--source", info["tmp_path"],
                "--adapter", preview.adapter,
                "--persona-name", preview.persona,
                "--persona-exact",
            ]
            if allow_equivalent:
                ingest_args.append("--allow-equivalent-source")
            if reconcile_equivalent:
                ingest_args.append("--reconcile-equivalent-source")
            ingest.main(ingest_args, knowledge_root=root, progress_callback=_progress_cb)
            result = dataset_invariants.validate_dataset(dataset_dir)
            # best-effort plan projection
            try:
                extraction = rebuild_extracted_projection(dataset_dir)
                plans_info = {"plans": len(extraction.plans), "unresolved": len(extraction.unresolved)}
            except PlanProjectionError as exc:
                plans_info = {"error": str(exc)}
            return {"status": "imported", "invariants": result, "plans": plans_info, "preview": preview}

        keep_preview = False
        try:
            import time as _time
            _t0 = _time.time()
            outcome = await run_in_threadpool(_apply)
            elapsed = _time.time() - _t0
            _JOBS[job_id].update({"pct": 100, "elapsed": round(elapsed, 1), "eta": 0, "status": "done"})
            outcome["_job_id"] = job_id
        except ImportValidationError as exc:
            keep_preview = True
            _JOBS[job_id].update({"pct": 0, "status": "error", "error": str(exc)})
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SystemExit as exc:
            _JOBS[job_id].update({"pct": 0, "status": "error"})
            raise HTTPException(status_code=422, detail=f"ingest failed: {exc.code}") from exc
        except Exception as exc:
            _JOBS[job_id].update({"pct": 0, "status": "error", "error": str(exc)})
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        finally:
            if not keep_preview:
                try:
                    Path(info["tmp_path"]).unlink(missing_ok=True)
                    Path(info["tmp_dir"]).rmdir()
                except Exception:
                    pass
                _PREVIEWS.pop(token, None)

        preview = outcome.pop("preview", None)
        if outcome.get("status") == "already_imported":
            return {"status": "already_imported", "message": "Already imported. Dataset unchanged.", "invariants": outcome["invariants"], "job_id": job_id}
        invariants = outcome.get("invariants", {})
        return {"status": "imported", "message": "Import complete.", "invariants": invariants, "plans": outcome.get("plans"), "preview": {"parsed_messages": preview.parsed_messages if preview else None}, "job_id": job_id}

    @app.get("/api/progress/{job_id}")
    async def get_progress(job_id: str) -> dict:
        if job_id not in _JOBS:
            raise HTTPException(status_code=404, detail="trabajo no encontrado")
        return _JOBS[job_id]

    @app.post("/api/ask")
    async def ask(payload: dict) -> dict:
        question = (payload.get("question") or "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="question required")
        slug = payload.get("slug")
        about = payload.get("about")
        provider_name = payload.get("provider", "local")
        limit = int(payload.get("limit", 5))
        evidence_budget = int(payload.get("evidence_budget", 2500))
        if limit < 1:
            raise HTTPException(status_code=400, detail="limit must be >=1")
        if evidence_budget < 100:
            raise HTTPException(status_code=400, detail="evidence_budget must be >=100")

        def _answer() -> Any:
            from lazograph.config import resolve_dataset as _resolve
            from lazograph.features.ask_person.service import answer_about_dataset, answer_about_person
            from lazograph.features.ask_relationship import answer_about_relationship
            from lazograph.features.describe_relationship import answer_describe_relationship, is_relationship_description_question
            from lazograph.features.pending_plans import answer_plan_question, is_plan_question
            from lazograph.features.suggestions import answer_suggestion_question, is_suggestion_question
            from lazograph.infrastructure.llm import HostedProvider, LocalExtractiveProvider, OllamaProvider

            dataset_dir = _resolve(slug)
            if provider_name == "ollama":
                provider = OllamaProvider(model=payload.get("model"))
            elif provider_name == "hosted":
                provider = HostedProvider(model=payload.get("model"))
            else:
                provider = LocalExtractiveProvider()

            # mirrors cli._run_ask routing
            if about:
                return answer_about_person(dataset_dir, question, about, provider, limit=limit, evidence_budget=evidence_budget)
            if is_plan_question(question):
                return answer_plan_question(dataset_dir, question)
            if is_suggestion_question(question):
                return answer_suggestion_question(dataset_dir, question, provider, limit=limit, evidence_budget=evidence_budget)
            if is_relationship_description_question(question):
                return answer_describe_relationship(dataset_dir, question, provider, limit=limit, evidence_budget=evidence_budget)
            # try resolve single participant
            from lazograph.features.ask_person.service import resolve_question_participant
            mentioned = None
            try:
                mentioned = resolve_question_participant(dataset_dir, question)
            except Exception:
                mentioned = None
            if mentioned is not None:
                return answer_about_person(dataset_dir, question, str(mentioned["name"]), provider, limit=limit, evidence_budget=evidence_budget)
            # relationship keyword fallback
            import re
            if re.search(r"\b(?:relationship|relation|related|connected|relación|relacionado|conectado|vínculo|vinculo|pareja|amigo|amiga|hermano|hermana|colleague|coworker|parent|child|manager|jefe|familia)\b", question, re.IGNORECASE):
                return answer_about_relationship(dataset_dir, question, provider, limit=limit, evidence_budget=evidence_budget)
            return answer_about_dataset(dataset_dir, question, provider, limit=limit, evidence_budget=evidence_budget)

        try:
            answer = await run_in_threadpool(_answer)
        except Exception as exc:
            # map known errors to 422 with message
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            import hashlib
            import datetime

            root = knowledge_root()
            logs_dir = root / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            cfg_path = root / "config.json"
            telemetry_on = False
            if cfg_path.exists():
                try:
                    telemetry_on = bool(json.loads(cfg_path.read_text(encoding="utf-8")).get("telemetry_enabled"))
                except Exception:
                    pass
            q_hash = "sha256:" + hashlib.sha256(question.encode("utf-8")).hexdigest()[:16]
            entry = {
                "ts": datetime.datetime.now().isoformat(),
                "route": "/api/ask",
                "slug": slug,
                "question_hash": q_hash,
            }
            if telemetry_on:
                entry["question"] = question
            with (logs_dir / "lazograph.log").open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

        return answer.to_dict()

    @app.get("/api/plans")
    def plans(slug: str, status: str | None = None, participant: str | None = None) -> dict:
        try:
            dataset_dir = resolve_dataset(slug)
            items = list_plans(dataset_dir, status=status, participant=participant)
        except PlanProjectionError as exc:
            # missing projection => empty, not error for UI
            if "missing or corrupt" in str(exc).lower() or "projection" in str(exc).lower():
                return {"plans": [], "warning": str(exc)}
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"plans": [p.to_dict() for p in items]}

    @app.get("/api/plans/{plan_id}")
    def plan_show(plan_id: str, slug: str) -> dict:
        try:
            dataset_dir = resolve_dataset(slug)
            plan = show_plan(dataset_dir, plan_id)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return plan.to_dict()

    @app.get("/api/corrections")
    def corrections(slug: str) -> dict:
        from lazograph.features.correct_knowledge import correction_records
        try:
            dataset_dir = resolve_dataset(slug)
            records = correction_records(dataset_dir)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"corrections": records}

    @app.get("/api/graph/stats")
    def graph_stats(slug: str) -> dict:
        try:
            dataset_dir = resolve_dataset(slug)
            from scripts.query_kg import _load_kg, _load_participant_profiles
            profiles = _load_participant_profiles(dataset_dir)
            entities, relationships, _ = _load_kg(dataset_dir, profiles=profiles)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"entities": len(entities), "relationships": len(relationships)}

    @app.get("/api/search")
    def search(slug: str, query: str = "", participant: str | None = None, limit: int = 20, offset: int = 0, from_date: str | None = None, to_date: str | None = None) -> dict:
        if limit < 1 or limit > 50:
            raise HTTPException(status_code=400, detail="limit 1..50")
        if offset < 0:
            raise HTTPException(status_code=400, detail="offset >=0")
        try:
            dataset_dir = resolve_dataset(slug)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        sources_dir = dataset_dir / "sources"
        results = []
        q = (query or "").lower()
        participant_lower = (participant or "").lower()
        if sources_dir.exists():
            for jsonl in sorted(sources_dir.glob("*.jsonl")):
                try:
                    lines = jsonl.read_text(encoding="utf-8").splitlines()
                except Exception:
                    continue
                for idx, line in enumerate(lines, 1):
                    try:
                        msg = json.loads(line)
                    except Exception:
                        continue
                    sender = str(msg.get("metadata", {}).get("sender") or "")
                    content = str(msg.get("content") or "")
                    ts = str(msg.get("timestamp") or "")
                    if participant and participant_lower not in sender.lower():
                        continue
                    if q and q not in content.lower():
                        continue
                    if from_date and ts[:10] < from_date:
                        continue
                    if to_date and ts[:10] > to_date:
                        continue
                    msg_id = f"{jsonl.name}:{idx}"
                    results.append(
                        {
                            "message_id": msg_id,
                            "sender": sender,
                            "source_file": jsonl.name,
                            "timestamp": msg.get("timestamp"),
                            "excerpt": content[:500],
                            "score": 1.0,
                            "content": content,
                        }
                    )
        total = len(results)
        sliced = results[offset : offset + limit]
        return {"results": sliced, "total": total, "has_more": (offset + limit) < total, "limit": limit, "offset": offset}

    @app.get("/api/timeline")
    def timeline(
        slug: str,
        granularity: str = "day",
        participant: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> dict:
        try:
            dataset_dir = resolve_dataset(slug)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        from collections import Counter

        counter = Counter()
        sources_dir = dataset_dir / "sources"
        if sources_dir.exists():
            for jsonl in sorted(sources_dir.glob("*.jsonl")):
                try:
                    lines = jsonl.read_text(encoding="utf-8").splitlines()
                except Exception:
                    continue
                for line in lines:
                    try:
                        msg = json.loads(line)
                    except Exception:
                        continue
                    if participant and participant.lower() not in str(msg.get("metadata", {}).get("sender") or "").lower():
                        continue
                    ts = str(msg.get("timestamp") or "")[:10]  # YYYY-MM-DD
                    if not ts:
                        continue
                    if from_date and ts < from_date:
                        continue
                    if to_date and ts > to_date:
                        continue
                    counter[ts] += 1
        buckets = [{"date": k, "count": v} for k, v in sorted(counter.items())]
        return {"buckets": buckets, "granularity": granularity, "total": sum(counter.values())}

    @app.get("/api/graph")
    def graph(slug: str, format: str = "json") -> dict:
        try:
            dataset_dir = resolve_dataset(slug)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        nodes: list[dict] = []
        edges: list[dict] = []
        # try effective graph
        try:
            from scripts.query_kg import _load_kg, _load_participant_profiles

            profiles = _load_participant_profiles(dataset_dir)
            entities, relationships, _ = _load_kg(dataset_dir, profiles=profiles)
            # nodes from entities
            for ent in entities:
                # entities may be dict or tuple; handle both
                if isinstance(ent, dict):
                    eid = ent.get("id") or ent.get("name") or str(ent)
                    label = ent.get("name") or eid
                    ntype = ent.get("type") or "entity"
                else:
                    eid = str(ent)
                    label = eid
                    ntype = "entity"
                nodes.append({"id": str(eid), "label": str(label), "type": str(ntype)})
            for rel in relationships:
                if isinstance(rel, dict):
                    rtype = rel.get("predicate") or rel.get("type") or "related"
                    if str(rtype).startswith("plan_"):
                        continue
                    frm = rel.get("subject") or rel.get("from") or ""
                    to = rel.get("object") or rel.get("to") or ""
                    conf = rel.get("confidence", 1.0)
                elif isinstance(rel, (list, tuple)) and len(rel) >= 3:
                    frm, rtype, to = rel[0], rel[1], rel[2]
                    if str(rtype).startswith("plan_"):
                        continue
                    conf = 1.0
                else:
                    continue
                edges.append({"from": str(frm), "to": str(to), "type": str(rtype), "confidence": float(conf) if conf else 1.0})
        except Exception:
            # fallback: try participants as nodes
            try:
                ppath = dataset_dir / "participants.json"
                if ppath.exists():
                    data = json.loads(ppath.read_text(encoding="utf-8"))
                    for p in data.get("participants", []):
                        nodes.append({"id": p.get("name"), "label": p.get("name"), "type": "participant"})
            except Exception:
                pass
        return {"nodes": nodes, "edges": edges, "format": format}

    @app.get("/api/wiki")
    def wiki(slug: str) -> dict:
        try:
            dataset_dir = resolve_dataset(slug)
            wiki_dir = dataset_dir / "wiki"
            if not wiki_dir.exists():
                return {"pages": []}
            pages = []
            for path in sorted(wiki_dir.glob("*.md")):
                pages.append({"name": path.name, "size": path.stat().st_size})
            # include lint summary if available
            try:
                from scripts.lint_wiki import lint_wiki

                report = lint_wiki(wiki_dir, dataset_dir)
                return {"pages": pages, "lint": {"issues": len(report.get("issues", [])), "warnings": len(report.get("warnings", []))}}
            except Exception:
                return {"pages": pages}
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/wiki/{page}")
    def wiki_page(page: str, slug: str) -> HTMLResponse:
        try:
            dataset_dir = resolve_dataset(slug)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        wiki_file = dataset_dir / "wiki" / page
        if not wiki_file.exists():
            raise HTTPException(status_code=404, detail="wiki page not found")
        content = wiki_file.read_text(encoding="utf-8")
        # simple markdown to html: escape and wrap
        import html

        escaped = html.escape(content)
        html_body = f"<pre>{escaped}</pre>"
        # try markdown lib if available
        try:
            import markdown  # type: ignore

            html_body = markdown.markdown(content)
        except Exception:
            pass
        import re

        html_body = re.sub(
            r"\[([a-zA-Z0-9_\.\-]+:\d+)\]",
            r'<a href="#" class="citation wiki-evidence-link" data-tag="\1">[\1]</a>',
            html_body,
        )
        return HTMLResponse(f"<html><body>{html_body}</body></html>")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        # slicing: if no datasets, render wizard (REQ-PD-002)
        try:
            root = knowledge_root()
            has_dataset = any((p / "dataset.json").exists() for p in root.iterdir()) if root.exists() else False
        except Exception:
            has_dataset = False
        if not has_dataset:
            wizard = TEMPLATES_DIR / "wizard.html"
            if wizard.exists():
                return wizard.read_text(encoding="utf-8")
        html_path = TEMPLATES_DIR / "base.html"
        if html_path.exists():
            return html_path.read_text(encoding="utf-8")
        return """<!doctype html><html><head><meta charset='utf-8'><title>LazoGraph</title><link rel='stylesheet' href='/static/style.css'></head><body><h1>LazoGraph UI</h1><p>API at /api/*</p><div id='app'>Loading...</div><script src='/static/app.js'></script></body></html>"""

    @app.post("/api/migrate")
    def migrate(payload: dict) -> dict:
        slug = (payload.get("slug") or "").strip()
        target = payload.get("target") or CURRENT_SCHEMA
        if not slug:
            raise HTTPException(status_code=400, detail="slug requerido")
        try:
            dataset_dir = resolve_dataset(slug)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        ds_json = dataset_dir / "dataset.json"
        try:
            data = json.loads(ds_json.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        current = str(data.get("schema_version") or "0.0.0")
        cmp = _compare_versions(current, target)
        if cmp == 0:
            return {"migrated": False, "from": current, "to": target, "message": "ya en versión actual"}
        if cmp > 0:
            raise HTTPException(status_code=422, detail=f"No se permite downgrade de {current} a {target} — operación detenida")
        # backup before migrate
        backup_dir = dataset_dir / ".migrations"
        backup_dir.mkdir(parents=True, exist_ok=True)
        import datetime

        ts = datetime.datetime.now().isoformat().replace(":", "-")
        bak = backup_dir / f"dataset-{ts}.bak"
        try:
            bak.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            # also backup participants.json if exists
            p_path = dataset_dir / "participants.json"
            if p_path.exists():
                (backup_dir / f"participants-{ts}.bak").write_bytes(p_path.read_bytes())
        except Exception:
            pass
        data["schema_version"] = target
        ds_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"migrated": True, "from": current, "to": target, "backup": str(bak)}

    @app.post("/api/backup")
    def backup(payload: dict) -> dict:
        slug = (payload.get("slug") or "").strip()
        if not slug:
            raise HTTPException(status_code=400, detail="slug requerido")
        try:
            dataset_dir = resolve_dataset(slug)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        import zipfile
        import tempfile

        tmp = Path(tempfile.mktemp(suffix=".zip"))
        # create zip of dataset_dir excluding .mempalace lock files
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for path in dataset_dir.rglob("*"):
                if path.is_file():
                    # skip chroma lock files that may be locked
                    if "chroma.sqlite3" in str(path) and path.suffix == "-wal":
                        continue
                    rel = path.relative_to(dataset_dir)
                    z.write(path, arcname=str(rel))
        # also copy to a stable location under knowledge_root for test discovery
        try:
            dest_dir = dataset_dir.parent / ".backups"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{slug}-{tmp.name}"
            dest.write_bytes(tmp.read_bytes())
            return {"path": str(dest), "zip": str(dest), "backup": str(dest)}
        except Exception:
            return {"path": str(tmp), "zip": str(tmp)}

    @app.post("/api/restore")
    async def restore(slug: str = Form(None), file: UploadFile = File(None)) -> dict:  # type: ignore
        # supports both JSON and multipart: if file provided, use it; else try payload
        # For multipart, slug may be in Form
        if file is None:
            raise HTTPException(status_code=400, detail="file requerido")
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="zip vacío")
        # determine target slug
        target_slug = slug or (file.filename or "").replace(".zip", "") or "restored"
        # fallback: try to infer from zip content
        import zipfile
        import tempfile

        tmp_zip = Path(tempfile.mktemp(suffix=".zip"))
        tmp_zip.write_bytes(content)
        try:
            with zipfile.ZipFile(tmp_zip, "r") as z:
                # validate: must contain dataset.json
                names = z.namelist()
                if "dataset.json" not in names:
                    raise HTTPException(status_code=422, detail="zip inválido: falta dataset.json")
                # extract to temp then move atomically
                extract_tmp = Path(tempfile.mkdtemp(prefix="restore-"))
                z.extractall(extract_tmp)
                # if zip contains top-level folder, handle
                # our backup zips store relative paths, so extract_tmp contains dataset files directly
                # determine knowledge_root
                root = knowledge_root()
                root.mkdir(parents=True, exist_ok=True)
                dest = root / target_slug
                # if dataset exists, remove first (recoverable via backup)
                if dest.exists():
                    import shutil

                    shutil.rmtree(dest)
                dest.mkdir(parents=True, exist_ok=True)
                # move files
                import shutil as _shutil

                for item in extract_tmp.rglob("*"):
                    if item.is_file():
                        rel = item.relative_to(extract_tmp)
                        out = dest / rel
                        out.parent.mkdir(parents=True, exist_ok=True)
                        _shutil.copy2(item, out)
                # cleanup
                import shutil as __shutil

                __shutil.rmtree(extract_tmp, ignore_errors=True)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"restore falló: {exc}") from exc
        finally:
            try:
                tmp_zip.unlink(missing_ok=True)
            except Exception:
                pass
        return {"restored": True, "slug": target_slug}

    @app.get("/api/logs")
    def logs(slug: str | None = None) -> dict:
        try:
            root = knowledge_root()
            log_path = root / "logs" / "lazograph.log"
            if not log_path.exists():
                return {"logs": [], "warning": "no logs"}
            # read last 100 lines, sanitize
            lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-100:]
            # ensure no raw PII: we already log hash, so return as is
            return {"logs": lines, "count": len(lines)}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/telemetry")
    def telemetry_get() -> dict:
        try:
            root = knowledge_root()
            cfg_path = root / "config.json"
            if cfg_path.exists():
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                return {"enabled": bool(data.get("telemetry_enabled"))}
        except Exception:
            pass
        return {"enabled": False}

    @app.post("/api/telemetry")
    def telemetry_post(payload: dict) -> dict:
        enabled = bool(payload.get("enabled"))
        try:
            root = knowledge_root()
            root.mkdir(parents=True, exist_ok=True)
            cfg_path = root / "config.json"
            data = {}
            if cfg_path.exists():
                try:
                    data = json.loads(cfg_path.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            data["telemetry_enabled"] = enabled
            cfg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"enabled": enabled}

    @app.delete("/api/datasets/{slug}")
    def delete_dataset(slug: str, confirm: str | None = None) -> dict:
        _validate_slug(slug)
        if confirm != slug:
            raise HTTPException(status_code=400, detail="confirm debe ser igual al slug")
        try:
            dataset_dir = resolve_dataset(slug)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        import shutil
        import datetime
        import time

        root = knowledge_root()
        quarantine = root / "quarantine"
        quarantine.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().isoformat().replace(":", "-")
        dest = quarantine / f"deleted-{slug}-{ts}"
        # retry for Windows locked sqlite; don't pre-create dest
        for attempt in range(5):
            try:
                shutil.move(str(dataset_dir), str(dest))
                break
            except PermissionError as exc:
                if attempt == 4:
                    raise HTTPException(status_code=500, detail=str(exc)) from exc
                time.sleep(0.5)
            except shutil.Error as exc:
                # if dest exists, remove and retry
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                    continue
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"deleted": True, "quarantine": str(dest), "slug": slug}

    @app.get("/api/update-check")
    def update_check() -> dict:
        # offline-safe, never blocks
        current = CURRENT_SCHEMA
        latest = current
        # try to fetch latest tag with short timeout, ignore failures
        try:
            import urllib.request

            req = urllib.request.Request("https://api.github.com/repos/acnlabs/persona-knowledge/releases/latest", headers={"User-Agent": "LazoGraph"})
            with urllib.request.urlopen(req, timeout=3) as resp:  # type: ignore
                data = json.loads(resp.read().decode("utf-8"))
                latest = (data.get("tag_name") or current).lstrip("v")
        except Exception as exc:
            return {"current": current, "latest": latest, "update_available": False, "warning": f"sin conexión u offline: {exc}"[:200]}
        try:
            avail = _compare_versions(latest, current) > 0
        except Exception:
            avail = False
        return {"current": current, "latest": latest, "update_available": avail}

    return app


app = create_app()
