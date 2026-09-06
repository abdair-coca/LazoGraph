# Spec: product-polish

> Source: `src/lazograph/ui/app.py:60-853`, `src/lazograph/ui/templates/base.html:12-186`, `src/lazograph/ui/static/app.js:1-156`, `src/lazograph/domain/answer.py:10-63`, `docs/ARCHITECTURE.md:37-79`, `docs/OPERATIONS.md:397-433`, `docs/specs/product-ux/spec.md:1-48`, `docs/specs/product-hardening/spec.md:1-45`, `docs/specs/product-distribution/spec.md:1-45`
> Change: `docs/changes/product-polish`
> Mode: single consolidated spec, 4 vertical slices (A-D)

Resumen ES: Cerrar LazoGraph como producto usable por cualquiera. Todos los botones funcionan con estados humanos, respuestas se interpretan en secciones con evidencia, y cada flujo vertical queda verificado E2E sin requerir docs.

---

## Requirements

### REQ-PP-001: Import flow — preview humano + confirm + progress
`POST /api/import/preview` (multipart `file, slug, persona, adapter`) SHALL parse via `features/import_chat/service.py:build_preview` sin escribir, y devolver `{token, adapter, parsed_messages, rejected_notices, participants[{name,identity,messages,new_messages}], persona, duplicates, new_messages, pii_flags, equivalent_sources, same_source_reimport, dataset_exists}` como `ui/app.py:139`. UI SHALL renderizar preview en humano ES: lista participantes con rol, badges PII/equivalent ("Equivalente detectado — revisá antes de confirmar"), counts. `POST /api/import/apply {token, allow_equivalent_source?, reconcile_equivalent_source?}` SHALL aplicar con validación de invariants `dataset_invariants.validate_dataset` y `rebuild_extracted_projection`. SHALL exponer `GET /api/progress/{job_id}` con `{stored,total,pct,elapsed,eta}` cada 128 msgs como `scripts/ingest.py` batch. Wizard `GET /` cuando no hay datasets SHALL usar `wizard.html` con ids únicos y mismo flujo.

### REQ-PP-002: Ask — respuestas interpretadas y citadas
`POST /api/ask {question, slug?, about?, provider="local", limit, evidence_budget}` SHALL rutear como `cli.py:379-442` (about → `answer_about_person`; `is_plan_question` → `answer_plan_question`; `is_suggestion_question` → `answer_suggestion_question`; `is_relationship_description_question` → `answer_describe_relationship`; fallback `resolve_question_participant` → relationship keyword → `answer_about_dataset`). UI SHALL renderizar `Answer` de `domain/answer.py` en secciones visibles: **Texto** + **Hechos** (`facts`) + **Interpretación** (`inferences` etiquetadas) + **Sugerencias** (`suggestions`) + **Falta info** (`missing_information`) + **Citas** `[source:line] sender timestamp score excerpt` clickeables que filtran `GET /api/search?participant=`. SHALL mostrar `confidence` badge y `retrieval_summary` en debug. SHALL abstener con copy humano ES ("No encontré evidencia suficiente para ... — probá con '¿Qué le gusta a Alex?'") cuando `GroundingError` o citas insuficientes. Nunca inventar.

### REQ-PP-003: Search + pagination
`GET /api/search?slug&query&participant&limit1..50&offset` SHALL filtrar `sources/*.jsonl` con `participant` en `metadata.sender` y `query` en `content` case-insensitive, devolver `{results: Evidence[], total, has_more, limit, offset}` como `app.py:415`. Validar `limit 1..50`, `offset >=0`. UI SHALL paginar con "Cargar más" sin overlap (`ids1 ∩ ids2 = ∅`), virtualizar o paginar server para >10k, mostrar empty humano "Sin resultados para 'X' — probá sin acentos o con alias".

### REQ-PP-004: Timeline agregada y filtrable
`GET /api/timeline?slug&granularity=day/week/month&participant&from&to` SHALL agregar mensajes activos de `sources/*.jsonl` por `timestamp[:10]` respetando `dataset.json:timezone` IANA (`app.py:463` buckets `{date,count}`). UI SHALL renderizar barras proporcionales y al click SHALL filtrar search con `from=YYYY-MM-DD&to=YYYY-MM-DD` (corrige `app.js:100` que hoy ignora fecha). SHALL mostrar total y granularidad.

