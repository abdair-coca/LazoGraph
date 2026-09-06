# Spec: architecture

> Source: `docs/ARCHITECTURE.md:1-284`, `src/lazograph/domain/`, `scripts/dataset_invariants.py`
> Change: `docs/changes/docs-sdd-baseline`

Resumen ES: Arquitectura local-first determinista con invariantes y límites de privacidad.

## Requirements

### REQ-AR-001: Deterministic pipeline
Ingestion SHALL follow `source -> adapter -> sender boundary -> persona resolution -> PII scan -> equivalent preflight -> dedup -> normalized messages -> sources/*.jsonl + ChromaDB + participants.json + KG + plans + wiki + export` per `ARCHITECTURE.md:16-33`.

### REQ-ARCH-002: Cross-layer invariants
After writes, system SHALL enforce `unique active source messages = dataset.json total_messages = participants.json summed message_count = ChromaDB vector count`; `Assistant counts = active source counts`; export snapshot matches active sources. Older exports SHALL be labeled `stale` not corrupt. Violations SHALL exit non-zero (`dataset_invariants.py`).

### REQ-ARCH-003: Effective knowledge projection
Generated SQLite triples SHALL remain rebuildable base; user assertions SHALL override only during reads via `effective = generated - retractions + assertions` with stable claim IDs (`correction.py`).

### REQ-ARCH-004: Privacy boundary
Private data SHALL live under `OPENPERSONA_KNOWLEDGE` outside git (`.gitignore` covers datasets, vectors, sources, exports, secrets). Default `lazo ask` SHALL be offline; `hosted` SHALL send only selected evidence + whitelisted metadata.

### REQ-ARCH-005: Adapter contract
Adapters SHALL emit unified schema `role (assistant|user), content, timestamp ISO8601, source_file, source_type, metadata.sender` per `ARCHITECTURE.md:73-84`; `persona=assistant`, others `user`.

## Scenarios

### Scenario: Invariant passes after import
Given successful `lazo import`
When `dataset_invariants.validate_dataset`
Then `unique == total == participants sum == vector count`

### Scenario: Privacy default offline
Given default ask
When inspecting network
Then zero outbound traffic, provider is `LocalExtractive`

### Scenario: Effective projection after rebuild
Given generated triple `Sam --friend--> Alex` and active correction `colleague`
When rebuilding KG
Then effective still returns `colleague`
