# Design: product-real

## Context
MVP current is technically correct but not product. User must set `PYTHONUTF8`, `OPENPERSONA_KNOWLEDGE`, `pip install -e .`, and read docs. UI shell is minimal, no search pagination, no graph viz, no auth. Need to slice to product without rewriting `adapters`/`domain`/`scripts`.

## Decisions

### Distribution
- PyInstaller standalone (`lazo` binary) + `pipx` package + `Dockerfile` local (all from same `pyproject.toml`). `lazo ui` auto-creates `knowledge_root` and handles `PYTHONUTF8` via `scripts/runtime.configure_safe_output()`. Version from `pyproject.toml` + git commit short in `--version`.
- Migrations: `src/lazograph/distribution/migrate.py` checks `dataset.json:schema_version`, runs idempotent steps, snapshots before write under `knowledge_root/.migrations/backup-{ts}.zip`.

### UX
- Wizard: `templates/wizard.html` (3 steps) reusing `POST /api/import/preview|apply` existing flow; empty state replaces dashboard when `GET /api/datasets` empty.
- Search: new `GET /api/search` wraps `ports/memory.py` with `limit/offset` + `total` via count query; timeline aggregates `sources/*.jsonl` in memory (stream, no DB change).
- Graph viz: `GET /api/graph?format=json|cytoscape` returns effective graph; frontend uses lightweight `cytoscape.js` or SVG (no heavy React). Wiki uses `markdown` lib server-side with evidence link rewriting.

### Hardening
- Token: on `lazo ui` start, `secrets.token_urlsafe(32)` → write `knowledge_root/.ui-token` 0600, require `X-UI-Token` for POST. `127.0.0.1` default, `0.0.0.0` needs `--allow-remote` flag.
- CSP: `Starlette middleware` adds `Content-Security-Policy`, `X-Frame-Options: DENY`.
- Logs: `logging.handlers.RotatingFileHandler` to `logs/lazograph.log`; diagnose export zips without messages.

## Alternatives
| Alt | Rejected why |
|-----|--------------|
| Electron/Tauri for P1 | Bundle 200MB+, breaks single Python toolchain, defer to P2 if needed |
| React SPA + Vite | Node heavier, not needed for wizard/search; keep Jinja + fetch, add `cytoscape` only for graph |
| Hosted sync now | Violates local-first promise, requires auth infra, defer past P4 |

## Architecture delta
```
lazo ui (cli.py) -> distribution/migrate -> ui/app.py (auth middleware, CSP, logs)
                                      -> /api/search,timeline,graph,wiki,backup,telemetry,update-check
                                      -> wizard.html + viz.js
lazo backup/restore -> distribution/backup.py (zip, .rebuild.lock)
```

## Testing
- Unit: REQ-PD-003 migration with old fixture; REQ-PH-001 token 401; REQ-PUX-002 pagination.
- Integration: TestClient wizard flow temp knowledge, backup round-trip, diagnose export.
- E2E: Playwright (Chromium) wizard import → ask → search → graph click, all offline.

## Rollout (gated slices)
- P1 Distribution: installer + wizard + migrations + backup (demo: fresh laptop install)
- P2 UX: search/timeline/graph/wiki/progress (demo: 10k chat)
- P3 Hardening: auth/CSP/logs/telemetry/GDPR (demo: token + delete)
- P4 Operable: releases + Playwright + docs + feedback (demo: signed release)
Each slice needs `Slice P-N accepted` before next.
