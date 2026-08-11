---
name: persona-knowledge
description: "Operate LazoGraph: a local-first personal knowledge graph with semantic memory, participant identity, evidence wiki, recovery workflows, and PII-safe exports."
license: MIT
compatibility: "Python 3.11+ and mempalace >= 3.1.0. Windows, macOS, and Linux."
allowed-tools: Read Write Bash
metadata:
  version: "0.8.0"
  project: LazoGraph
  upstream: acnlabs/persona-knowledge
  requires: "python >= 3.11, mempalace >= 3.1.0"
---

# LazoGraph operator skill

Use this skill when the user wants to create, ingest, inspect, query, rebuild, repair, verify, or export a persistent personal knowledge dataset.

Do not use it for one-shot summarization with no persistent dataset. Do not place private source data inside the Git repository.

## Safety rules

1. Set `OPENPERSONA_KNOWLEDGE` to a private directory outside the repository.
2. Run ingestion with `--dry-run` before the first write from any source format.
3. Confirm parsed counts, roles, participant names, and PII flags.
4. Never merge equivalent backups blindly. Use reconciliation/quarantine workflows.
5. Prefer `rebuild_all.py --atomic` for coordinated derived-state changes.
6. Run `diagnose.py` and `smoke_test.py` after repairs.
7. Export uses PII `block` by default. Prefer `redact` for shareable artifacts.
8. Never commit dataset files, vectors, source backups, exports, or secrets.

## Environment

Windows PowerShell:

```powershell
$env:PYTHONUTF8='1'
$env:OPENPERSONA_KNOWLEDGE="$env:LOCALAPPDATA\LazoGraph\knowledge"
```

macOS/Linux:

```bash
export PYTHONUTF8=1
export OPENPERSONA_KNOWLEDGE="$HOME/.local/share/LazoGraph/knowledge"
```

## Phase 1: preview and import

```bash
lazo import <path> --slug {slug} --persona "Display Name" --dry-run
lazo import <path> --slug {slug} --persona "Display Name"
```

First command never writes. Second repeats preflight, asks for confirmation, initializes a missing
dataset, imports every storage layer, and validates invariants. Reimporting the same source must
report zero new messages without changing data.

## Legacy or advanced ingestion

Existing scripts remain supported:

```bash
python scripts/ingest.py \
  --slug {slug} \
  --source <path> \
  --persona-name "Display Name" \
  --dry-run
```

Then ingest only after validating output:

```bash
python scripts/ingest.py \
  --slug {slug} \
  --source <path> \
  --persona-name "Display Name"
```

Pipeline:

1. Detect or force adapter.
2. Parse into normalized role/content/timestamp/sender messages.
3. Reject malformed chat system notices at the shared boundary.
4. Scan PII.
5. detect equivalent source backups before writes.
6. Deduplicate content.
7. Persist vectors with canonical participant metadata.
8. Write immutable normalized JSONL backup.
9. Build participant profiles and aliases.
10. Extract graph entities/relationships with numeric confidence.
11. Validate dataset-wide invariants.

## Phase 2: ask about one participant

```bash
lazo ask "What does Alex like?" --about Alex --slug {slug}
```

Default `local` provider stays offline. Results contain persisted message citations and abstain when
evidence is weak, contradictory, or unavailable. `--provider ollama` enables local generation.
`--provider hosted` requires explicit endpoint/model/key configuration and sends only selected
evidence. Never use an unfiltered retrieval result to answer about a named participant.

## Phase 3: add manual context

```bash
lazo context <context.txt> --slug {slug} --dry-run
lazo context <context.txt> --slug {slug} --apply
```

Separate records with blank lines. Prefix explicit assertions with `ASSERT:`, freeform notes with
`CONTEXT:`, and user-declared inferences with `INFERENCE:`. Unprefixed text remains freeform. Every
record must resolve to exactly one known participant; use `--about` for an implicit subject.

Review subject, kind, authority, confidence, duplicates, PII flags, and source hash before apply.
Explicit assertions alone receive confidence `1.0`. Apply persists normalized `user_context`
evidence and vectors, validates invariants, and rolls back new artifacts on failure. Repeat apply
to verify it reports no changes. Manual context is searchable and citable through `lazo ask`.

If an equivalent source exists, stop by default. Use:

```bash
python scripts/ingest.py ... --reconcile-equivalent-source
```

This quarantines equivalent active backups recoverably, stores the incoming authoritative replacement, and rebuilds all affected derived layers.

## Phase 4: correct relationship knowledge

Preview an exact relationship replacement first:

```bash
lazo correct "Carlos is Juan's cousin, not his brother" --slug {slug} --dry-run
lazo correct "Carlos no es hermano de Juan, es su primo" --slug {slug} --dry-run
```

Confirm the resolved entities, old claim, retraction, assertion, PII flags, and fingerprint. Apply
only if the statement represents the dataset owner's intended truth:

