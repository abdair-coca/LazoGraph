# Tasks: product-polish

> Spec: `docs/specs/product-polish/spec.md` | Design: `docs/changes/product-polish/design.md`
> Mode: single spec, 4 vertical slices A-D

## Slice A — Import polido (REQ-PP-001, PP-011 parcial, PP-010 parcial)

- [x] **A1** Fix `ui/app.py:139` import preview/apply: keep `_PREVIEWS` token, wire `allow/reconcile_equivalent_source` flags to UI, validate slug/file size, return human `detail` ES.
- [x] **A2** Add `GET /api/progress/{job_id}` real tracking (in-memory `_JOBS` updated per 128 batch, or stub increment) + wire `app.js` polling bar.
- [x] **A3** Fix `templates/base.html:80` + `wizard.html:30` ids únicos, add duplicate `import-form` handler that works for both pages, progress bar element.
- [x] **A4** Update `static/app.js:30` import flow: render preview human (participants badges, PII, equivalent warning), disable button during apply, show progress pct/eta, handle 401/413/422 with copy humano.
- [x] **A5** Tests: extend `tests/test_ui_import.py` (preview human, progress polling, equivalent guard, 20MB, slug traversal) + manual `POST /api/import/preview` with `sample-whatsapp-localized.txt`.

## Slice B — Ask interpretado (REQ-PP-002, PP-011)

- [x] **B1** Update `static/app.js:48` `ask-form` handler: split `renderAsk(j)` into cards Text/Facts/Inferences/Suggestions/Missing + confidence badge + retrieval_summary debug toggle + citations clickable → `search?participant=`.
- [x] **B2** Handle abstención: if `j.citations=[]` or `confidence<0.4` show human copy "No encontré evidencia suficiente — probá con ..." + suggested queries, no stack.
- [x] **B3** Add UI routing hint: placeholder examples + `about` auto-suggest from `GET /api/datasets` participants.
- [x] **B4** Tests: `tests/test_ui_ask.py` fake provider, verify facts/inferences separation, citations existence, abstención, no leak; plus `test_ask_person` regression.

## Slice C — Explorar (REQ-PP-003, PP-004, PP-005, PP-006)

- [x] **C1** Fix `static/app.js:65` search: add `from/to` filter state from timeline, virtualized list or pagination correct, human empty state, `has_more` check.
- [x] **C2** Fix `static/app.js:87` timeline: `GET /api/timeline?granularity=day` buckets render + click sets `searchFrom/To = b.date` + `document.querySelector('[data-tab=search]').click()` + `doSearch(true)` with date params.
- [x] **C3** Fix `static/app.js:113` graph: inject `GET /api/graph?format=json`, filter `plan_*` edges, `cytoscape` CDN fallback to list + `GET /api/graph/stats`, click node → `GET /api/search?participant=id` panel sin leak.
- [x] **C4** Fix `templates/base.html:157` wiki: add `id="wiki-load"` + `id="wiki-content"` handler, ensure `GET /api/wiki` lint badge `issues/warnings` visible, `GET /api/wiki/{page}` evidence tags link.
- [x] **C5** Populate `static/app.js:14` `loadDiagnose()` KPIs `kpi-messages/personas/graph` from diagnose `sources.messages` etc.
- [x] **C6** Tests: `tests/test_product_ux.py` must pass `test_search_pagination`, `test_timeline_aggregation`, `test_graph_json`, `test_wiki_render` after fixes.

## Slice D — Operar (REQ-PP-007, PP-008, PP-009, PP-010 resto)

- [x] **D1** Plans tab: `static/app.js:58` add filters `status` select + `participant` input + `show` detail modal with transitions `proposed→pending...`, reuse `GET /api/plans`.
- [x] **D2** Ops tab: `templates/base.html:166` add buttons `Backup`, `Restore` (file input), `Delete dataset` (confirm=slug modal), `Telemetry toggle`, `Logs tail`, `Update check` badge; wire `app.js` fetch handlers with human copy.
- [x] **D3** Harden `ui/app.py:60` ensure `X-UI-Token` 401 copy humano, `validate_slug` 422, `413 file too large`, CSP header `app.py:91` verified, logs `question_hash` not raw when telemetry off.
- [x] **D4** E2E `e2e/product.spec.ts:3` ampliar a 9 flujos: wizard→import→ask→search paginado→timeline click→graph click→plans filter→wiki→backup/restore→delete; run `npx playwright test`.
- [x] **D5** Final verify: `pytest tests -q -p no:warnings` (excl. known Windows Chroma heavy) + `python scripts/diagnose.py --slug sample` healthy + invariants `unique messages = vectors = KG`.

## Global

- [x] Update `docs/OPERATIONS.md:397` with backup/restore/delete flows verification.
- [x] Add `CHANGELOG.md` entry for `product-polish`.
- [x] Demo script: one-command `lazo ui` → wizard → ask → timeline → graph without docs.
