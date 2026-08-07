# persona-knowledge

Persistent, incremental, searchable persona knowledge base — the **data layer** between raw sources and persona training.

## What it does

```
Data sources                  persona-knowledge                 Downstream consumers
───────────────          →   ──────────────────────      →   ──────────────────────
Obsidian vault                Storage: MemPalace              anyone-skill
GBrain export                 Graph: Knowledge Graph            (4D extraction)
WhatsApp / Telegram           Knowledge: Karpathy Wiki        persona-model-trainer
X (Twitter) / Instagram       Export: training/                 (fine-tuning)
iMessage / Signal
.md / .txt / .csv / .pdf
.jsonl / .json
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│                persona-knowledge                   │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ MemPalace│  │Knowledge │  │  Karpathy    │  │
│  │ (ChromaDB│  │  Graph   │  │  LLM Wiki    │  │
│  │ +SQLite) │  │ (SQLite) │  │  (Markdown)  │  │
│  └────┬─────┘  └────┬─────┘  └──────┬───────┘  │
│       │              │               │           │
│       └──────────────┼───────────────┘           │
│                      │                           │
│              ┌───────┴───────┐                   │
│              │   Export      │                   │
│              │  training/    │                   │
│              └───────────────┘                   │
└─────────────────────────────────────────────────┘
```

**Four layers:**

| Layer | Technology | Role |
|-------|-----------|------|
| **Storage** | MemPalace (ChromaDB + SQLite) | Verbatim content, semantic search |
| **Graph** | MemPalace Knowledge Graph | Entity-relationship graph with temporal validity |
| **Knowledge** | Karpathy LLM Wiki (interlinked .md) | LLM-maintained structured knowledge accumulation |
| **Export** | `export_training.py` | Generate `training/` for persona-model-trainer |

## Quick start

### Requirements

- Python >= 3.11
- `pip install mempalace` (~1-2 GB disk for ChromaDB)

### 1. Initialize

```bash
python scripts/init_knowledge.py --slug sam --name "Samantha"
```

### 2. Ingest data

```bash
# WhatsApp chat
python scripts/ingest.py --slug sam --source ~/whatsapp-export.txt --persona-name "Samantha"

# Twitter archive
python scripts/ingest.py --slug sam --source ~/twitter-archive/ --persona-name "Sam"

# Obsidian vault
python scripts/ingest.py --slug sam --source ~/obsidian-vault/

# Generic JSONL
python scripts/ingest.py --slug sam --source data.jsonl --persona-name "Sam"

# Dry run (parse without writing)
python scripts/ingest.py --slug sam --source data.txt --dry-run
```

### 3. Build wiki

Build all six persona pages from messages authored by the independently identified
persona. Evidence references point to exact source-backup lines; private content
never leaves the local machine.

```bash
python scripts/build_wiki.py --slug sam --dry-run
python scripts/build_wiki.py --slug sam
python scripts/lint_wiki.py --slug sam
```

The deterministic builder provides a verified baseline. Human or agent review can
add nuance later while keeping the evidence protocol in `wiki/_schema.md`.

### 4. Export for training

```bash
python scripts/export_training.py --slug sam --output training/
```

Exports block detected PII by default before creating output. Choose redaction for shareable
artifacts; use `allow` only after explicit review:

```bash
python scripts/export_training.py --slug sam --output training/ --pii-policy redact
python scripts/export_training.py --slug sam --output training/ --pii-policy allow
```

Redaction covers raw copies, conversations, profile, and probes. Original private dataset files
remain unchanged. Export metadata records detected types, policy, and replacement totals.

Output:

```
training/
  raw/                    # authentic source files
  conversations.jsonl     # distilled Q-A pairs
  profile.md              # character sheet
  metadata.json           # stats
```

### 5. Lint wiki

```bash
python scripts/lint_wiki.py --slug sam
```

### 6. Query Knowledge Graph

```bash
python scripts/query_kg.py --slug sam --entity "Tom"
python scripts/query_kg.py --slug sam --path "Tom" "Alice"
python scripts/query_kg.py --slug sam --stats
python scripts/query_memory.py --slug sam --query "work projects" --participant "Sam"
```

KG extraction combines explicit relationship cues with conservative person NER and bounded
pronoun coreference. Every generated relationship carries numeric confidence; low-confidence
candidates are rejected. Evaluate changes against labeled JSONL before rebuilding production:

```bash
python scripts/evaluate_kg_extraction.py --cases tests/fixtures/kg-cases.jsonl
```

Participant aliases are stored in private `participants.json` profiles. Repeated
name variants can resolve to the same canonical person without mixing authorship.
After upgrading an existing dataset, add sender metadata to its semantic index:

