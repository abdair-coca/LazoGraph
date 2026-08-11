# LazoGraph

Local-first personal knowledge system that turns life data into searchable memories, an identity-aware knowledge graph, an evidence-backed wiki, and safe training exports.

LazoGraph started from [`acnlabs/persona-knowledge`](https://github.com/acnlabs/persona-knowledge) and now includes deterministic participant identity, recoverable ingestion, transactional rebuilds, functional smoke tests, conservative graph extraction, and PII-aware exports.

## Current capabilities

- Import WhatsApp, Telegram, Signal, iMessage, social archives, Markdown, JSON/JSONL, CSV, PDF, and Obsidian vaults.
- Parse localized Spanish WhatsApp timestamps, multiline messages, and narrow/non-breaking spaces.
- Identify the persona and contacts independently; canonicalize expanded compound names and resolve
  stable aliases without mixing authorship.
- Deduplicate messages and detect equivalent source backups before they corrupt derived layers.
- Store verbatim memories in MemPalace/ChromaDB and search them semantically by participant.
- Build a SQLite knowledge graph with participant, communication, relationship, entity, and confidence data.
- Build and lint six evidence-backed wiki pages.
- Rebuild vectors, graph, and wiki atomically with rollback.
- Diagnose all persisted layers and run functional post-rebuild smoke tests.
- Inspect and transactionally restore quarantined sources.
- Export authentic user/assistant pairs with `block`, `redact`, or explicit `allow` PII policies.
- Run a disposable end-to-end test on Windows, macOS, or Linux.
- Preview and import a chat through the packaged `lazo import` command with explicit participant
  selection and invariant validation.
- Ask grounded questions about one participant through `lazo ask`, with persisted citations,
  canonical alias isolation, confidence, and safe abstention.
- Preview and apply manual context through `lazo context`, with explicit authority levels,
  source hashes, PII warnings, idempotency, rollback, and grounded retrieval.
- Preview, apply, audit, and undo relationship corrections through an immutable ledger; effective
  graph queries and grounded answers honor user corrections without altering generated triples.
- Ask grounded questions about two people through the effective graph, with alias resolution,
  source-backed paths, temporal evidence, explicit facts/inferences, and safe abstention.

Current boundary: chat import, person-specific grounded answers, manual context, and knowledge
correction are accepted. Relationship questions are demo-ready and awaiting feedback. Structured
plans, suggestions, and relationship descriptions remain gated roadmap work.

## Architecture

```text
Raw life data
    |
    v
Adapters -> normalized messages -> immutable source backups
                                  |
                 +----------------+----------------+
                 |                |                |
                 v                v                v
          semantic memory   knowledge graph   participant profiles
          ChromaDB/SQLite       SQLite             JSON
                 |                |                |
                 +----------------+----------------+
                                  |
                                  v
                         evidence-backed wiki
                                  |
                                  v
                    PII-governed training export
```

See [Architecture](docs/ARCHITECTURE.md) for component boundaries, invariants, transactions, and privacy rules.

## Requirements

- Python 3.11+
- `mempalace >= 3.1.0`
- About 1–2 GB free disk for ChromaDB and its embedding model

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

On macOS/Linux, replace activation with `source .venv/bin/activate` and use `python` in the commands below.

## Quick start

Set an explicit private knowledge root. Dataset contents are not stored in the Git repository.

```powershell
$env:PYTHONUTF8='1'
$env:OPENPERSONA_KNOWLEDGE="$env:LOCALAPPDATA\LazoGraph\knowledge"
```

### 1. Preview the chat

```powershell
lazo import "C:\path\to\whatsapp.txt" `
  --slug sam `
  --persona "Samantha" `
  --dry-run
```

The preview shows adapter, participant candidates, persona/contact counts, rejected system notices,
duplicates, PII flags, and equivalent backups. It never writes.

### 2. Import

```powershell
lazo import "C:\path\to\whatsapp.txt" --slug sam --persona "Samantha"
```

Confirm after reviewing the same preflight. The command initializes a missing dataset, imports all
layers, then validates cross-layer invariants. Use `--yes` only for reviewed automation.

Existing script commands remain supported:

```powershell
python scripts/init_knowledge.py --slug sam --name "Samantha"
python scripts/ingest.py `
  --slug sam `
  --source "C:\path\to\whatsapp.txt" `
  --adapter chat_export `
  --persona-name "Samantha"
```

Equivalent active sources stop before any write. Use `--reconcile-equivalent-source` to preview and confirm recoverable replacement, or `--allow-equivalent-source` only when both sources are intentionally distinct.

### 3. Build derived knowledge

```powershell
python scripts/ingest.py --slug sam --rebuild-kg
python scripts/ingest.py --slug sam --rebuild-vectors
python scripts/build_wiki.py --slug sam --dry-run
python scripts/build_wiki.py --slug sam
python scripts/lint_wiki.py --slug sam
```

For one coordinated transaction:

```powershell
python scripts/rebuild_all.py --slug sam --atomic
```

Atomic rebuild runs vectors, graph, wiki, wiki lint, and functional smoke tests. Any failed stage restores the previous derived state.

### 4. Search memories and graph

```powershell
lazo ask "¿Qué cosas le gustan a Samantha?" --about Samantha --slug sam

python scripts/query_memory.py `
  --slug sam `
  --query "work and projects" `
  --participant "Sam" `
  --limit 5

python scripts/query_kg.py --slug sam --entity "Alex"
python scripts/query_kg.py --slug sam --path "Sam" "Alex"
python scripts/query_kg.py --slug sam --stats
```

`lazo ask` uses the offline extractive provider by default. It sends no data over the network.
Optional local generation uses `--provider ollama`. Hosted generation requires explicit
`--provider hosted` plus `LAZOGRAPH_HOSTED_URL`, `LAZOGRAPH_HOSTED_MODEL`, and
`LAZOGRAPH_HOSTED_API_KEY`; only selected evidence crosses that boundary.

`query_memory.py` returns ranked evidence, not a generated answer. Participant aliases resolve to canonical names before ChromaDB filtering.

### 5. Add manual context

Separate records with a blank line. Use a prefix to state the intended authority:

```text
ASSERT: Alex's birthday is March 14.

CONTEXT: Alex mentioned flowers while discussing gifts.

INFERENCE: Alex may prefer tulips.
```

`ASSERT`, `FACT`, or `HECHO` creates an explicit user assertion with confidence `1.0`.
`CONTEXT`, `NOTE`, or unprefixed text remains freeform context with confidence `0.75`.
`INFERENCE` remains an identified inference with confidence `0.5`.

```powershell
lazo context "C:\private\context.txt" --slug sam --dry-run
lazo context "C:\private\context.txt" --slug sam --apply
lazo ask "When is Alex's birthday?" --about Alex --slug sam
```

Each record must name exactly one known participant. Use `--about Alex` when the subject is implicit.
The preview shows classification, subject, authority, confidence, duplicates, PII flags, and source
hash without writing. Apply stores normalized evidence and vectors, validates invariants, and rolls
back newly created artifacts on failure. Repeating the same context leaves the dataset unchanged.

### 6. Correct generated relationship knowledge

Corrections replace one existing relationship with another in the effective graph. Preview is
mandatory before apply; ambiguous entities, unsupported relationship wording, and missing old
claims write nothing.

```powershell
lazo correct "Carlos is Juan's cousin, not his brother" --slug sam --dry-run
lazo correct "Carlos is Juan's cousin, not his brother" --slug sam --apply
lazo corrections --slug sam list
python scripts/query_kg.py --slug sam --entity Carlos
```

Generated SQLite triples and source backups remain unchanged. Each apply appends an auditable user
assertion/retraction record under the private dataset. Effective graph reads and `lazo ask` give
active corrections priority. Rebuilds preserve the ledger. Undo appends a reversal event:

```powershell
lazo corrections --slug sam undo <claim-id>
```

### 7. Ask about a relationship

Omit `--about` and name exactly two people in the question:

```powershell
lazo ask "Who is Alex and how is Alex related to Samantha?" --slug sam
lazo ask "¿Qué relación tengo con Alex?" --slug sam
```

The first-person form resolves the dataset persona when the other participant is unambiguous.
The answer separates facts from interpretation and includes the effective graph path, confidence,
analyzed period, and citations to original messages or user corrections. Membership-only
`participant_in` paths are not treated as relationships. Missing paths or unsupported graph edges
produce an abstention instead of an invented connection. Use `--debug` for the retrieval summary
or `--json` for the full `Answer` contract.

### 8. Diagnose and smoke-test

```powershell
python scripts/diagnose.py --slug sam
python scripts/diagnose.py --slug sam --json
python scripts/smoke_test.py --slug sam
```

`diagnose.py` reports the active knowledge root, dataset path, Git/schema version, message and participant totals, vector count, graph health, wiki health, export health, and cross-layer invariants.

### 9. Export safely

Exports block detected PII by default before creating output:

```powershell
python scripts/export_training.py --slug sam --output training\sam
```

Create a shareable redacted export:

```powershell
python scripts/export_training.py `
  --slug sam `
  --output training\sam-redacted `
  --pii-policy redact
```

Use `--pii-policy allow` only after explicit review. Redaction covers raw copies, conversations, profile, and probes; original private sources remain unchanged.

Export structure:

```text
training/
  raw/
  conversations.jsonl
  profile.md
  metadata.json
  probes.json
```

### 10. Run full end-to-end verification

```powershell
python scripts/e2e_test.py `
  --source "C:\path\to\whatsapp.txt" `
  --persona-name "Samantha" `
  --persona-query "Sam" `
  --contact-query "Alex" `
  --stage-timeout 900 `
  --pii-policy redact
```

The E2E workflow uses a disposable knowledge root, prints child stages immediately, validates all layers, retries cleanup for briefly locked Windows SQLite files, and removes temporary data. Add exact gates with `--expect-messages`, `--expect-persona-messages`, and `--expect-contact-messages`.

## Recovery and maintenance

Inspect source quarantine:

```powershell
python scripts/quarantine.py --slug sam list
python scripts/quarantine.py --slug sam show 20260807T120000Z
python scripts/quarantine.py --slug sam restore 20260807T120000Z
python scripts/quarantine.py --slug sam restore 20260807T120000Z --apply
```

Restoration is a dry run by default. `--apply` restores selected source files, rebuilds all affected derived layers, and rolls everything back on failure.

Metadata-only vector migration avoids re-embedding unchanged documents:

```powershell
python scripts/ingest.py --slug sam --migrate-vector-metadata --dry-run
python scripts/ingest.py --slug sam --migrate-vector-metadata
```

Evaluate graph extraction changes before rebuilding private data:

```powershell
python scripts/evaluate_kg_extraction.py --cases tests\fixtures\kg-cases.jsonl
```

See [Operations](docs/OPERATIONS.md) for routine workflows and failure recovery.

## Supported sources

| Source | Adapter | Detection |
|---|---|---|
| Obsidian / Markdown directories | `universal` | `.obsidian/` or `*.md` |
| GBrain exports | `universal` | Markdown/raw sidecars or JSON memories |
| Markdown, text, CSV, PDF | `universal` | File extension |
| JSONL / JSON | `universal` | File extension/schema |
| WhatsApp text export | `chat_export` | Localized timestamp pattern |
| Telegram `result.json` | `chat_export` | `chats` schema |
| Signal JSON | `chat_export` | `sender` + `body` |
| iMessage SQLite | `chat_export` | `message` + `handle` tables |
| X/Twitter archive | `social` | `data/tweets.js` |
| Instagram archive | `social` | `content/posts_1.json` |

See [Source formats](references/source-formats.md) for details.

## Command reference

| Script | Purpose |
|---|---|
| `lazo import` | Preview participants, safely initialize, import, and validate one chat |
| `lazo ask` | Answer about one participant or a supported two-person relationship with validated citations |
| `lazo context` | Preview or apply classified manual context with provenance and rollback |
| `lazo correct` | Preview or apply one relationship replacement through an immutable ledger |
| `lazo corrections` | List correction history or append a reversible undo event |
| `init_knowledge.py` | Initialize dataset or print basic stats |
| `ingest.py` | Parse, deduplicate, store, reconcile, migrate, and rebuild |
| `query_memory.py` | Participant-filtered semantic retrieval |
| `query_kg.py` | Entity lookup, shortest path, graph statistics |
| `build_wiki.py` | Deterministic evidence-backed wiki build |
| `lint_wiki.py` | Wiki links, evidence, contradiction, and coverage checks |
| `rebuild_all.py` | Coordinated rebuild with optional atomic rollback |
| `smoke_test.py` | Cross-layer functional verification |
| `diagnose.py` | Read-only persisted-state health report |
| `reconcile_sources.py` | Manual authoritative-source reconciliation |
| `quarantine.py` | Inspect and transactionally restore quarantined sources |
| `export_training.py` | Versioned, hashed, PII-governed training export |
| `evaluate_kg_extraction.py` | Labeled precision/recall/F1 evaluation |
| `e2e_test.py` | Disposable full-system verification |

## Private data layout

```text
${OPENPERSONA_KNOWLEDGE}/{slug}/
  dataset.json
  participants.json
  .mempalace/
    palace/
      chroma.sqlite3
      knowledge_graph.sqlite3
  sources/
    .source-index.json
    quarantine/
  corrections/
    ledger.jsonl
  wiki/
    identity.md
    voice.md
    values.md
    thinking.md
    relationships.md
    timeline.md
    _schema.md
    _contradictions.md
    _changelog.md
    _evidence.md
```

Private datasets, vector stores, imports, exports, virtual environments, and secrets are excluded by `.gitignore`.

## Project status and roadmap

All defects discovered during the first real WhatsApp end-to-end validation are fixed and retained
as regression coverage.

Future product work follows the gated [Vertical Slice Roadmap](docs/VERTICAL_SLICES.md). Each slice
must reach a working demo, receive user feedback, and be explicitly accepted before the next slice
starts. See [PENDING.md](PENDING.md) for the next active item and completed repair history.

## License

MIT
