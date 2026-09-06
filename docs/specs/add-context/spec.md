# Spec: add-context

> Source: `docs/VERTICAL_SLICES.md:393-483` Slice 3 Accepted (`334bd4d`), `docs/ARCHITECTURE.md:48-53`, `src/lazograph/features/add_context/`
> Change: `docs/changes/docs-sdd-baseline`

Resumen ES: Agregar contexto manual clasificado, con preview/apply, hash y rollback.

## Requirements

### REQ-AC-001: Record classification
System SHALL classify each blank-line-separated block as `ASSERT/FACT/HECHO` (confidence 1.0, authority user_assertion), `CONTEXT/NOTE` or unprefixed (0.75), `INFERENCE` (0.5).

### REQ-AC-002: Single subject per record
Each record SHALL resolve to exactly one known participant; otherwise require `--about` or fail.

### REQ-AC-003: Preview metadata
Dry-run SHALL show classification, subject, authority, confidence, duplicates, PII flags, and full source SHA-256 without writing.

### REQ-AC-004: Transactional apply
Apply SHALL revalidate hash, write `user_context` normalized records + vectors, rebuild profiles/counters, validate invariants; on failure SHALL restore metadata/source snapshots and delete only vectors created by that attempt. Repeat apply of same file SHALL be idempotent.

### REQ-AC-005: Retrieval integration
Manual context SHALL be searchable via `lazo ask --about` with provenance `authored_by=dataset_owner`, `source_type=user_context`.

## Scenarios

### Scenario: Classification
Given file with `ASSERT: Alex's birthday is March 14.`
When `lazo context --dry-run`
Then reports `kind=assertion confidence=1.00 authority=user`

### Scenario: Subject resolution
Given text `We should plan trip` without names
When without `--about`
Then error `exactly one participant required`

### Scenario: Idempotency
Given already stored context hash
When `lazo context --apply` again
Then `Already stored. Dataset unchanged.`

### Scenario: Rollback on invariant fail
Given valid preview but `dataset_invariants` fails on apply
When apply runs
Then all new files/vectors rolled back, non-zero exit
