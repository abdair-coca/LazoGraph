# Proposal: product-polish

## Intent

Convert current LazoGraph UI (shell + 8 slices + product-real P1-P3 parcial) into **producto cerrado para cualquiera**: todos los botones responden, respuestas se interpretan en secciones citadas y se entienden sin docs, cada flujo vertical funciona y queda verificado. Resolver fricciones detectadas en `ui/app.py:60-853`, `templates/base.html:12-186`, `static/app.js:1-156` durante discovery 2026-09-02.

## Scope

### In Scope
- Spec única consolidada `docs/specs/product-polish/spec.md` (11 REQs: 9 flujos + 2 transversales) que referencia `ARCHITECTURE.md:37-79`, `OPERATIONS.md:397-433`, `domain/answer.py:10-63`.
- Fix botones muertos/rotos: KPIs dashboard, timeline click→search, wiki-load id, graph fallback, planes filtros, ops backup/restore/delete/telemetry, wizard ids duplicados.
- Render Ask seccionado `facts/inferences/suggestions/missing + citations clickeables + confidence + abstención humana ES`.
- Human states ES para empty/loading/error + logs técnicos separados `REQ-PUX-001`.
- 4 slices verticales dentro de 1 spec (A Import, B Ask, C Explore, D Operate) con demo y tests cada uno.
- Playwright E2E ampliado de `e2e/product.spec.ts:3` a 9 flujos.

### Out of Scope
- Reescribir `adapters/`, `domain/*`, `scripts/ingest`, `infrastructure/chroma/sqlite`, dataset layout `${OPENPERSONA_KNOWLEDGE}/{slug}/`.
- Sync multi-device, mobile nativa, hosted LLM por defecto, calendario/mensajería automática.
- Nueva infraestructura de distribución (PyInstaller ya en product-real); solo pulido UI.

## Capabilities

### New Capabilities
- `product-polish`: spec única que cierra todos los flujos UI (import, ask, search, timeline, graph, wiki, plans, ops, hardening) con respuestas interpretadas y copy humano.

### Modified Capabilities
- `product-ux`: precisa timeline click filter, graph fallback, search virtualización, wiki link evidence.
- `product-hardening`: precisa token scope, CSP, logs sin PII, GDPR confirm.
- `product-distribution`: precisa backup/restore UI y wizard idempotent.
- `ui`: corrige ids muertos (`wiki-load`, `kpi-*`, `backup/delete`) y añade progress polling.
- `operations`: añade verificación por flujo.

## Approach

Slicing vertical incremental sobre base existente. Cada slice toca thin wrapper `ui/app.py` + `templates` + `static` + tests `TestClient`. Reusa servicios `build_preview`, `answer_*`, `diagnose`, `list_plans`, `query_kg`. Mantiene `scripts/*.py` compatibles y layout privado fuera de Git. Spec única da contrato; implementación por slices A→D con gating `Slice P-polish-X accepted`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `docs/specs/product-polish/spec.md` | New | 11 REQs + 11 scenarios verificables |
| `docs/changes/product-polish/*` | New | proposal/spec/design/tasks |
| `src/lazograph/ui/app.py` | Modified | progress job_id, timeline params, wiki page, backup/restore/delete UI wiring, KPIs |
| `src/lazograph/ui/templates/base.html` | Modified | fix ids, add backup/delete/telemetry buttons |
| `src/lazograph/ui/templates/wizard.html` | Modified | ids únicos, progress bar |
| `src/lazograph/ui/static/app.js` | Modified | renderAsk seccionado, search virtualized, timeline filter, graph fallback, human states |
| `src/lazograph/ui/static/style.css` | Modified | toasts/errors humanos |
| `tests/test_product_ux.py` etc | Modified | ampliar fixtures por flujo |
| `e2e/product.spec.ts` | Modified | 9 flujos E2E |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Scope creep (querer todo) | High | 1 spec / 4 slices gated, demo antes de siguiente |
| CDN cytoscape falla | Medium | Fallback lista + stats sin JS |
| Chroma/ONNX memoria Windows | Medium | Tests excluyen `test_correct_knowledge` pesado, documentar `minilm` fallback |
| Falsa seguridad local | Low | CSP, token, validación slug/20MB, no exponer paths |

## Rollback Plan

`git revert` por slice; cada slice preserva layout y CLI. Spec es aditiva, revierte sin migración destructiva. Backup `dataset.json` antes de cualquier cambio de schema.

## Dependencies

- 8 slices aceptados + `product-real` P1-P3 parcial presente. Python 3.11+, `fastapi`, `mempalace`, `tzdata` en `pyproject.toml:11-18`.

## Success Criteria

- [ ] Los 9 tabs responden con copy humano ES y sin stack en UI
- [ ] Ask renderiza facts/inferences/suggestions/missing + citations clickeables + abstención
- [ ] Timeline click filtra search por día con timezone `dataset.json:timezone`
- [ ] Graph excluye `plan_*` y fallback funciona sin CDN
- [ ] Backup→restore round-trip diagnose healthy
- [ ] `pytest tests -q` y `playwright test e2e/product.spec.ts` pasan para 9 flujos
