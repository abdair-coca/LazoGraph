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

Participant aliases are stored in private `participants.json` profiles. Repeated
name variants can resolve to the same canonical person without mixing authorship.
After upgrading an existing dataset, add sender metadata to its semantic index:

```bash
python scripts/ingest.py --slug sam --migrate-vector-metadata --dry-run
python scripts/ingest.py --slug sam --migrate-vector-metadata
```

This path updates metadata only; embeddings remain unchanged. If vector IDs differ
from authoritative sources, the command stops and requires `--rebuild-vectors`.

### 7. End-to-end verification

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
`--expect-contact-messages`.

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
