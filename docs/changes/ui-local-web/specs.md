# Specs: ui-local-web

> Proposal: `docs/changes/ui-local-web/proposal.md`
> Mode: filesystem `docs/` + Engram `sdd/ui-local-web/*`

## Summary
New UI capability sliced into 4 incremental deliverables reusing all existing domain services. Additive only; no storage migration.

## New Specs
| Spec | Path | Source | Key Coverage |
|------|------|--------|--------------|
| ui | `docs/specs/ui/spec.md` | VERTICAL_SLICES 8 slices, ARCH 38-284, cli.py 60-638 | local server, datasets/diagnose, import preview/apply, unified ask, plans/graph read-only, privacy, simple shell |

## Modified Specs
None. Future UI slices SHALL add delta REQ-UI-00x with `Modified` entry.

## Traceability
Each REQ cites `file:line` of CLI/domain source. Scenarios mirror `tests/test_lazo_import.py` and `tests/test_ask_person.py`.
