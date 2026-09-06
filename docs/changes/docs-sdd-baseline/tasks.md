# Tasks: docs-sdd-baseline

> Proposal: `docs/changes/docs-sdd-baseline/proposal.md`
> Specs: `docs/changes/docs-sdd-baseline/specs.md` + `docs/specs/*/spec.md`
> Mode: docs-only, no code, hybrid Engram `sdd/docs-sdd-baseline/*`

## History & Acceptance Links
| Slice | Commit | Date | Test Signal |
|-------|--------|------|-------------|
| 1 Import Chat | `c6d90eb` | 2026-08-08 | 121 tests, localized fixture |
| 2 Ask Person | `532e95e` | 2026-08-08 | 138 tests, grounded + abstention |
| 3 Add Context | `334bd4d` | 2026-08-09 | 151 tests, idempotency E2E |
| 4 Correct Knowledge | `e36dcc1` | 2026-08-10 | 177 tests, ledger + rebuild |
| 5 Ask Relationship | `5f8183e` | 2026-08-13 | 194 tests, path + temporal |
| 6 Pending Plans | `79f5400,41f2d70,c2cb4a8,66f9e9b` | 2026-08-23 | 212 tests (51 focused) |
| 7 Grounded Suggestions | `be9df6c` | 2026-08-23 | 227 tests (13 focused) |
| 8 Describe Relationship | worktree | 2026-08-23 | 7 focused + 63 regression |

## Tasks

### T01 — Refresh .atl/skill-registry.md
Update timestamp to 2026-08-31, keep contract. Verify no code change.
Owner: baseline. Status: done.

### T02 — Create docs/specs/ structure + proposal baseline
Create `docs/specs/*` dirs and `docs/changes/docs-sdd-baseline/proposal.md` <450 words EN.
Depends: T01. Status: done.

### T03 — Spec: import-chat
Write `docs/specs/import-chat/spec.md` with REQ-IC-001..005 and 4 scenarios, traced to VERTICAL_SLICES:205-298.
Acceptance: `lazo import --dry-run` behavior specified.

### T04 — Spec: ask-person + add-context
Write `docs/specs/ask-person/spec.md`, `docs/specs/add-context/spec.md`.
Acceptance: alias isolation + confidence 1.0/0.75/0.5 defined.

### T05 — Spec: correct-knowledge + ask-relationship
Write both specs with effective graph projection and facts/inferences split.
Acceptance: ledger append-only + participant_in excluded.

### T06 — Spec: pending-plans + grounded-suggestions + describe-relationship
Write 3 specs covering lifecycle IANA timezone, suggestion isolation, time-bounded description.
Acceptance: `unresolved` handling + no silent persistence.

### T07 — Spec: architecture + operations
Write cross-cutting specs with invariants `unique == total == participants sum == vectors` and atomic rebuild `.rebuild.lock`.
Acceptance: invariants reference `scripts/dataset_invariants.py`.

### T08 — Spec: source-formats + wiki-schema
Write adapter contracts + wiki L1-L4 health bar.
Acceptance: WhatsApp localized parsing + 6 pages template covered.

### T09 — Delta specs contract
Write `docs/changes/docs-sdd-baseline/specs.md` listing 12 New / 0 Modified.
Depends: T03-T08.

### T10 — Docs README human index
Write `docs/README.md` ES: qué es LazoGraph, flujo diagrama, tabla 8 slices con estado Accepted, links a `specs/*/spec.md` y `changes/*/`, nota custom `docs/` vs `openspec/` deviation.
Depends: T09.

### T11 — Hybrid Engram mirrors
Save `sdd/docs-sdd-baseline/proposal|specs|tasks` + `sdd/lazograph/testing-capabilities` to Engram for token-efficient retrieval. Fallback filesystem-only if token expired.
Depends: T09.

### T12 — Verify
Run `pytest -q` (no code touched, expect pass), `rg` check `docs/specs` links resolve, each spec has >=1 SHALL and >=1 Scenario, proposal <450 words.
Depends: T10-T11. Status: pending verification in this turn.

## Execution Order
T01 -> T02 -> T03,T04,T05,T06,T07,T08 parallel -> T09 -> T10,T11 -> T12

## Future Changes Convention
New feature `docs/changes/<kebab>/` SHALL contain `proposal.md`, `specs.md`, `tasks.md` per user rule. Tasks append to history, never delete `docs/changes/*`. On version reorg, update `docs/README.md` links but keep `changes/` intact.
