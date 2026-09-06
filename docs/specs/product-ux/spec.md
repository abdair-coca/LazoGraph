# Spec: product-ux

> Source: `docs/mockups/lazograph-mvp.html:1-709`, `src/lazograph/ui/templates/base.html`, `docs/specs/ui/spec.md:32-34`, `src/lazograph/domain/answer.py:10-63`
> Change: `docs/changes/product-real`

Resumen ES: Convertir shell mínimo en producto usable sin docs, con búsqueda real y visualización humana.

## Requirements

### REQ-PUX-001: Human states
Every empty/error/loading state SHALL show human ES copy (no stack trace). Examples: “No hay datasets — importá tu chat”, “Archivo muy grande (20MB)”, “Equivalente detectado — revisá antes de confirmar”. SHALL log technical detail to `logs/lazograph.log` but UI shows summary.

### REQ-PUX-002: Search and pagination
`GET /api/search?slug&query&participant&limit&offset` SHALL reuse participant-filtered semantic retrieval (`memory.py` port) with `limit` 1..50 and `offset`, return `{results: Evidence[], total, has_more}`. UI search bar SHALL paginate (“Cargar más”) and SHALL NOT block on chats >10k (virtualized list or server pagination).

### REQ-PUX-003: Timeline
`GET /api/timeline?slug&from&to&participant&granularity` SHALL aggregate active source messages by day/week/month from `sources/*.jsonl` timestamps (respects `dataset.json:timezone`). UI timeline SHALL render bars and allow click-to-filter search.

### REQ-PUX-004: Graph visualization
`GET /api/graph?slug&format=graphviz|json` SHALL return effective graph (generated - retractions + assertions, excluye `plan_*`) as `{nodes:[{id,label,type}], edges:[{from,to,type,confidence}]}`. UI SHALL render interactive SVG/Canvas (zoom, click node → `entity` panel with citations), not just `stats`.

### REQ-PUX-005: Wiki rendering
`GET /api/wiki/{page}?slug` SHALL return rendered Markdown HTML for `wiki/*.md` with evidence tags as links to `Evidence.message_id`. `GET /api/wiki` list SHALL include `lint` summary (`issues/warnings`) per `scripts/lint_wiki.py`.

### REQ-PUX-006: Progress and ETA
Any long operation (`import/apply`, `rebuild_all --atomic`, `backup`) SHALL stream progress via `GET /api/progress/{job_id}` (SSE or polling) with `{stored, total, pct, elapsed, eta}` same as `ingest.py` batch every 128 msgs.

## Scenarios

### Scenario: Search pagination
Given dataset 3k messages con “Alex”
When `GET /api/search?slug=sam&query=proyecto&participant=Alex&limit=20&offset=0` then offset 20
Then both return 20, no overlap, `has_more` correct, UI “Cargar más” funciona

### Scenario: Timeline filter
Given messages en 2026-08-10 y 2026-08-11
When click en barra 08-11 en UI
Then search filtra `from=2026-08-11&to=2026-08-11` y muestra solo ese día

### Scenario: Graph click
Given effective graph `Sam --friend--> Alex`
When click nodo `Alex` en UI
Then panel muestra `query_kg --entity Alex` citations y corrections activas, sin leak de otros

### Scenario: Large file progress
Given upload 15MB chat
When `POST /api/import/apply`
Then `GET /api/progress/{id}` emite `pct` creciente y ETA, UI no se congela