### REQ-PP-005: Graph efectivo visual
`GET /api/graph?slug&format=json` SHALL devolver `effective graph = generated - retractions + assertions` excluyendo `plan_*` edges (`ARCHITECTURE.md:118`, `app.py:492`). Formato `{nodes:[{id,label,type}], edges:[{from,to,type,confidence}]}`. UI SHALL intentar `cytoscape` CDN y si falla SHALL caer a lista + stats. Click nodo SHALL cargar `GET /api/search?participant={id}` citas y mostrar corrections activas sin leak. SHALL exponer también `GET /api/graph/stats` conteo.

### REQ-PP-006: Wiki renderizada y linkeada
`GET /api/wiki?slug` list SHALL devolver `{pages:[{name,size}], lint:{issues,warnings}}` via `scripts/lint_wiki.py` (`app.py:547`). `GET /api/wiki/{page}?slug` SHALL devolver HTML renderizado de `wiki/*.md` con escape y, si `markdown` disponible, render; evidence tags `[source:line]` SHALL ser links a search. UI SHALL tener botón `id="wiki-load"` (corrige `base.html:159` sin id) y render en `#wiki-content`.

### REQ-PP-007: Plans filtrables
`GET /api/plans?slug&status&participant` y `GET /api/plans/{id}?slug` (`app.py:371`) SHALL listar/mostrar `Plan` con `{id,title,status,participants,scheduled_for,location,source_ids,transitions}`. UI tab Plans SHALL tener filtros `status` y `participant` + botón show detail con lifecycle `proposed→pending→scheduled→completed→cancelled`. Read-only, nunca muta.

### REQ-PP-008: Ops + diagnose legible
`GET /api/datasets`, `GET /api/diagnose?slug`, `GET /api/health` (`app.py:98`) SHALL alimentar dashboard KPIs `kpi-messages, kpi-personas, kpi-graph` desde `diagnose.json` (`sources.messages`, `participants.profiles`, `vectors.count`, graph stats). UI SHALL mostrar estado humano + raw JSON colapsable. `GET /api/logs?slug` tail 100 sin PII, `GET /api/telemetry` estado, `POST /api/telemetry {enabled}` opt-in `config.json`.

### REQ-PP-009: Backup / Restore / Delete confiable
`POST /api/backup {slug}` SHALL crear zip de `${slug}/` excluyendo `chroma.sqlite3-wal` locks y guardar copia en `knowledge_root/.backups/` (`app.py:655`). `POST /api/restore` multipart zip SHALL validar `dataset.json` presente, extraer atómicamente a `knowledge_root/{slug}` (corrige `migrate` caso). `DELETE /api/datasets/{slug}?confirm={slug}` SHALL mover a `quarantine/deleted-{slug}-{ts}` recuperable 30d con retry Windows locks (`app.py:794`). `GET /api/update-check` offline-safe timeout 3s → `{current,latest,update_available,warning:"sin conexión"}`.

### REQ-PP-010: Hardening local
`lazo ui` SHALL bindear `127.0.0.1` default (`--host 0.0.0.0` explícito + warning). Si `knowledge_root/.ui-token` existe SHALL exigir `X-UI-Token` en `POST /api/*` (`app.py:60` → 401). Validar `slug` regex `[a-z0-9][a-z0-9_-]*` (`app.py:76` → 422), cap `file` 20MB → 413 (`app.py:152`), sanitizar wiki `html.escape` y CSP `default-src 'self'; script-src 'self'; connect-src 'self'` (`app.py:91`), no reflejar `OPENPERSONA_KNOWLEDGE` path. Logs a `logs/lazograph.log` sin PII cruda.