```bash
lazo correct "Carlos is Juan's cousin, not his brother" --slug {slug} --apply
lazo corrections --slug {slug} list
python scripts/query_kg.py --slug {slug} --entity Carlos
```

Corrections append to a private immutable ledger and override generated triples only in effective
reads. Rebuilds preserve them. Repeating an active correction is a no-op; ambiguity, missing old
claims, stale previews, locks, and corrupt ledger state fail without writes. Undo is append-only:

```bash
lazo corrections --slug {slug} undo <claim-id>
```

## Phase 5: ask about relationships

Omit `--about` and name two participants, or use first-person wording with one contact:

```bash
lazo ask "Who is Carlos and how is Carlos related to Juanita?" --slug {slug}
lazo ask "¿Qué relación tengo con Alex?" --slug {slug}
```

Relationship mode resolves canonical identities, reads the effective graph, ignores
membership-only `participant_in` paths, and requires original source support for generated edges.
It returns path confidence, temporal evidence, citations, separate facts and interpretations, or
abstains when the relationship is unsupported. Active user corrections take priority. `--debug`
shows the retrieval summary and `--json` exposes the structured answer. Hosted providers receive
only selected evidence and safe path metadata.

## Phase 6: rebuild and verify

Preferred coordinated path:

```bash
python scripts/rebuild_all.py --slug {slug} --atomic
```

Stages:

1. Vector rebuild with batch progress and ETA.
2. Managed graph rebuild.
3. Deterministic wiki build.
4. Wiki lint.
5. Functional smoke tests.

Atomic mode acquires an exclusive dataset lock and restores prior vector, graph, participant, metadata, and wiki state after any failure or interruption.

Individual maintenance commands:

```bash
python scripts/ingest.py --slug {slug} --rebuild-vectors
python scripts/ingest.py --slug {slug} --rebuild-kg
python scripts/build_wiki.py --slug {slug} --dry-run
python scripts/build_wiki.py --slug {slug}
python scripts/lint_wiki.py --slug {slug}
```

## Phase 7: retrieve knowledge

Semantic evidence:

```bash
python scripts/query_memory.py \
  --slug {slug} \
  --query "natural language query" \
  --participant "canonical name or alias" \
  --limit 5
```

Graph:

```bash
python scripts/query_kg.py --slug {slug} --entity "Name"
python scripts/query_kg.py --slug {slug} --path "Name A" "Name B"
python scripts/query_kg.py --slug {slug} --stats
```

`query_kg.py` reads the effective graph, including active user corrections. `query_memory.py`
returns evidence rather than generated prose; use `lazo ask` for grounded person or relationship
answers.

## Phase 8: diagnose

```bash
python scripts/diagnose.py --slug {slug}
python scripts/diagnose.py --slug {slug} --json
python scripts/smoke_test.py --slug {slug}
```

Healthy completion requires matching source/message/profile/vector counts, readable graph, valid wiki, and five passing functional smoke probes.

## Phase 9: recover sources

```bash
python scripts/quarantine.py --slug {slug} list
python scripts/quarantine.py --slug {slug} show <batch>
python scripts/quarantine.py --slug {slug} restore <batch>
python scripts/quarantine.py --slug {slug} restore <batch> --apply
```

Restore is a plan unless `--apply` is supplied. Apply refuses active filename conflicts, restores source-index metadata, rebuilds affected layers, and rolls back source plus derived state after failure.

## Phase 10: export

Default PII block:

```bash
python scripts/export_training.py --slug {slug} --output training/{slug}
```

Recommended shareable export:

```bash
python scripts/export_training.py \
  --slug {slug} \
  --output training/{slug}-redacted \
  --pii-policy redact
```

`allow` must be explicit. Metadata records policy, detected types, replacement totals, version, conversation hash, and source snapshot without exposing local dataset paths.

Output:

```text
raw/
conversations.jsonl
profile.md
metadata.json
probes.json
```

## Phase 11: end-to-end test

```bash
python scripts/e2e_test.py \
  --source <raw-export> \
  --persona-name "Display Name" \
  --persona-query "Persona alias" \
  --contact-query "Contact alias" \
  --stage-timeout 900 \
  --pii-policy redact
```

The test creates a disposable root, runs the complete workflow, validates exact-count gates when supplied, streams unbuffered child logs, and removes temporary state with Windows-safe retries.

## Supported formats

See `references/source-formats.md`. Adapters:

- `universal`: Markdown, text, CSV, PDF, JSON/JSONL, Obsidian, GBrain.
- `chat_export`: localized WhatsApp, Telegram, Signal, iMessage.
- `social`: X/Twitter and Instagram archives.

## Graph extraction changes

Before modifying extraction rules:

```bash
python scripts/evaluate_kg_extraction.py --cases tests/fixtures/kg-cases.jsonl
```

Extraction is deterministic and conservative: known identities, contextual/multiword person NER, bounded two-message pronoun coreference, stop-token rejection, and a numeric confidence floor.
