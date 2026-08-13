# Pending work

## Active roadmap

- [x] **Slice 1 — Import Chat: Accepted.** Packaged `lazo import`, participant preview, safe
  focal-person resolution, confirmation, idempotent reimport, equivalent-source preflight,
  compatibility wrappers, and final invariant validation passed automated and real-data testing.

- [x] **Slice 2 — Ask About a Person: Accepted.** Participant-isolated semantic retrieval,
  provider-neutral synthesis, persisted citations, confidence, Spanish output, contradiction
  handling, and safe abstention passed automated and real-data testing.

- [x] **Slice 3 — Add Manual Context: Accepted.** Preview/apply semantics, classified
  authority, PII/source-hash reporting, transactional persistence, idempotency, grounded citations,
  and invariant validation passed automated and end-to-end testing.

- [x] **Slice 4 — Correct Knowledge: Accepted.** Safe bilingual correction previews,
  immutable assertion/retraction/supersede history, effective graph reads, grounded citations,
  rebuild persistence, conflict protection, audit listing, and reversible undo passed automated
  and disposable end-to-end testing. Feedback repair also canonicalizes expanded compound names,
  prunes historical identity-shadow orphans, and rejects genuinely ambiguous abbreviations.

- [x] **Slice 5 — Ask About Relationships: Accepted.** Effective-KG path lookup,
  participant-isolated temporal evidence, source-backed facts, explicit inferences, correction
  priority, aliases/first-person resolution, provider-safe context, and safe abstention passed 194
  automated tests plus read-only real-dataset verification.

- [ ] **Slice 6 — Pending Plans: In Progress.** Implementing structured plan extraction,
  deterministic date and timezone resolution, lifecycle and duplicate matching, evidence-backed
  state transitions, participant/location projection, and grounded list/show/ask interfaces.

The [Vertical Slice Roadmap](docs/VERTICAL_SLICES.md) is the source of truth for all eight slices,
their dependencies, acceptance criteria, feedback checklists, and mandatory approval records.
No later slice may start until the user writes the exact acceptance phrase for the current slice.

## Completed optimization backlog from real end-to-end testing

- [x] Add a single `diagnose` command that prints the active knowledge root, dataset path,
  Git/schema version, source counts, participant totals, vector counts, KG counts, and
  wiki/export health. `diagnose.py` now checks every persisted layer without mutation,
  reports human-readable or JSON output, distinguishes stale/not-built warnings from corrupt
  state, and exits non-zero for critical health failures.
- [x] Reject WhatsApp system notices as senders at the ingestion boundary. Two notices
  (`end-to-end encryption` and `disappearing messages`) became one-message contacts and
  malformed KG entities. The WhatsApp parser now recognizes notices even when they contain
  a colon, and the shared ingestion boundary rejects known notices plus structurally invalid
  sender names before they can reach deduplication, vectors, participant profiles, or the KG.
- [x] Detect equivalent source backups before ingestion. The direct export (3614 messages)
  and an older normalized export (3627 lines) produced a 3663-message union instead of
  being recognized as two representations of the same chat. Ingestion now compares normalized
  content overlap against every active backup and stops before all writes when a large source
  has at least 95% overlap and a similar size. Small sources require an exact match; intentional
  imports can use `--allow-equivalent-source`; confirmed replacement uses recoverable quarantine.
- [x] Add dataset-wide invariants after every write: active-source unique messages must equal
  dataset stats, participant totals, vector count, and export source snapshot. The mismatch
  was only found after KG reconstruction. A shared validator now checks active JSONL backups,
  `dataset.json`, `participants.json`, Chroma's persisted vector count, the latest export state,
  and newly generated export metadata. Ingestion and rebuilds fail loudly on divergence;
  initialization, staged reconciliation, and legacy export flows report without destructive
  repair. Older exports that predate source changes are labeled stale instead of corrupt.
- [x] Make source reconciliation an automatic preflight with a confirmation report, instead
  of requiring a separate repair after duplicate backups already affect profiles/KG/vectors.
  Equivalent ingestion now prints the exact replacement plan and writes nothing by default.
  `--reconcile-equivalent-source` explicitly confirms selective, recoverable quarantine; the
  incoming source becomes authoritative, then stale vectors, participant profiles, managed KG,
  counters, source index, and invariants are rebuilt. `--dry-run` previews the full plan safely.
