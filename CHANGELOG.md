# Changelog — LazoGraph

## [Unreleased]

### Added

- Multilingual embeddings by default: LazoGraph now sets
  `MEMPALACE_EMBEDDING_MODEL=embeddinggemma` when the user has not chosen a
  model, so Spanish (and other non-English) chat retrieval uses the
  multilingual `embeddinggemma-300m` ONNX embedder (cross-lingual cosine ~0.88
  vs ~0.35 for the English-only MiniLM default). An explicit
  `MEMPALACE_EMBEDDING_MODEL` still wins. Existing datasets built with MiniLM
  must be re-embedded (different vector space); `diagnose.py` fails loudly on
  the mismatch until then.
- Packaged `lazo` entry point and Slice 1 `lazo import` command.
- Non-mutating participant preview with exact focal-person resolution, counts, PII flags,
  duplicates, rejected system notices, and equivalent-source warnings.
- Automatic dataset initialization after confirmation plus final invariant validation.
- Localized generic import fixture and Slice 1 CLI/integration regression coverage.
- Slice 2 `lazo ask` with participant-filtered retrieval, persisted Evidence citations, Answer
  contracts, confidence, safe debug summaries, and Spanish responses.
- Provider-neutral `LLMProvider` implementations: offline extractive default, local Ollama, and an
  explicitly configured evidence-only hosted boundary.
- Abstention for missing, weak, contradictory, or topic-mismatched evidence.
- Slice 3 `lazo context` with dry-run/apply semantics, explicit assertion/freeform/inference
  classification, subject resolution, source hashes, authorship, authority, and confidence.
- Transactional manual-context persistence across source backup, Chroma vectors, participant
  profiles, dataset counters, and invariants, including failure rollback and idempotent reapply.
- Manual-context citations in Slice 2 with provider-safe provenance and correct non-speaker wording.
- Slice 4 `lazo correct` bilingual relationship replacement with non-mutating dry-run, strict
  entity resolution, PII reporting, and stale-preview conflict protection.
- Private append-only correction ledger with assertion/retraction/supersede records, audit listing,
  idempotent apply, rebuild-safe effective graph projection, and reversible undo events.
- Correction-backed answer evidence with participant isolation, user authority, and distinct
  provenance from extracted messages and manual context.
- Slice 5 relationship questions through `lazo ask` without `--about`, including canonical alias
  and first-person resolution, effective-graph paths, source-backed temporal citations, explicit
  facts/inferences, and safe no-path abstention.
- Relationship-answer regression coverage for direct and indirect paths, correction overrides,
  date-only graph evidence, hosted-provider isolation, JSON output, and real import-to-answer E2E.
- Slice 6 pending plans: deterministic timezone-aware Plan contracts, lifecycle extraction with
  source-backed transitions, atomic JSON projection, read-only `lazo plans list/show`, and explicit
  pending-plan questions with creation/latest-transition citations.
- Dedicated `lazograph-plans` Knowledge Graph projection with stable plan nodes and participant/
  location edges; plan status remains structured data and is excluded from relationship traversal.

### Changed

- Existing adapters and ingestion remain the implementation boundary; `scripts/*.py` commands stay
  compatible.
- Reimporting the same source exits successfully without changing persisted data.
- Semantic hits must pass canonical sender and persisted-source validation before generation.
- Manual context import time is audit metadata rather than an event timestamp, preserving chat
  chronology.
- Graph queries, diagnosis, smoke tests, and grounded answers read the effective graph while the
  generated SQLite graph remains an unchanged rebuildable base layer.
- `lazo ask --about` is optional: supplying it preserves participant-isolated Slice 2 behavior;
  omitting it routes an exactly-two-participant question to Slice 5.
- Explicit pending-plan questions are recognized before relationship fallback. Imports and atomic
  rebuilds refresh plans from active source backups; ambiguous candidates remain unresolved.
- New datasets declare IANA `timezone` metadata (default `UTC`) for deterministic relative-date
  resolution, and plan projections fail closed when that metadata is missing or invalid.
- The `mempalace` dependency floor is now `3.3.6` (first release with the multilingual embedder).

