# Specs: product-real

> Proposal: `docs/changes/product-real/proposal.md`
> Mode: filesystem `docs/` + Engram `sdd/product-real/*`

## Summary
Product-real extends baseline (8 slices + ui-local-web) into distributable, usable, hardened product. Additive only; preserves `adapters`, `domain/*`, dataset layout. Each new spec traced to `ARCHITECTURE.md` or `OPERATIONS.md`.

## New Specs
| Spec | Path | Source | Key Coverage |
|------|------|--------|--------------|
| product-distribution | `docs/specs/product-distribution/spec.md` | ARCH 278-284, OPERATIONS 3-15, pyproject 1-46 | installer, wizard, migrations, backup/restore, signed releases |
| product-ux | `docs/specs/product-ux/spec.md` | mockup 1-709, ui/spec 32-34, domain/answer 10-63 | human states, search pagination, timeline, graph-viz, wiki render, progress |
| product-hardening | `docs/specs/product-hardening/spec.md` | ARCH 278-284, ui/app 94-180 | local auth, CSP/validation, logs, telemetry, GDPR delete |

## Modified Specs
| Spec | Delta |
|------|-------|
| `ui` | Hardens `lazo ui` (adds REQ-UI-009 auth, REQ-UI-010 CSP, wizard REQ-UI-011) — backward compat for GET read-only |
| `architecture` | Adds distribution invariants (schema_version, backup) and operational logs |
| `operations` | Adds backup/restore and update-check workflows |

## Traceability
Every REQ cites `file:line`. Scenarios mirror `tests/test_ui_*.py` and `scripts/diagnose.py` patterns.

## Out of Scope for Specs Phase
Code, `openspec/` creation, rewriting narrative docs, hosted sync, mobile.

