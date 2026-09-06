# Spec: product-hardening

> Source: `docs/ARCHITECTURE.md:278-284`, `src/lazograph/ui/app.py:94-180`, `docs/specs/ui/spec.md:28-30`, `src/lazograph/infrastructure/llm/*`
> Change: `docs/changes/product-real`

Resumen ES: Endurecer UI local para uso diario real sin exponer datos ni frustrar.

## Requirements

### REQ-PH-001: Local auth and scope
`lazo ui` SHALL bind `127.0.0.1` only by default (`--host 0.0.0.0` requires explicit flag + warning). On startup SHALL generate ephemero `LAZOGRAPH_UI_TOKEN` (uuid) printed to stdout and SHALL require `X-UI-Token: <token>` for any `POST /api/*` (GET read-only allowed). Token file SHALL live under `knowledge_root/.ui-token` with `0600` perms and expiry 24h.

### REQ-PH-002: Input validation and CSP
Server SHALL validate `slug` via `config.py:27` regex, reject `..`, cap `file` 20MB (`413`), sanitize wiki HTML (allowlist, escape script), and send `Content-Security-Policy: default-src 'self'; script-src 'self'; connect-src 'self'`. SHALL NOT reflect `OPENPERSONA_KNOWLEDGE` path in responses (only `slug`).

### REQ-PH-003: Structured logs and diagnose export
Logs SHALL go to `${knowledge_root}/logs/lazograph.log` (rotating 5MB, 3 files) with `{ts, level, route, slug, elapsed_ms, error}`. `GET /api/diagnose?slug&download=1` SHALL return zip with `diagnose.json` + `logs tail 1000` (no private messages). `POST /api/ask` SHALL log `question_hash` not raw question when telemetry off.

### REQ-PH-004: Opt-in telemetry
Telemetry SHALL be `off` by default. `POST /api/telemetry {enabled:bool}` persists to `${knowledge_root}/config.json`. When `off`, system SHALL NOT send network data except `update-check` (explicit). When `on`, SHALL send only anonymous counts `{datasets, messages, vectors, errors}` no content, with 30s timeout and failure silent.

### REQ-PH-005: GDPR delete and encryption at rest
`DELETE /api/datasets/{slug}` SHALL require `confirm=slug` param, SHALL move dataset to `quarantine/deleted-{slug}-{ts}` (recoverable 30d) then `rm` after confirm, SHALL log deletion. Optional `lazo init --encrypt` SHALL set `dataset.json:encrypted=true` and document that content at rest is not yet fully encrypted (roadmap), failing closed if `--encrypt` requested without support.

## Scenarios

### Scenario: Token required
Given `lazo ui` running with token `abc123`
When `POST /api/import/preview` without `X-UI-Token`
Then 401 `missing token`, no file created

### Scenario: Path traversal blocked
Given `POST /api/import/preview` with `slug=../escape`
When preview called
Then 422 `invalid slug` per `config.py:27`, no file outside `knowledge_root`

### Scenario: Logs without PII
Given `POST /api/ask` with telemetry off
When inspecting `logs/lazograph.log`
Then contains `question_hash=sha256:abc...` not raw “¿Qué le gusta a Alex?”

### Scenario: Delete recoverable
Given dataset `sam` exists
When `DELETE /api/datasets/sam?confirm=sam`
Then `GET /api/datasets` no longer lists `sam`, `quarantine/deleted-sam-...` exists, second delete without confirm 400
