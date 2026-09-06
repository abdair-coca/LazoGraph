# Spec: product-distribution

> Source: `docs/ARCHITECTURE.md:278-284`, `docs/OPERATIONS.md:3-15`, `pyproject.toml:1-46`, `src/lazograph/ui/app.py:45-92`
> Change: `docs/changes/product-real`

Resumen ES: Hacer LazoGraph instalable, actualizable y portable sin que el usuario configure entorno.

## Requirements

### REQ-PD-001: One-command install
System SHALL provide at least `pipx install lazograph` and a native executable (`lazo.exe`/`lazo` via PyInstaller or briefcase) that runs without manual `python -m venv`, `PYTHONUTF8` or `OPENPERSONA_KNOWLEDGE` setup. SHALL auto-create `knowledge_root` under `LOCALAPPDATA/LazoGraph` (Windows) or `~/.local/share/LazoGraph` (macOS/Linux) if env var absent, per `config.py:14-20` fallback.

### REQ-PD-002: First-run wizard (non-mutating preview)
`GET /` when no dataset exists SHALL render wizard: 1) elige archivo, 2) `POST /api/import/preview` muestra adapter/participantes/PII/equivalent, 3) confirma persona, 4) `POST /api/import/apply` + `diagnose` success. Wizard SHALL NOT write until confirm, idéntico a `REQ-UI-003`.

### REQ-PD-003: Versioned dataset migrations
`dataset.json` SHALL include `schema_version` (semver). On startup, system SHALL detect older `schema_version`, run idempotent migrations (tests: old fixture `schema_version=0.7` migrates to `0.8.0` without data loss), and SHALL backup `dataset.json` + `participants.json` before migrate. SHALL fail closed with human ES error if downgrade attempted.

### REQ-PD-004: Backup and restore (UI + CLI)
System SHALL expose `POST /api/backup` (zip of `${slug}/` filtered: excludes `.mempalace/chroma.sqlite3` lock) and `POST /api/restore` (validate zip, check `schema_version`, restore atomically via `.rebuild.lock` snapshot per `ARCHITECTURE.md:238-249`). CLI `lazo backup --slug sam --output sam.zip` and `lazo restore sam.zip` SHALL reuse same logic.

### REQ-PD-005: Signed releases and update check
Each release SHALL publish `SHA256SUMS` + `CHANGELOG.md` entry. `GET /api/update-check` SHALL fetch latest GitHub release tag (timeout 3s, offline fallback) and return `{current, latest, update_available}` without blocking UI. `lazo --version` SHALL print `0.8.0` + commit short.

## Scenarios

### Scenario: Fresh install no env
Given clean Windows without env vars
When running `lazo ui` from executable
Then `knowledge_root` auto-creates at `%LOCALAPPDATA%\LazoGraph\knowledge`, wizard shows, no `PYTHONUTF8` error

### Scenario: Migration
Given dataset `schema_version=0.7` with 100 messages
When opening dashboard after upgrade to `0.8.0`
Then backup created at `backups/2026-09-02T...zip`, `schema_version` bumped, `diagnose` healthy

### Scenario: Backup round-trip
Given healthy dataset `sam`
When `POST /api/backup {"slug":"sam"}` then `POST /api/restore` with same zip
Then `diagnose` healthy and `sources` count identical

### Scenario: Update offline
Given no network
When `GET /api/update-check`
Then returns `update_available: false` with `warning: offline` in 200, UI shows “sin conexión”
