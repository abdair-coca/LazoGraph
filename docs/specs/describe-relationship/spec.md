# Spec: describe-relationship

> Source: `docs/VERTICAL_SLICES.md:875-959` Slice 8 Accepted (uncommitted worktree), `src/lazograph/features/describe_relationship/`
> Change: `docs/changes/docs-sdd-baseline`

Resumen ES: Descripción de relación acotada en tiempo, balanceada, sin diagnóstico.

## Requirements

### REQ-DR-001: Time-bounded summary
Answer SHALL state analyzed period and evidence coverage (earliest/latest participant-filtered messages).

### REQ-DR-002: Separation
Answer SHALL separate observations, measured patterns, interpretations, and unknowns. Factual claims SHALL have citations; interpretations SHALL be labeled uncertain.

### REQ-DR-003: Balance and safety
Answer SHALL balance positive/negative/contradictory evidence, expose active corrections and contradictions, and reject psychological diagnosis, absolute judgments, unsupported labels.

### REQ-DR-004: Privacy boundary
Provider prompt SHALL contain only selected evidence for the two requested participants, never third-party unrelated data. Third-party exposure SHALL be gated.

## Scenarios

### Scenario: Balanced description
Given mixed evidence for `Alex`
When `lazo ask "How would you describe my relationship with Alex?"`
Then output has `Facts` with citations + `Interpretation` labeled, `Observed period` line

### Scenario: Contradiction exposed
Given conflicting evidence about reliability
When described
Then both sides cited and marked `contradictory`, not single conclusion

### Scenario: Diagnostic language blocked
Given prompt tries to force diagnosis
When generated
Then provider guard rejects `psychological diagnosis` language

### Scenario: Privacy isolation
Given dataset has `Sam` unrelated messages
When describing `Alex`
Then hosted prompt never includes `Sam` excerpts
