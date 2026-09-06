# LazoGraph — Docs SDD

> Índice humano del proyecto. Specs formales en `specs/` (inglés, SHALL). Historial en `changes/` (inglés). Esta guía en español rioplatense para entender rápido.

## Qué es
LazoGraph convierte datos de vida privados en cuatro capas: memoria semántica verbatim (ChromaDB), identidad canónica de participantes, grafo de entidades/relaciones (SQLite) y wiki con evidencia + export para training. Local-first, determinista donde puede, con respuestas fundadas y citadas.

```
Raw life data
  -> adapters/universal|chat_export|social  -> normalized messages
  -> sender boundary -> persona resolution -> PII scan -> equivalent preflight -> dedup
  -> sources/*.jsonl -> ChromaDB + participants.json + KG + plans/projection.json -> wiki/*.md -> export
```

Ver detalle: `ARCHITECTURE.md`, `OPERATIONS.md`.

## Slices (estado real Accepted)
| # | Capacidad | Comando | Estado | Spec |
|---|-----------|---------|--------|------|
| 1 | Import Chat | `lazo import --dry-run / --apply` | Accepted 2026-08-08 `c6d90eb` | `specs/import-chat/spec.md` |
| 2 | Ask About a Person | `lazo ask --about` | Accepted 2026-08-08 `532e95e` | `specs/ask-person/spec.md` |
| 3 | Add Manual Context | `lazo context --dry-run/--apply` | Accepted 2026-08-09 `334bd4d` | `specs/add-context/spec.md` |
| 4 | Correct Knowledge | `lazo correct --dry-run/--apply` | Accepted 2026-08-10 `e36dcc1` | `specs/correct-knowledge/spec.md` |
| 5 | Ask About Relationships | `lazo ask` sin `--about` (2 personas) | Accepted 2026-08-13 `5f8183e` | `specs/ask-relationship/spec.md` |
| 6 | Pending Plans | `lazo plans list|show`, ask pending | Accepted 2026-08-23 `79f5400` | `specs/pending-plans/spec.md` |
| 7 | Grounded Suggestions | `lazo ask "What could I give ...?"` | Accepted 2026-08-23 `be9df6c` | `specs/grounded-suggestions/spec.md` |
| 8 | Describe a Relationship | `lazo ask "How would you describe ...?"` | Accepted 2026-08-23 worktree | `specs/describe-relationship/spec.md` |

Cross-cutting: `specs/architecture/spec.md` (invariantes, privacy, transacciones), `specs/operations/spec.md` (rebuild atomico, diagnose, smoke, quarantine), `specs/source-formats/spec.md`, `specs/wiki-schema/spec.md`.
UI: `specs/ui/spec.md` (local web `lazo ui` — Accepted 2026-09-02, `src/lazograph/ui`).

## Producto real (próxima etapa)
| # | Capacidad | Estado | Spec |
|---|-----------|--------|------|
| P1 | Distribución (installer, wizard, backup, migrations) | Planned | `specs/product-distribution/spec.md` + `changes/product-real/proposal.md` |
| P2 | UX (search, timeline, graph-viz, wiki, progress) | Planned | `specs/product-ux/spec.md` |
| P3 | Hardening (auth local, CSP, logs, telemetry, GDPR) | Planned | `specs/product-hardening/spec.md` |
| P4 | Operable (releases firmados, Playwright) | Planned | `changes/product-real/tasks.md` T05 |

Ver `changes/product-real/{proposal,specs,design,tasks}.md` para intent, arquitectura delta y slicing P1→P4. Cada P requiere `Slice P-N accepted` antes de siguiente.

## Cómo leer esto
- **Para usar LazoGraph:** empezá por `OPERATIONS.md` (checklist primer import, rebuild, diagnose).
- **Para entender el dominio:** `ARCHITECTURE.md` + `specs/architecture/spec.md`.
- **Para implementar una feature:** `changes/<feature>/proposal.md` -> `specs.md` -> `tasks.md` -> `specs/*/spec.md` (requirements SHALL + scenarios).

## Estructura SDD (custom)
Este proyecto usa `docs/` como root SDD (no `openspec/` default) por tu pedido. Decisión documentada en `changes/docs-sdd-baseline/proposal.md`.

```
docs/
  README.md               # este índice (ES)
  ARCHITECTURE.md         # narrativa arquitectura (fuente)
  OPERATIONS.md           # workflows operativos (fuente)
  VERTICAL_SLICES.md     # roadmap 8 slices (fuente)
  specs/*/spec.md         # 12 specs formales (EN, SHALL, traced)
  changes/<feature>/
    proposal.md           # intent/scope/approach <450w (EN)
    specs.md              # New/Modified capabilities
    tasks.md              # tasks trazables + commits historia
```

Historial: `changes/` queda para siempre. En nueva versión se reorganiza `README` y `specs` pero no se borra `changes/`.

## Hybrid con Engram (ahorro tokens LLM)
Filesystem es source of truth. Engram guarda espejos `sdd/docs-sdd-baseline/proposal|specs|tasks` y `sdd/lazograph/testing-capabilities` para retrieval rápido sin leer 1000 líneas. Si Engram no está disponible, filesystem alcanza.

Idioma: specs/proposal/tasks en inglés (contract SDD). Índice humano y comentarios en español.

## Siguiente cambio
Nuevo feature: crear `docs/changes/<kebab>/proposal.md + specs.md + tasks.md` y actualizar `specs/*/spec.md` correspondiente. No tocar `ARCHITECTURE.md`/`VERTICAL_SLICES.md` salvo que el slice lo exija con migración testeada.

## Referencias rápidas
- Fuente formatos: `references/source-formats.md` + `specs/source-formats/spec.md`
- Wiki schema: `references/wiki-schema.md` + `specs/wiki-schema/spec.md`
- Invariantes: `scripts/dataset_invariants.py` + `specs/architecture/spec.md`
