# Spec: ask-relationship

> Source: `docs/VERTICAL_SLICES.md:590-684` Slice 5 Accepted (`5f8183e`), `docs/ARCHITECTURE.md:62-64`, `src/lazograph/features/ask_relationship/`
> Change: `docs/changes/docs-sdd-baseline`

Resumen ES: Explicar relación entre dos personas usando grafo efectivo, evidencia temporal y separación hechos/inferencias.

## Requirements

### REQ-AR-001: Dual entity resolution
Without `--about`, system SHALL resolve exactly two canonical participants (or `yo` -> dataset persona + one contact). Alias and first-person SHALL be canonicalized.

### REQ-AR-002: Effective-graph path
System SHALL read effective graph, exclude `participant_in` membership edges, require original source support for generated edges, and return shortest supported path with confidence, hop count, relationship types, observed period (earliest/latest evidence).

### REQ-AR-003: Facts vs inferences
Answer SHALL separate `facts` and `inferences` both in rendered output and `Answer.to_dict()` JSON; hosted prompt SHALL receive only canonical names, relationship types, hop count, selected evidence.

### REQ-AR-004: Safe abstention
No path, ambiguous identities, missing source support, or evidence budget too small SHALL abstain, not invent.

## Scenarios

### Scenario: Direct relationship with citation
Given `Carlos --cousin--> Juan` via correction
When `lazo ask "Who is Carlos and how is Carlos related to Juan?"`
Then path `[Carlos-cousin-Juan]`, facts cite both participants, 6+ citations in real E2E

### Scenario: Membership ignored
Given only shared `participant_in` edges
When relationship query
Then abstains (`no supported relationship`)

### Scenario: First-person resolution
Given `lazo ask "¿Qué relación tengo con Juanita?"` and persona `Samantha`
When resolved
Then path uses `Samantha` as endpoint, debug shows resolved names

### Scenario: Hosted isolation
Given hosted provider
When relationship ask
Then provider receives only evidence excerpts + safe path metadata, never dataset paths
