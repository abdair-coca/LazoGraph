---
name: persona-knowledge
description: "Operate LazoGraph: a local-first personal knowledge graph with semantic memory, participant identity, evidence wiki, recovery workflows, and PII-safe exports."
license: MIT
compatibility: "Python 3.11+ and mempalace >= 3.1.0. Windows, macOS, and Linux."
allowed-tools: Read Write Bash
metadata:
  version: "0.3.0"
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

## Phase 1: initialize

```bash
python scripts/init_knowledge.py --slug {slug} --name "Display Name"
```

Creates isolated metadata, participant profiles, MemPalace/ChromaDB storage, SQLite graph, source backup directory, and ten wiki pages.

## Phase 2: inspect and ingest

First run:

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

If an equivalent source exists, stop by default. Use:

```bash
python scripts/ingest.py ... --reconcile-equivalent-source
```

This quarantines equivalent active backups recoverably, stores the incoming authoritative replacement, and rebuilds all affected derived layers.

## Phase 3: rebuild and verify

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

## Phase 4: retrieve knowledge

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

Current limitation: these commands retrieve evidence and graph facts. Natural-language answer synthesis/RAG is not implemented yet.

## Phase 5: diagnose

```bash
python scripts/diagnose.py --slug {slug}
python scripts/diagnose.py --slug {slug} --json
python scripts/smoke_test.py --slug {slug}
```

Healthy completion requires matching source/message/profile/vector counts, readable graph, valid wiki, and five passing functional smoke probes.

## Phase 6: recover sources

```bash
python scripts/quarantine.py --slug {slug} list
python scripts/quarantine.py --slug {slug} show <batch>
python scripts/quarantine.py --slug {slug} restore <batch>
python scripts/quarantine.py --slug {slug} restore <batch> --apply
```

Restore is a plan unless `--apply` is supplied. Apply refuses active filename conflicts, restores source-index metadata, rebuilds affected layers, and rolls back source plus derived state after failure.

## Phase 7: export

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

## Phase 8: end-to-end test

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