- [x] Add a metadata-only vector migration. Adding `sender` previously re-embedded all 3614
  messages even when document text and embeddings were unchanged. The new
  `--migrate-vector-metadata` path compares authoritative vector IDs, updates only changed
  metadata through Chroma `update(ids=..., metadatas=...)`, verifies persisted fields, and
  never submits documents or embeddings. ID drift aborts safely and requests `--rebuild-vectors`;
  `--dry-run` reports required changes without writing.
- [x] Show batch progress and estimated remaining time during vector rebuild. Rebuild and
  equivalent-source replacement now print flushed status after every 128-message batch:
  stored/total, percentage, elapsed time, and ETA derived from measured average throughput.
  Zero-duration and completed batches remain deterministic and avoid division errors.
- [x] Make KG/vector/wiki rebuild an optional atomic transaction with rollback. New
  `rebuild_all.py --atomic` acquires an exclusive dataset lock, snapshots palace storage,
  participant profiles, dataset metadata, and wiki into a private temporary directory, then
  runs vector rebuild, KG rebuild, wiki build, and lint in isolated subprocesses. Any failed
  stage or `KeyboardInterrupt` restores exact previous files and removes newly created paths.
  Omitting `--atomic` preserves explicit non-atomic behavior.
- [x] Add automatic post-rebuild smoke tests for canonical aliases, KG paths, participant-filtered
  semantic search, wiki lint, and export pair balance. `smoke_test.py` now runs all five probes,
  reports every failed layer, and is the final coordinated rebuild stage so atomic mode rolls
  back when rebuilt data is not functionally queryable.
- [x] Improve Windows E2E process output and cleanup. Child stages now run unbuffered with
  flushed labels, configurable per-stage timeouts, safe legacy-console output, and retrying
  cleanup for briefly locked SQLite files. `--keep-temp` preserves failures for inspection.
- [x] Add structured quarantine inspection and restore commands. `quarantine.py` lists batches,
  exposes manifests, file counts and hashes, previews restoration by default, rejects filename
  conflicts, and restores sources plus all affected derived layers transactionally with rollback.
- [x] Expand relationship/entity extraction beyond regex with conservative NER, coreference,
  confidence thresholds, and false-positive evaluation. Extraction now combines known identities,
  contextual and multiword NER, two-message bounded pronoun resolution, numeric confidence with
  a strict acceptance floor, stop-token rejection, and labeled precision/recall/F1 evaluation.
- [x] Add PII redaction/export policies. Export now blocks detected PII before creating output by
  default; `redact` sanitizes raw copies, conversations, profile, and probes; `allow` requires an
  explicit choice. Metadata records findings, policy, replacements, and omits private local paths.

## Resolved defects kept for regression context

- [x] Stop silently falling back to `kg-pending.json` when the persisted KG API returns an error;
  query the local SQLite graph deterministically.
- [x] Replace the redundant compound Chroma filter with direct canonical `sender` filtering.
- [x] Prune malformed orphan KG entities during rebuild while preserving valid/manual entities.
- [x] Reconcile duplicate backups through recoverable quarantine and update source index/stats.
- [x] Remove stale vector IDs during rebuild after authoritative-source reconciliation.

## Completed after end-to-end test

- [x] Support Spanish WhatsApp timestamps containing `a. m.` / `p. m.`.
- [x] Accept Unicode non-breaking spaces (`U+00A0`, `U+202F`) around meridiem markers.
- [x] Update automatic adapter detection and `chat_export` timestamp parsing.
- [x] Preserve multiline WhatsApp messages.
- [x] Add Spanish entity and relationship extraction.
- [x] Add regression coverage for localized Android/iOS WhatsApp exports on Windows.
- [x] Remove need for temporary UTF-8 normalization workaround.
- [x] Identify persona and contacts independently, including repeated aliases.
- [x] Build six evidence-backed wiki pages from persona-authored messages only.
- [x] Export authentic user/assistant dialogue without invented prompts.
- [x] Add disposable full end-to-end verification from raw source to export.
- [x] Add participant-filtered semantic search and vector metadata rebuild.
