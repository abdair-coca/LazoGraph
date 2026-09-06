# Proposal: ui-local-web

## Intent
Add local-first web UI that mirrors every CLI slice without duplicating domain logic. Single command `lazo ui` serves dashboard, import, ask, plans, graph, corrections, and ops on `http://localhost`. Offline by default, no external sync, no invented evidence.

## Scope
### In Scope
- FastAPI + Jinja + vanilla JS frontend served from `src/lazograph/ui`
- `lazo ui --host --port --no-browser` entry point reusing `features/*`, `config.py`, `domain/*`
- REST `GET /api/datasets`, `GET /api/diagnose`, `POST /api/import/preview|apply`, `POST /api/ask`, `GET /api/plans`, `GET /api/graph`, `GET /api/corrections`, `GET /api/wiki`
- Slicing: UI-1 shell/health → UI-2 import → UI-3 ask → UI-4 plans/graph/ops, each demo-ready with tests

### Out Of Scope
- Hosted sync, mobile app, Electron/Tauri, rewriting adapters/storage/graph/wiki
- New source formats beyond CLI coverage
- Auto-persisting suggestions as facts

## Capabilities
### New
- `ui-shell`: local server, dataset selector, diagnose metrics, smoke gate
- `ui-import`: web preview/apply with PII/equivalent guards and invariant check
- `ui-ask`: unified grounded QA (person/relationship/plan/suggestion/describe) with citations
- `ui-plans-graph`: read-only plans/graph/corrections/wiki + rebuild/quarantine ops

### Modified
- `pyproject.toml` adds `fastapi`, `uvicorn`, `jinja2`
- `lazograph/cli.py` adds `lazo ui` subcommand

## Approach
Reuse thin wrappers over existing services (`import_chat.service.build_preview`, `ask_person.service.answer_about_person`, `pending_plans.list_plans`, etc.). Frontend never parses raw sources; all validation stays server-side. Tests use `FastAPI TestClient` + disposable `OPENPERSONA_KNOWLEDGE` temp dirs + fake providers, mirroring `tests/test_ask_person.py`.

## Affected Areas
| Area | Impact |
|------|--------|
| `src/lazograph/ui/*` | New |
| `src/lazograph/cli.py` | Modified (ui subcommand) |
| `pyproject.toml` | Modified |
| `docs/specs/ui/spec.md` | New |
| `docs/changes/ui-local-web/*` | New |

## Risks
| Risk | Mitigation |
|------|------------|
| File upload path traversal | Reject `..`, resolve inside temp, never trust client path |
| Large chat blocks event loop | Run `build_preview`/`apply` in threadpool, cap upload 20MB |
| Port conflict | Fail fast with clear message, allow `--port` override |

## Rollback
`git revert` UI commits or `Remove-Item src/lazograph/ui -Recurse`; CLI remains functional. No dataset migration.

## Dependencies
- Existing `features/*` and `dataset_invariants`; `mempalace`, `tzdata` unchanged

## Success Criteria
- [ ] `lazo ui` boots, dashboard shows diagnose counts
- [ ] Import preview → apply → invariants pass, idempotent reimport
- [ ] Ask returns citations/confidence/abstention identical to CLI
- [ ] Plans/graph read-only, no mutation
- [ ] `pytest -q` passes including `tests/test_ui_*.py`
