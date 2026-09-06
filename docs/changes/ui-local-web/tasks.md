# Tasks: ui-local-web

> Proposal: `docs/changes/ui-local-web/proposal.md`
> Spec: `docs/specs/ui/spec.md`
> Design: `docs/changes/ui-local-web/design.md`

## Tasks

- [x] **T01 — SDD baseline (docs)**
  Create `proposal.md`, `spec.md`, `design.md`, `specs.md` under `docs/changes/ui-local-web` + `docs/specs/ui/spec.md`. Acceptance: REQ-UI-001..008 with scenarios.

- [x] **T02 — UI-1 foundation**
  Add `fastapi`, `uvicorn`, `jinja2` to `pyproject.toml`; create `src/lazograph/ui/app.py`, `templates/base.html`, `static/*`; add `lazo ui` subcommand in `cli.py`. Endpoints: `GET /`, `GET /api/datasets`, `GET /api/diagnose`, `GET /api/health`. Tests: `tests/test_ui_shell.py` (TestClient). Demo: `lazo ui --port 8765` → dashboard shows counts.

- [x] **T03 — UI-2 import**
  Implement `POST /api/import/preview` + `POST /api/import/apply` + temp token store + threadpool. Tests: `tests/test_ui_import.py` (preview never writes, equivalent guard, idempotent apply). Depends: T02. Demo: upload `tests/fixtures/sample-whatsapp-localized.txt`.

- [x] **T04 — UI-3 ask**
  Implement `POST /api/ask` unified router mirroring `cli._run_ask` + provider selection. Frontend ask card with citations. Tests: `tests/test_ui_ask.py` (alias isolation, abstention, citation validation). Depends: T02. Demo: `POST /api/ask` vs CLI parity.

- [x] **T05 — UI-4 plans/graph/corrections/ops**
  Implement `GET /api/plans`, `/api/plans/{id}`, `/api/graph/*`, `/api/corrections`, `/api/wiki`, plus nav tabs. Tests: `tests/test_ui_plans_graph.py`. Depends: T02. Demo: list pending plans, show graph path.

- [x] **T06 — Verification**
  Run `pytest -q` full suite (expect pass), manual `lazo ui` smoke, `diagnose.py` + `smoke_test.py` post-import. Acceptance: all scenarios in `docs/specs/ui/spec.md` green. 228 passed.

## Execution Order
T01 -> T02 -> T03,T04 parallel (both depend T02) -> T05 -> T06
