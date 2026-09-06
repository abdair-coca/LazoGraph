# Specs: docs-sdd-baseline

> Proposal: `docs/changes/docs-sdd-baseline/proposal.md`
> Mode: hybrid `docs/` filesystem + Engram `sdd/docs-sdd-baseline/*`
> Language: specs EN (SHALL), human index ES

## Summary
Baseline additive — introduces 12 specs, modifies none. Extracts `Requirement SHALL` + `Scenario Given/When/Then` from `VERTICAL_SLICES.md` (8 slices Accepted) and `ARCHITECTURE.md`/`OPERATIONS.md`/`references/*`. No code change.

## New Specs

| Spec | Path | Source | Key Coverage |
|------|------|--------|--------------|
| import-chat | `docs/specs/import-chat/spec.md` | VERTICAL_SLICES:205-298, ARCH:38-43 | dry-run, persona resolution, equivalent guard, idempotency, invariants |
| ask-person | `docs/specs/ask-person/spec.md` | VERTICAL_SLICES:301-390 | alias filter before retrieval, citation validation, provider neutrality, ES + abstention |
| add-context | `docs/specs/add-context/spec.md` | VERTICAL_SLICES:393-483 | classification confidence 1.0/0.75/0.5, single subject, hash preview, transactional apply |
| correct-knowledge | `docs/specs/correct-knowledge/spec.md` | VERTICAL_SLICES:486-587 | NL parse ES/EN, dry-run fingerprint, immutable ledger, effective projection |
| ask-relationship | `docs/specs/ask-relationship/spec.md` | VERTICAL_SLICES:590-684 | dual resolution, effective path excl. participant_in, facts/inferences, abstention |
| pending-plans | `docs/specs/pending-plans/spec.md` | VERTICAL_SLICES:687-786, ARCH:138-148 | IANA timezone, atomic projection lazograph-plans, lifecycle unresolved |
| grounded-suggestions | `docs/specs/grounded-suggestions/spec.md` | VERTICAL_SLICES:789-872 | single-participant isolation, no silent persistence, plan-aware |
| describe-relationship | `docs/specs/describe-relationship/spec.md` | VERTICAL_SLICES:875-959 | time-bounded, balance, safety, privacy isolation |
| architecture | `docs/specs/architecture/spec.md` | ARCH:1-284 | pipeline, invariants, effective projection, privacy, adapter contract |
| operations | `docs/specs/operations/spec.md` | OPERATIONS:1-405, ARCH:240-284 | atomic rebuild, diagnose, smoke, quarantine, vector metadata |
| source-formats | `docs/specs/source-formats/spec.md` | references/source-formats.md | universal/chat_export/social adapters, localized WhatsApp, unified schema |
| wiki-schema | `docs/specs/wiki-schema/spec.md` | references/wiki-schema.md | 6 pages, L1-L4 tags, system pages, lint health bar |

## Modified Specs
None.

## Traceability
Each spec header cites `file:line` of narrative source. Future changes SHALL add `Modified Specs` entry with delta requirements.

## Out of Scope for Specs Phase
Code edits, `openspec/` creation, rewriting narrative docs, new capabilities beyond baseline.
