# Spec: grounded-suggestions

> Source: `docs/VERTICAL_SLICES.md:789-872` Slice 7 Accepted (`be9df6c`), `src/lazograph/features/suggestions/`
> Change: `docs/changes/docs-sdd-baseline`

Resumen ES: Sugerencias fundadas en preferencias/evidencias, sin persistir como hecho.

## Requirements

### REQ-GS-001: Single-participant grounded routing
Suggestion question SHALL resolve exactly one canonical participant and use participant-isolated sources (preferences, memories, corrections, plans, dates, constraints).

### REQ-GS-002: Structure
Answer SHALL separate `facts`, `inferences`, `suggestions`, `missing_information`; rendered and JSON SHALL match.

### REQ-GS-003: No silent persistence
System SHALL never persist a suggestion as fact; confirmation via explicit `lazo context|correct` flow required.

### REQ-GS-004: Correction and plan awareness
Corrections, active plan status, timing, constraints SHALL influence output; unsupported/weak/conflicting/sensitive context SHALL ask clarification or abstain.

## Scenarios

### Scenario: Grounded gift suggestion
Given `lazo ask "What could I give Alex as a gift?"` with birthday evidence
When provider called
Then suggestions cite `user_context` provenance and include missing_information if budget unknown

### Scenario: Sensitive abstention
Given sensitive context with no strong evidence
When asked
Then abstains or asks clarifying question

### Scenario: Plan-aware suggestion
Given `Alex` has pending plan `dinner tomorrow`
When suggestion requested
Then suggestion respects plan timing, not contradicts

### Scenario: Nothing persisted
Given suggestion generated
When inspecting ledger/sources
Then no new file or ledger entry without user confirmation
