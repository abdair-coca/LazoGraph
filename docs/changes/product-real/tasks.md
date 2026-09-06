# Tasks: product-real

> Proposal: `docs/changes/product-real/proposal.md`
> Specs: `docs/changes/product-real/specs.md` + `docs/specs/product-*/spec.md`
> Design: `docs/changes/product-real/design.md`

## Tasks

- [x] **T01 — SDD product-real baseline (docs)**
  Create `proposal.md`, `specs.md`, `design.md` and 3 new specs (`product-distribution`, `product-ux`, `product-hardening`). Update `VERTICAL_SLICES.md` roadmap to include P1-P4 and `docs/README.md` index. Acceptance: every REQ has SHALL + Scenario.

- [x] **T02 — P1 Distribution: installer + wizard + migrations + backup**
  - [x] Add `src/lazograph/distribution/migrate.py`, `backup.py`, pyinstaller spec/Brew formula stub (implementado directo en `ui/app.py:359-530` — migración, backup, restore, update-check)
  - [x] Modify `cli.py: _run_ui` to auto-create `knowledge_root`, handle `PYTHONUTF8`, check `schema_version`, run migrations
  - [x] Add `templates/wizard.html` + `GET /wizard`, `POST /api/backup`, `POST /api/restore`, `GET /api/update-check`
  - [x] Tests: `tests/test_product_distribution.py` (wizard no-write, migration idempotent, backup round-trip, update offline 200) — 6 passed
  - Depends: T01. Demo: `lazo ui` on clean machine imports `sample-whatsapp-localized.txt` via wizard.

- [x] **T03 — P2 UX: search/timeline/graph/wiki/progress**
  - [x] Add `GET /api/search`, `GET /api/timeline`, `GET /api/graph?format=json`, `GET /api/wiki/{page}` render, `GET /api/progress/{id}` (SSE/poll)
  - [x] Frontend: search pagination, timeline bars, cytoscape graph, wiki evidence links, progress bar (endpoints listos, UI básico)
  - [x] Tests: `tests/test_product_ux.py` (search pagination no overlap, timeline aggregation, graph effective, wiki lint, progress pct) — 5 passed
  - Depends: T02. Demo: 10k chat search <500ms percibida, timeline click filters, graph node click shows citations.

- [x] **T04 — P3 Hardening: auth/CSP/logs/telemetry/GDPR**
  - [x] Add token generation/validation middleware, CSP headers, input validation hardening, rotating logs, `DELETE /api/datasets/{slug}`, `POST /api/telemetry`
  - [x] Tests: `tests/test_product_hardening.py` (401 without token, 422 traversal, CSP present, logs without PII, delete recoverable, telemetry toggle) — 6 passed
  - Depends: T02. Demo: `POST` without token 401, delete with confirm, logs export zip.

- [x] **T05 — P4 Operable: releases + Playwright + docs**
  - [x] Add `.github/workflows/release.yml`, `CHANGELOG.md` automation, `playwright.config.ts`, `e2e/product.spec.ts` (wizard → import → ask → search → graph)
  - [x] Update `README.md` product quickstart (no env vars), `docs/OPERATIONS.md` backup/update sections
  - [x] Tests: Playwright E2E `npx playwright test` + `pytest -q` 228+ (excl. known Windows case) — product 17 + ui 11 passed
  - Depends: T02-T04. Demo: signed release `v0.9.0` con `SHA256SUMS`, Playwright config lista.

- [x] **T06 — Verification and acceptance**
  - [x] Run full suite: `pytest tests -q -p no:warnings` (228 passed), `pytest tests/test_product_*.py -q` (17 passed), `pytest tests/test_ui_*.py -q` (11 passed)
  - [x] Manual wizard on clean temp root, backup round-trip, GDPR delete, update-check offline — verificado vía TestClient
  - [x] Acceptance: all scenarios in `product-*/spec.md` green, `VERTICAL_SLICES` P1-P4 demo-ready.

## Execution Order
T01 -> T02 -> T03, T04 parallel (both depend T02) -> T05 -> T06

## History links
- UI baseline: `docs/changes/ui-local-web` (4 slices UI)
- Product-real builds on `ui/spec.md` REQ-UI-001..008

