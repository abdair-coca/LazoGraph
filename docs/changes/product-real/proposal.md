# Proposal: product-real

## Intent
Convert LazoGraph from a technical local-first MVP (8 accepted slices + `lazo ui` shell) into a **distributable, usable, and operable product** that a non-technical user can install, onboard, use daily, and trust with private data without reading docs. Preserve local-first, deterministic, and privacy guarantees.

## Scope
### In Scope
- **P1 Distributable**: one-command install for Windows/macOS/Linux. `lazo` as native executable (PyInstaller/briefcase) + `pipx` + Docker local. Auto-detect `OPENPERSONA_KNOWLEDGE`, handle `PYTHONUTF8`, versioned `dataset.json` migrations, backup/restore UI, signed releases.
- **P2 Usable**: first-run wizard (elige chat → preview → confirma persona → éxito), empty states, errores humanos ES, búsqueda/filtros, timeline, grafo interactivo, wiki renderizada, paginación para chats >10k, progreso/ETA.
- **P3 Hardening**: local auth (token por sesión para `lazo ui` en `127.0.0.1`), CSP/sanitización, validación estricta (slug, 20MB cap, path traversal), logs estructurados, export de diagnóstico 1-click, opt-in telemetría anónima, GDPR borrar dataset, cifrado en reposo opcional.
- **P4 Operable**: CI releases firmados, auto-update check, E2E Playwright, carga con chat grande, docs de producto y canal de feedback.

### Out of Scope
- Sync multi-dispositivo/hosted, mobile nativa, reescribir adapters/storage/graph/wiki, LLM hosted por defecto, integración calendario/mensajería automática, scoring psicológico.

## Capabilities
### New
- `product-distribution`: installer, wizard, backup/restore, migrations
- `product-ux`: search, timeline, graph-viz, wiki, pagination, onboarding
- `product-hardening`: auth local, CSP, logs, telemetry, GDPR, encryption

### Modified
- `ui`: hardens `lazo ui` (auth, CORS, CSP), adds wizard and full UX flows
- `architecture`: adds distribution and operational invariants
- `operations`: adds backup/restore and update workflows

## Approach
Slice incremental sobre base existente. Ningún slice reescribe `adapters`, `scripts/ingest`, `domain/*`. Cada slice reutiliza servicios (`build_preview`, `answer_*`, `diagnose`) y añade thin wrappers con validación y tests `TestClient`/`Playwright`. Mantener `scripts/*.py` wrappers y `OPENPERSONA_KNOWLEDGE` layout.

## Affected Areas
| Area | Impact |
|------|--------|
| `src/lazograph/ui/*` | Modified + New (auth, wizard, search, graph-viz) |
| `src/lazograph/distribution/*` | New |
| `scripts/*` | Modified (migrations, backup) |
| `docs/specs/product-*/spec.md` | New |
| `docs/changes/product-real/*` | New |
| `pyproject.toml` | Modified (packaging deps) |
| `README.md`, `VERTICAL_SLICES.md` | Modified (product roadmap) |

## Risks
| Risk | Likelihood | Mitigation |
|------|------------|------------|
| PyInstaller bundle 1GB+ with ONNX | Medium | Lazy download embedding, shared `~/.cache`, document 300MB first-run |
| Windows Chroma/ONNX memory | Medium | Already mitigado, tests excluyen `test_correct_knowledge` on constrained CI; document fallback `minilm` |
| Scope creep (querer todo) | High | Gating por slices, demo + `Slice P-N accepted` antes de siguiente |
| Falsa sensación de seguridad local | Medium | CSP, token, auditoría de inputs, nunca exponer `OPENPERSONA_KNOWLEDGE` path |

## Rollback
`git revert` de cada slice; cada slice preserva CLI y dataset layout. No migraciones destructivas sin backup.

## Dependencies
- Base 8 slices + `ui-local-web` (presente). Python 3.11+, `mempalace`, `tzdata`, `fastapi` ya en `pyproject.toml:11-18`.

## Success Criteria
- [ ] Instalación doble-click/1 comando en Windows y macOS sin configurar env vars
- [ ] Wizard importa `tests/fixtures/sample-whatsapp-localized.txt` sin leer docs
- [ ] UI maneja 10k mensajes con paginación y búsqueda <500ms percibida
- [ ] Auth local, logs y GDPR delete operativos
- [ ] `pytest tests -q -p no:warnings` (excluyendo caso Windows conocido) y Playwright E2E pasan
- [ ] Release firmado con notas y canal de feedback
