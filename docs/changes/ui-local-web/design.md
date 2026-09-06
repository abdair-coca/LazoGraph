# Design: ui-local-web

## Context
LazoGraph is local-first Python with deterministic pipeline (ARCH 16-33) and 8 accepted slices. UI must not duplicate domain logic nor bypass guards (alias isolation, PII scan, equivalent preflight, invariants).

## Decision
FastAPI app in `src/lazograph/ui/app.py` exposing `/api/*` plus Jinja shell at `/`. CLI `lazo ui` starts uvicorn. Frontend uses plain HTML + `fetch` (no Node build). All writes go through existing services; blocking I/O runs in `anyio.to_thread.run_sync`.

## Architecture
```
browser  ->  FastAPI (ui/app.py)
               ├─ GET  /              -> Jinja dashboard (diagnose card + nav)
               ├─ GET  /api/datasets  -> config.knowledge_root() list
               ├─ GET  /api/diagnose?slug -> scripts/dataset_invariants + diagnose logic (read-only)
               ├─ POST /api/import/preview (multipart file+slug+persona) -> features.import_chat.service.build_preview (threadpool)
               ├─ POST /api/import/apply (token) -> features.import_chat + ingest + rebuild_extracted_projection + invariants
               ├─ POST /api/ask {question, about, slug, provider, limit, evidence_budget} -> same router as cli._run_ask
               ├─ GET  /api/plans[?status&participant]&slug -> pending_plans.list_plans
               ├─ GET  /api/plans/{id}?slug -> pending_plans.show_plan
               ├─ GET  /api/graph/entity|path|stats?slug -> query_kg effective graph
               ├─ GET  /api/corrections?slug -> correct_knowledge.correction_records
               └─ GET  /api/wiki?slug -> wiki files list + lint summary
static -> src/lazograph/ui/static/app.js, style.css
templates -> src/lazograph/ui/templates/base.html, dashboard.html
```

## Alternatives Considered
| Alternative | Why rejected |
|-------------|--------------|
| React + Vite | Requires Node, heavier, not needed for simple functional UI |
| Streamlit | Couples UI to Python stateful server, harder to test with TestClient, diverges from REST |
| Electron/Tauri | Desktop bundle complexity, breaks single `pip install` contract |

## Data Flow (import)
`browser file -> POST /preview (temp retained, token uuid) -> server build_preview -> JSON {token, preview} -> user confirms -> POST /apply {token} -> server runs ingest+invariants+plan projection -> JSON {stored, duplicates, invariants}`

## Privacy & Safety
- Default `LocalExtractiveProvider`; `hosted` needs env vars, else 400.
- Preview temp files under `tempfile.mkdtemp` inside `knowledge_root/.ui-preview`, auto-cleaned after apply or 1h expiry.
- Upload cap 20MB, reject `..` in slug via `config.py:27`, no client path trusted.
- All `GET` routes never write; `apply` acquires same file logic as CLI (no concurrent writes; UI-1 uses dataset invariants check, not yet global lock — acceptable for single-user local).

## Testing Strategy
- `tests/test_ui_shell.py`: `TestClient` for `/` 200, `/api/datasets` empty/multi, `/api/diagnose` healthy/warning/error
- `tests/test_ui_import.py`: preview never writes, equivalent guard 422, apply idempotent, PII flags returned
- `tests/test_ui_ask.py`: fake provider, alias isolation, abstention, citation validation, evidence budget cap
- `tests/test_ui_plans_graph.py`: list filtering, show by id, graph read-only
- Each slice runs `pytest -q` and manual `lazo ui` demo checklist

## Rollout
UI-1 ships server+shell+diagnose; UI-2 adds import; UI-3 adds ask; UI-4 adds plans/graph/ops. Each slice gated by tests and demo command.