```bash
python scripts/ingest.py --slug sam --migrate-vector-metadata --dry-run
python scripts/ingest.py --slug sam --migrate-vector-metadata
```

This path updates metadata only; embeddings remain unchanged. If vector IDs differ
from authoritative sources, the command stops and requires `--rebuild-vectors`.
Full vector rebuilds print progress, elapsed time, and ETA after every 128-message batch.

Inspect recoverable source quarantine, preview a restore, then apply it transactionally:

```bash
python scripts/quarantine.py --slug sam list
python scripts/quarantine.py --slug sam show 20260807T120000Z
python scripts/quarantine.py --slug sam restore 20260807T120000Z
python scripts/quarantine.py --slug sam restore 20260807T120000Z --apply
```

Applied restoration rebuilds vectors, participant profiles, KG, and counters. Failure restores
both source location and derived state. Active filename conflicts stop before any write.

### 7. Coordinated atomic rebuild

Rebuild vectors, KG, wiki, and run wiki lint under one exclusive dataset lock:

```bash
python scripts/rebuild_all.py --slug sam --atomic
```

With `--atomic`, affected layers are snapshotted to a private temporary directory and
restored after any failed stage or keyboard interruption. Omit the flag to keep successful
partial stages when a later stage fails.

The final rebuild stage runs cross-layer smoke tests for canonical aliases, persona/contact
KG connectivity, participant-filtered semantic search, wiki lint, and complete export pairs.
Run it independently when needed:

```bash
python scripts/smoke_test.py --slug sam
```

### 8. Diagnose persisted state

Inspect every persisted layer without changing data:

```bash
python scripts/diagnose.py --slug sam
python scripts/diagnose.py --slug sam --json
```

The report identifies the active knowledge root and dataset path, Git and dataset schema
versions, source/message and participant totals, vector and KG counts, wiki lint health,
latest export health, and cross-layer invariant failures. A critical health failure returns
a non-zero exit code; stale or not-yet-built derived artifacts remain explicit warnings.

### 9. End-to-end verification

Run the complete workflow in a disposable dataset: initialize, dry-run, ingest,
rebuild KG, build/lint wiki, query identities, export, validate counts, then remove
temporary data.

```bash
python scripts/e2e_test.py \
  --source ~/whatsapp-export.txt \
  --persona-name "Samantha" \
  --persona-query "Sam" \
  --contact-query "Alex"
```

Optional exact-count gates: `--expect-messages`, `--expect-persona-messages`, and
`--expect-contact-messages`. Every child stage uses immediate unbuffered output and a
900-second default timeout; override it with `--stage-timeout`. Temporary state is removed
with Windows-safe retries. E2E exports use `--pii-policy redact` by default. Use `--keep-temp`
only when debugging a failed run.

## Supported sources

Three adapters cover all formats:

| Source | Adapter | Auto-detected |
|--------|---------|---------------|
| Obsidian vault | `universal` | `.obsidian/` or `*.md` directory |
| GBrain export | `universal` | Markdown dir with `.raw/` sidecars |
| `.md` / `.txt` / `.csv` / `.pdf` | `universal` | File extension |
| `.jsonl` / `.json` | `universal` | File extension |
| WhatsApp `.txt` | `chat_export` | Timestamp pattern |
| Telegram `result.json` | `chat_export` | `chats` JSON key |
| Signal JSON | `chat_export` | `sender`+`body` format |
| iMessage `.db` | `chat_export` | SQLite tables |
| X (Twitter) archive | `social` | `data/tweets.js` |
| Instagram archive | `social` | `content/posts_1.json` |

## Data storage

```
~/.openpersona/knowledge/{slug}/
  dataset.json                # metadata + stats
  participants.json           # canonical people, roles, aliases, activity ranges
  .mempalace/                 # MemPalace local data
    palace/                   # ChromaDB + KG
  sources/                    # immutable source backups (JSONL)
    .source-index.json        # per-file metadata
  wiki/                       # Karpathy wiki (derived from MemPalace)
    _schema.md
    identity.md
    voice.md
    values.md
    thinking.md
    relationships.md          # KG-generated
    timeline.md               # KG-generated
    _contradictions.md
    _changelog.md
    _evidence.md
```

## Dependency chain

```
persona-knowledge   →   anyone-skill   →   persona-model-trainer
(data management)     (distillation)     (fine-tuning)
```

- `persona-knowledge` is optional — `anyone-skill` works standalone
- When present, `anyone-skill` uses `persona-knowledge` for persistent storage and semantic search
- `persona-model-trainer` consumes the `training/` export directly

## License

MIT
