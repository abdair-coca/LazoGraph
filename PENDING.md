# Pending work

## Optimization backlog from real end-to-end testing

- [ ] Add a single `diagnose` command that prints the active knowledge root, dataset path,
  Git/schema version, source counts, participant totals, vector counts, KG counts, and
  wiki/export health. We initially queried a stale dataset state without enough diagnostics.
- [ ] Reject WhatsApp system notices as senders at the ingestion boundary. Two notices
  (`end-to-end encryption` and `disappearing messages`) became one-message contacts and
  malformed KG entities.
- [ ] Detect equivalent source backups before ingestion. The direct export (3614 messages)
  and an older normalized export (3627 lines) produced a 3663-message union instead of
  being recognized as two representations of the same chat.
- [ ] Add dataset-wide invariants after every write: active-source unique messages must equal
  dataset stats, participant totals, vector count, and export source snapshot. The mismatch
  was only found after KG reconstruction.
- [ ] Make source reconciliation an automatic preflight with a confirmation report, instead
  of requiring a separate repair after duplicate backups already affect profiles/KG/vectors.
- [ ] Add a metadata-only vector migration. Adding `sender` currently re-embeds all 3614
  messages and takes roughly 2–4 minutes even when document text and embeddings are unchanged.
- [ ] Show batch progress and estimated remaining time during vector rebuild. Long CPU work
  currently appears inactive between start and completion.
- [ ] Make KG/vector/wiki rebuild an optional atomic transaction with rollback. Current layers
  are individually recoverable, but interruption between them can temporarily leave counts
  inconsistent.
- [ ] Add automatic post-rebuild smoke tests for canonical aliases, KG paths, participant-filtered
  semantic search, wiki lint, and export pair balance.
- [ ] Improve Windows E2E process output and cleanup. Buffered subprocess logs hid progress,
  the first run exceeded a 120-second wrapper timeout, and one validation run temporarily held
  `chroma.sqlite3` open during cleanup.
- [ ] Add structured quarantine inspection and restore commands. Duplicate sources are preserved
  safely now, but restoration still requires manual filesystem work.
- [ ] Expand relationship/entity extraction beyond regex with conservative NER, coreference,
  confidence thresholds, and false-positive evaluation.
- [ ] Add PII redaction/export policies. Current scanner flags PII but raw and training exports
  retain it unless the operator handles it separately.

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