### Fixed

- Exact CLI persona roles no longer merge similarly named participants.
- `init_knowledge.py --stats` no longer crashes on legacy Windows console code pages.
- Expanded compound names that contain one known participant no longer create truncated orphan
  entities. KG rebuild removes historical identity shadows, unique participant prefixes resolve to
  the canonical profile, and genuinely ambiguous abbreviations fail explicitly.

## [0.3.0] — 2026-08-07

### Added

- Localized Spanish WhatsApp parsing, multiline preservation, and system-notice rejection.
- Canonical persona/contact profiles with aliases and participant-filtered semantic search.
- Equivalent-source detection, recoverable reconciliation, quarantine inspection, and transactional restoration.
- Dataset-wide source/profile/vector/export consistency invariants.
- Vector metadata-only migration plus rebuild progress and ETA.
- Atomic vector/KG/wiki rebuild with exclusive lock and rollback.
- Read-only dataset diagnosis and five cross-layer functional smoke tests.
- Deterministic evidence-backed six-page wiki builder.
- Conservative person NER, bounded coreference, numeric relationship confidence, and labeled extraction evaluation.
- PII export policies: default block, deterministic redaction, and explicit allow.
- Windows-safe E2E output, configurable stage timeouts, and retrying temporary cleanup.
- Authentic alternating dialogue export without invented prompts.

### Changed

- Project product name is now LazoGraph; the compatible skill/package identifier remains `persona-knowledge`.
- Knowledge Graph access uses the current `db_path` API and persisted SQLite state.
- Private dataset storage is explicitly separated from the Git checkout.
- Wiki generation is now deterministic and script-driven; human or agent review remains optional.

### Fixed

- Duplicate normalized/direct chat backups no longer inflate datasets.
- Stale vectors are pruned after authoritative source changes.
- Malformed WhatsApp notices cannot become participants or orphan graph entities.
- Semantic participant filters resolve canonical sender metadata correctly.
- Windows legacy console code pages no longer crash CLI output.

### Current limitation

- Semantic and graph queries return evidence; conversational RAG answer synthesis is not implemented yet.

## [0.2.0] — 2026-04-11

### Added

- **Dataset export versioning** — every `export_training.py` run now assigns an auto-incremented version tag (`v1`, `v2`, …) and records it in `training/metadata.json` as `export_version`. Override with `--version <tag>`.
- **Export hash** — `metadata.json` now includes `export_hash` (SHA-256 of `conversations.jsonl`) and `source_snapshot` (per-file hash of all source files at export time).
- **Export history** — each export appends an entry to `dataset.json → export_history[]`, enabling full audit trail without re-running exports.
- `**--list` flag** — `export_training.py --slug {slug} --list` shows all past exports with version, hash, turn count, and timestamp.
- `**--wiki-only` flag** — skips copying `sources/` to `training/raw/`, useful when only wiki-derived conversations are needed.
- `**probes.json` generation** — `export_training.py` now auto-generates `training/probes.json` from `wiki/identity.md` and `wiki/voice.md`. Contains weighted keyword probes (name: 1.0, identity: 0.8, voice: 0.5) consumed by `persona-model-trainer`'s probe evaluation step.
- **27 unit tests** — covering export versioning, hash format, source snapshot, export history, `--list`, `--wiki-only`, `--version`, probes schema, hash determinism.
- **Cross-skill next-step guidance** — Phase 4 export section now includes a ready-to-run `pipeline.sh` command (with `--probes`) pointing to `persona-model-trainer`.

### Changed

- `metadata.json` output extended with `export_version`, `export_hash`, `source_snapshot` fields (backward-compatible — old consumers ignore unknown fields).
- `export_training.py` module docstring updated to list `probes.json` in the output structure.

---

## [0.1.0] — initial release

- `init_dataset.py` — initialize dataset with MemPalace wing + KG + wiki structure
- `ingest.py` — unified ingestion: adapter dispatch, PII scan, dedup, MemPalace, KG
- `export_training.py` — export sources + wiki → `training/` directory
- `lint_wiki.py` — wiki health check
- `query_kg.py` — Knowledge Graph query CLI
