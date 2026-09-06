# Spec: ask-person

> Source: `docs/VERTICAL_SLICES.md:301-390` Slice 2 Accepted (`532e95e`), `docs/ARCHITECTURE.md:44-46`, `src/lazograph/domain/answer.py`
> Change: `docs/changes/docs-sdd-baseline`

Resumen ES: Responder preguntas sobre una persona con evidencia citada, filtrado por participante y abstención segura.

## Requirements

### REQ-AP-001: Canonical alias filter before retrieval
System SHALL resolve `--about` via `participants.json` canonical + aliases before ChromaDB query; mismatched hits SHALL be rejected before generation.

### REQ-AP-002: Citation validation
Every `Answer.citation` SHALL point to persisted `Evidence` (message_id, persisted source) included in prompt; invalid citation SHALL cause hard error, not guess.

### REQ-AP-003: Provider neutrality
Default provider SHALL be offline extractive (`LocalExtractiveProvider`) sending zero network data. `ollama` stays local; `hosted` requires explicit `LAZOGRAPH_HOSTED_URL|MODEL|API_KEY` and sends only selected evidence budget.

### REQ-AP-004: Spanish output and abstention
Spanish questions SHALL yield Spanish answers. Missing/weak/contradictory/topic-mismatched evidence SHALL produce abstention, not invention.

## Scenarios

### Scenario: Alias equivalence
Given `Sam` alias of `Samantha`
When `lazo ask "What does Sam like?" --about Sam` vs `--about Samantha`
Then both return same citations and confidence

### Scenario: Cross-participant isolation
Given evidence for `Alex` and `Sam`
When asking about `Alex`
Then citations contain only `Alex` evidence, zero leakage

### Scenario: Abstention unknown preference
Given no evidence about `Alex` preference
When `lazo ask "What does Alex like?" --about Alex`
Then answer abstains with `insufficient evidence` and no hallucinated claim

### Scenario: Hosted boundary
Given `--provider hosted`
When provider called
Then prompt contains only selected evidence + whitelisted profile metadata, never full dataset