### REQ-PP-011: Copy humano en todos los estados
Todo empty/loading/error SHALL mostrar copy humano ES (no stack): "No hay datasets — importá tu chat", "Archivo muy grande (20MB)", "Equivalente detectado — revisá antes de confirmar", "Sin evidencia suficiente — probá reformular", "Sin conexión". Detalle técnico SHALL ir a `logs`/`#raw` colapsable. UI SHALL distinguir loading (spinner/disabled), success (badge verde), error (badge rojo + acción siguiente).

---

## Scenarios

### Scenario: Import happy + progress
Given dataset no existe y `POST /api/import/preview` con `sample-whatsapp-localized.txt` persona Samantha
When render preview muestra participantes/PII/equivalent humano y `POST /api/import/apply {token}` con `GET /api/progress/{id}` emitiendo `pct` creciente
Then `GET /api/diagnose?slug=sample` healthy, `GET /api/datasets` lista slug, reimport mismo token → `already_imported`

### Scenario: Import equivalent guard
Given dataset sample existe
When `POST /api/import/preview` con backup equivalente (>95% overlap)
Then preview muestra `equivalent_sources` y `POST /api/import/apply` sin flag → 422 humano, con `reconcile_equivalent_source` → quarantine + rebuild ok

### Scenario: Ask interpretado con citas
Given dataset con mensajes Alex/Samantha
When `POST /api/ask {question:"¿Qué le gusta a Alex?", about:"Alex"}` 
Then UI muestra Text + Facts + Interpretación + Citations `[chat.jsonl:2]` clickeables → search filtra participant, confidence badge, retrieval_summary en debug; `POST /api/ask` con pregunta sin evidencia → abstención humana sin citas inventadas

### Scenario: Ask routing sin about
Given pregunta "¿Qué relación tengo con Alex?" sin about
When `POST /api/ask`
Then resuelve persona dataset + Alex y devuelve relationship con path y hechos separados

### Scenario: Search pagination sin overlap
Given 25 mensajes con "proyecto" de Alex
When `GET /api/search?query=proyecto&participant=Alex&limit=10&offset=0` luego `offset=10`
Then cada uno 10 results, `ids1 ∩ ids2 = ∅`, `has_more` correcto, UI "Cargar más" funciona

### Scenario: Timeline click filtra search
Given mensajes en 2026-08-10 (10) y 2026-08-11 (15)
When `GET /api/timeline?granularity=day` → 2 buckets y click barra 08-11
Then search filtra `from=2026-08-11&to=2026-08-11` y muestra solo 15, total coherente, respeta timezone UTC

### Scenario: Graph click sin leak
Given effective graph `Sam --friend--> Alex` sin `plan_*`
When `GET /api/graph?format=json` y click nodo Alex
Then panel muestra `GET /api/search?participant=Alex` citas y corrections activas, edges sin `plan_` prefix

### Scenario: Graph fallback sin CDN
Given cytoscape bloqueado
When `GET /api/graph` 
Then UI muestra lista nodos/edges + stats sin crash

### Scenario: Wiki link + lint
Given `wiki/identity.md` con evidence tags
When `GET /api/wiki?slug=sample` luego `GET /api/wiki/identity.md?slug=sample`
Then HTML renderizado + evidence links a search + lint `{issues,warnings}`

### Scenario: Plans filtros
Given plans con status pending/scheduled
When `GET /api/plans?status=pending&participant=Alex` y `GET /api/plans/{id}`
Then lista filtrada y detail con transitions `proposed→pending`, location, source_ids

### Scenario: Ops + backup round-trip + delete
Given dataset healthy `sam`
When `POST /api/backup {slug:sam}` → zip, `POST /api/restore` zip, `GET /api/diagnose` healthy con mismo `sources.messages`; luego `DELETE /api/datasets/sam?confirm=sam`
Then `GET /api/datasets` no lista sam, `quarantine/deleted-sam-*` existe, delete sin confirm → 400

### Scenario: Hardening + copy humano
Given `lazo ui` con token `abc123`
When `POST /api/import/preview` sin `X-UI-Token` → 401 "token requerido"; `slug=../escape` → 422; file 21MB → 413; `POST /api/ask` con telemetry off → `logs` contiene `question_hash` no texto crudo; todos los errores muestran copy humano + raw colapsable
