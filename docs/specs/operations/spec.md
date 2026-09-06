# Spec: operations

> Source: `docs/OPERATIONS.md:1-405`, `docs/ARCHITECTURE.md:240-284`, `scripts/rebuild_all.py`, `scripts/diagnose.py`, `scripts/smoke_test.py`
> Change: `docs/changes/docs-sdd-baseline`

Resumen ES: Workflows operativos con transactions, diagnosis y quarantine recuperable.

## Requirements

### REQ-OP-001: Atomic rebuild
`rebuild_all.py --atomic` SHALL acquire exclusive `.rebuild.lock`, snapshot `.mempalace/palace/, participants.json, dataset.json, plans/, wiki/`, run vector->KG->wiki->lint->smoke in subprocesses, and restore exact prior state on any stage failure or `KeyboardInterrupt`.

### REQ-OP-002: Health interpretation
`diagnose.py` SHALL be read-only, return `healthy` only if all critical layers agree; `warning` for stale derived artifacts; `error` for divergent counts/unreadable DB/wiki structural issues; `--json` machine readable, non-zero only on critical corruption.

### REQ-OP-003: Smoke tests
`smoke_test.py` SHALL probe alias resolution, persona/contact KG path, participant-filtered retrieval, wiki lint, export pair balance; ALL five SHALL pass post-atomic rebuild or rollback.

### REQ-OP-004: Quarantine transactions
`quarantine.py list|show|restore(--apply)` SHALL preview by default, reject active filename conflicts, restore source-index + rebuild layers transactionally with rollback.

### REQ-OP-005: Vector maintenance
`--migrate-vector-metadata` SHALL update only `metadata.sender` via Chroma `update(ids, metadatas)` without re-embedding; ID drift SHALL abort and request `--rebuild-vectors`. `--rebuild-vectors` SHALL print progress every 128 msgs with ETA.

## Scenarios

### Scenario: Atomic rollback
Given atomic run and wiki lint fails
When stage exits 1
Then previous vectors/graph/participants/wiki restored, no partial files

### Scenario: Diagnose stale vs error
Given export older than active sources
When `diagnose.py`
Then `warning: stale export`, not `error`

### Scenario: Quarantine preview
Given `quarantine.py restore <batch>` without `--apply`
Then prints plan, no files moved, exit 0

### Scenario: Smoke gating rebuild
Given rebuilt vectors missing filtered participant
When smoke runs as final stage
Then atomic rebuild rolls back
