# Spec: correct-knowledge

> Source: `docs/VERTICAL_SLICES.md:486-587` Slice 4 Accepted (`e36dcc1`), `docs/ARCHITECTURE.md:55-60`, `src/lazograph/features/correct_knowledge/`
> Change: `docs/changes/docs-sdd-baseline`

Resumen ES: Corregir relaciones vía ledger inmutable, con preview obligatorio y proyección efectiva.

## Requirements

### REQ-CK-001: Natural-language parse
System SHALL parse one conservative English/Spanish relationship replacement (sibling, cousin, friend, partner, coworker, spouse, parent, child, manager, conversation partner) with both endpoints exactly resolved.

### REQ-CK-002: Dry-run plan
Dry-run SHALL show resolved entities, matched effective claims, retraction, assertion, PII flags, fingerprint without writing.

### REQ-CK-003: Immutable ledger
Apply SHALL append to `corrections/ledger.jsonl` under exclusive lock, with assertion/retraction/supersede, stable claim IDs independent of filenames/timestamps. Generated `knowledge_graph.sqlite3` SHALL remain unchanged.

### REQ-CK-004: Effective projection priority
Reads via `query_kg.py`, diagnose, smoke, and `lazo ask` SHALL use `effective = generated - active retractions + active assertions` with user assertions confidence 1.0 overriding generated.

### REQ-CK-005: Idempotency and conflict protection
Repeating active correction SHALL be no-op. Stale preview fingerprint vs ledger head SHALL fail. Ambiguity/missing old claim/lock/corruption SHALL write nothing. `undo <claim-id>` SHALL append reversal event, never delete.

## Scenarios

### Scenario: Successful correction
Given effective graph has `Carlos --brother--> Juan`
When `lazo correct "Carlos is Juan's cousin, not his brother" --apply`
Then ledger contains retraction brother + assertion cousin, effective query returns cousin

### Scenario: Ambiguity blocks
Given `Alex` matches two participants via abbreviation
When correcting
Then exit 2, no ledger entry

### Scenario: Rebuild persistence
Given active correction
When `rebuild_all.py --atomic`
Then effective graph still returns corrected relation

### Scenario: Undo
Given correction claim `c-abc`
When `lazo corrections undo c-abc`
Then effective view restores brother, history retains both events
