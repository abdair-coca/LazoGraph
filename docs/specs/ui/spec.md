# Spec: ui

> Source: `docs/VERTICAL_SLICES.md` (8 slices Accepted), `docs/ARCHITECTURE.md:38-284`, `src/lazograph/cli.py:60-638`, `docs/mockups/lazograph-mvp.html`
> Change: `docs/changes/ui-local-web`

Resumen ES: UI web local que expone todos los slices sin duplicar lógica de dominio, con guards de privacidad e invariantes idénticos al CLI.

## Requirements

### REQ-UI-001: Local web server
System SHALL expose `lazo ui [--host 127.0.0.1] [--port 8765] [--no-browser]` running a local FastAPI server that serves UI under `/` and API under `/api/*`. SHALL NOT require external network. SHALL NOT sync datasets externally.

### REQ-UI-002: Dataset and health
`GET /api/datasets` SHALL list datasets under `knowledge_root()` (same logic as `config.py:23-50`). `GET /api/diagnose?slug=<s>` SHALL return read-only health identical to `scripts/diagnose.py` (critical `error` only on divergent counts/unreadable DB, `warning` for stale exports). Dashboard SHALL show message/participant/vector/KG counts.

### REQ-UI-003: Import preview (non-mutating)
`POST /api/import/preview` SHALL accept `multipart/form-data` with `file`, `slug`, `persona` (and optional `adapter`) and return same `ImportPreview` fields as `cli.py:202-228` (adapter, parsed_messages, rejected_notices, participants[], persona, duplicates, new_messages, pii_flags, equivalent_sources) WITHOUT writing. Large equivalent source guard SHALL be identical to CLI (`cli.py:265-273`).

### REQ-UI-004: Import apply (guarded)
`POST /api/import/apply` SHALL require a prior preview (temp file retained server-side by preview token) and SHALL run same pipeline as `cli.py:279-319` (init_dataset if missing, ingest, invariants, `rebuild_extracted_projection`). SHALL reject path traversal, cap 20MB, run blocking work in threadpool. SHALL return `Already imported. Dataset unchanged.` on idempotent reimport and leave invariants passing.

### REQ-UI-005: Unified ask
`POST /api/ask` SHALL accept `{question, slug?, about?, provider?, limit?, evidence_budget?}` and route identically to `cli.py:373-436` (about → person, plan question → `answer_plan_question`, suggestion → `answer_suggestion_question`, describe → `answer_describe_relationship`, single-participant mention → person, relationship keyword → relationship, else dataset). SHALL return `Answer.to_dict()` (`domain/answer.py:39-63`) with `text`, `citations[]`, `confidence`, `entities`, `retrieval_summary`, `facts/inferences/suggestions/missing_information`, `abstained`. SHALL enforce alias canonical filter before retrieval and citation validation (`tests/test_ask_person.py:145-250`).

### REQ-UI-006: Plans / Graph / Corrections read-only
`GET /api/plans?slug&status&participant`, `GET /api/plans/{id}?slug`, `GET /api/graph/entity|path|stats?slug`, `GET /api/corrections?slug`, `GET /api/wiki?slug` SHALL be read-only and SHALL use effective graph (generated - retractions + assertions) and exclude `plan_*` edges from relationship traversal. Plans SHALL respect IANA timezone and `unresolved` lifecycle.

### REQ-UI-007: Privacy boundary
Default provider SHALL be `local` offline (`LocalExtractiveProvider`). `hosted` SHALL require explicit `LAZOGRAPH_HOSTED_URL|MODEL|API_KEY` and SHALL receive only selected evidence + whitelisted metadata, never full dataset nor local paths.

### REQ-UI-008: Simple frontend
`/` SHALL serve a minimal functional shell (dataset selector, nav, diagnose card) that works with JS disabled for read-only views and enhances with fetch for import/ask. No heavy build required; static assets under `src/lazograph/ui/static`.

## Scenarios

### Scenario: Preview never writes
Given `lazo ui` running and no dataset
When `POST /api/import/preview` with `sample-whatsapp-localized.txt`
Then response `parsed_messages=4`, `rejected_notices=1`, `equivalent_sources=[]`, and no file created under `knowledge_root/slug`

### Scenario: Equivalent guard via UI
Given active backup covers 96% overlap
When `POST /api/import/apply` without reconcile flag
Then 422 with `Import stopped before writes` and zero files changed

### Scenario: Ask via UI equals CLI
Given dataset with `Samantha`/`Alex` messages
When `POST /api/ask {"question":"¿Qué le gusta a Samantha?","about":"Sam"}`
Then citations only `Samantha`, `abstained=false`, text contains `[chat.jsonl:…]`, identical to `answer_about_person` with `LocalExtractiveProvider`

### Scenario: Idempotent apply via UI
Given dataset already contains source
When re-`POST /api/import/apply` same file
Then `Already imported. Dataset unchanged.` and file hashes unchanged

### Scenario: Diagnose via UI
Given dataset with divergent counts
When `GET /api/diagnose?slug=sample`
Then health `error` and `GET /api/datasets` still lists dataset
