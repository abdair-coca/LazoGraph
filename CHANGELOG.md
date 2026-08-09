# Changelog — LazoGraph

## [Unreleased]

### Added

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

### Changed

- Existing adapters and ingestion remain the implementation boundary; `scripts/*.py` commands stay
  compatible.
- Reimporting the same source exits successfully without changing persisted data.
- Semantic hits must pass canonical sender and persisted-source validation before generation.
- Manual context import time is audit metadata rather than an event timestamp, preserving chat
  chronology.
- Graph queries, diagnosis, smoke tests, and grounded answers read the effective graph while the
  generated SQLite graph remains an unchanged rebuildable base layer.

### Fixed

- Exact CLI persona roles no longer merge similarly named participants.
- `init_knowledge.py --stats` no longer crashes on legacy Windows console code pages.

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
