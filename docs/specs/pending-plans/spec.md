# Spec: pending-plans

> Source: `docs/VERTICAL_SLICES.md:687-786` Slice 6 Accepted (`79f5400` etc), `docs/ARCHITECTURE.md:138-148`, `src/lazograph/features/pending_plans/`
> Change: `docs/changes/docs-sdd-baseline`

Resumen ES: Planes derivados con lifecycle, timezone determinista y proyección KG dedicada.

## Requirements

### REQ-PP-001: Plan model
Plan SHALL have stable `id` (title+participants+proposed_at+source_ids), `title`, `status` in `{proposed,pending,scheduled,completed,cancelled}`, `participants`, `proposed_at`, `scheduled_for`, `location`, `source_ids`, `confidence`, plus `transitions[]`.

### REQ-PP-002: Timezone-aware resolution
Relative dates SHALL resolve against `dataset.json:timezone` IANA value; missing/invalid timezone SHALL fail closed, never use host local time.

### REQ-PP-003: Atomic projection
`plans/projection.json` + `lazograph-plans` KG adapter (`plan:<id>` nodes + `plan_participant`/`plan_location` edges) SHALL be rebuilt atomically from active source backups under exclusive lock. Status SHALL never be a graph entity. Relationship traversal SHALL exclude `plan_*` edges.

### REQ-PP-004: Lifecycle handling
Duplicate/ambiguous/terminal updates/invalid transitions SHALL remain `unresolved`, not mutate state. Every transition SHALL carry `occurred_at`, `source_ids`, `confidence`, provenance.

### REQ-PP-005: Read-only interfaces
`lazo plans list|show` and `lazo ask "Do we have any pending plans?"` SHALL never mutate sources; they SHALL cite creation + latest transition evidence.

## Scenarios

### Scenario: Timezone determinism
Given dataset timezone `America/La_Paz` and message `tomorrow at 5pm` timestamped 2026-08-07
When extraction runs
Then scheduled_for = 2026-08-08T17:00:00-04:00

### Scenario: Invalid timezone fails closed
Given dataset missing timezone
When `rebuild_extracted_projection`
Then `PlanProjectionError`

### Scenario: Ambiguity unresolved
Given two participants both match `Alex`
When ambiguous plan candidate
Then stored in `unresolved`, not in projection

### Scenario: List filtering
Given 3 plans with different statuses
When `lazo plans list --status pending --json`
Then returns only pending, JSON includes transitions
