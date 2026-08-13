# LazoGraph architecture

## Goals

LazoGraph converts private life records into four usable representations while preserving provenance and recoverability:

1. Verbatim semantic memory.
2. Canonical participant identity.
3. Entity/relationship graph.
4. Evidence-backed wiki and training export.

The system is deterministic where possible. Grounded person and relationship answers use a
provider-neutral boundary; offline extractive synthesis is the default.

## Data flow

```text
source
  -> adapter parsing or manual-context classification
  -> sender boundary validation
  -> focal persona resolution
  -> PII scan
  -> equivalent-source preflight
  -> content deduplication
  -> normalized messages
       -> sources/*.jsonl
       -> ChromaDB vectors
       -> participants.json
       -> knowledge_graph.sqlite3
       -> plans/projection.json
       -> wiki/*.md
       -> versioned export
```

## Components

### Product CLI

`lazo import` owns Slice 1 orchestration. Its preflight parses without mutation, resolves exactly
one focal participant, shows trust-relevant counts, and stops on ambiguity or equivalent backups.
After confirmation it delegates initialization and persistence to existing script modules, then
runs dataset invariants. Legacy `scripts/*.py` commands remain supported wrappers.

`lazo ask` owns Slice 2 orchestration. It resolves one canonical profile, applies its sender filter
inside vector retrieval, rejects mismatched or unpersisted hits, ranks a bounded evidence set,
adds safe KG/wiki metadata, calls an `LLMProvider`, then validates every returned citation.

`lazo context` owns Slice 3 orchestration. Its dry-run separates UTF-8 blocks, classifies explicit
assertions, freeform notes, and declared inferences, resolves exactly one canonical subject per
record, scans PII, computes a full source hash, and checks exact deduplication. Apply revalidates
the hash, writes normalized `user_context` records and vectors, rebuilds profiles and counters,
then checks invariants. A failed apply restores metadata/source snapshots and removes only vectors
created by that attempt.

`lazo correct` owns Slice 4 orchestration. It parses one conservative English or Spanish
relationship replacement, resolves both endpoints exactly, verifies the old claim against the
effective graph, scans PII, and prints the exact assertion/retraction plan without writing. Apply
revalidates the plan under an exclusive ledger lock and appends an immutable correction event.
`lazo corrections list` exposes audit history; `lazo corrections undo <claim-id>` appends a
reversal event rather than deleting history.

When `lazo ask` is called without `--about`, Slice 5 resolves exactly two canonical participants,
loads the effective graph, finds a supported non-membership path, indexes active source messages
once, and selects path and temporal evidence. It then calls the same provider boundary and
validates citations. First-person questions may use the unique dataset persona as one endpoint.

Slice 6 adds `lazo plans list|show` and explicit pending-plan routing in `lazo ask`. Imports and
coordinated rebuilds extract plans from active source backups into an atomically replaced
`plans/projection.json`; list/show and pending-plan answers never mutate source data.

### Adapters

Adapters emit one normalized schema:

```json
{
  "role": "assistant",
  "content": "message text",
  "timestamp": "2026-08-07T12:00:00",
  "source_file": "chat.txt",
  "source_type": "whatsapp",
  "metadata": {"sender": "Canonical Sender"}
}
```

The persona is represented as `assistant`; other conversation participants are `user`. `metadata.sender` preserves independent authorship.

Manual context uses `source_type=user_context`. For participant-isolated retrieval,
`metadata.sender` and `metadata.subject` name the person the evidence concerns;
`metadata.authored_by=dataset_owner` preserves actual authorship. `record_kind`, `authority`,
`confidence`, `source_sha256`, record number, and import time keep the evidence auditable. The
import time is not used as the event timestamp, so manual additions do not extend chat chronology.

### Source backups

Normalized JSONL files under `sources/` are the authoritative active message layer. Original raw inputs remain outside the dataset unless an operator keeps them separately.

Large equivalent sources are detected using normalized message overlap and size ratio. Small sources require an exact match. Reconciliation moves replaced backups into timestamped quarantine directories with manifests and source-index snapshots.

### Semantic memory

MemPalace stores messages in a persistent ChromaDB collection. Vector IDs derive deterministically from dataset slug plus normalized message content. Canonical sender metadata supports participant-filtered semantic search.

Metadata-only migration updates sender metadata without submitting documents or embeddings. Full rebuild prunes vector IDs absent from authoritative sources.

### Participant identity

`participants.json` contains canonical name, identity type, aliases, role counts, activity range, and contributing sources. Exact sender evidence creates profiles. Conservative repeated-name heuristics add aliases without merging independently authored identities.

Capitalized runs may contain up to six tokens so compound Hispanic names are not truncated. A long
run is accepted only when its tokens map unambiguously to one known participant; unknown-name NER
remains capped at three tokens. Rebuild removes historical orphan entities that are expanded
shadows of a canonical participant. Entity queries prioritize a unique canonical participant
prefix and reject abbreviations shared by multiple participants.

### Knowledge graph

The SQLite graph stores entities and triples. Generated relationship triples use adapter name
`persona-knowledge`, allowing rebuilds to replace generated relationships while preserving manual
triples. Plan projection triples use the separate `lazograph-plans` adapter so they can be replaced
atomically without touching generated relationships or effective user corrections.

Generated relationship confidence:

- `1.0`: participant membership and observed communication.
- `0.95`: explicit romantic evidence.
- `0.96`: explicit named relationship phrase.
- `0.84`: bounded pronoun coreference.

Person extraction combines known participants, contextual cues, conservative multiword NER, stop-token rejection, and a minimum confidence threshold. Coreference expires after two messages from the same persona sender.

Plan projection adds stable `plan:<id>` nodes and source-backed `plan_participant` and
`plan_location` edges. Lifecycle status (`proposed`, `pending`, `scheduled`, `completed`, or
`cancelled`) remains a structured Plan field, never a graph entity. Relationship traversal excludes
`plan_` edges, preventing plan membership from being mistaken for a personal relationship.

### Pending plans

`Plan` records are immutable-shaped derived values with deterministic IDs based on normalized title,
participants, timezone-aware proposal time, and source IDs. Every lifecycle transition carries
timezone-aware occurrence time, source IDs, confidence, and provenance. The extractor resolves
relative dates in the dataset's declared IANA timezone and withholds ambiguous identities,
duplicates, terminal updates, and invalid transitions as unresolved rather than guessing.

`dataset.json` must declare a valid IANA `timezone` (new datasets default to `UTC`). The projection
stores schema version and timezone, rejects mismatches or corrupt records, uses an exclusive lock,
and replaces the complete JSON atomically. Source IDs remain line-addressable so pending-plan
answers can cite the creation and latest transition evidence.

### Effective knowledge and correction ledger

Generated SQLite triples remain the rebuildable base graph. User corrections live separately in
`corrections/ledger.jsonl`, a private append-only JSONL ledger. Each correction records stable
semantic claim IDs, the original input, assertion, retraction, authority, timestamp, provenance,
and superseded claim. Undo records reference earlier events and never erase them.

```text
effective graph = generated graph
                - active retractions
                + active user assertions
```

User assertions have confidence `1.0` and override generated claims only during reads. Stable claim
IDs do not depend on source filenames or extraction timestamps, so rebuilding the generated graph
does not orphan corrections. A ledger lock plus preview fingerprint prevents two stale previews
from silently replacing the same claim differently. Corrupt or ambiguous correction state fails
closed. `query_kg.py`, diagnosis, smoke tests, and person answers all consume the same effective
projection.

### Grounded answers

Stable contracts live under `src/lazograph/domain/`:

- `Evidence`: persisted message ID, subject/sender, source, timestamp, excerpt, score, and optional
  manual-context provenance.
- `Answer`: text, validated Evidence citations, confidence, entities, retrieval summary, explicit
  fact statements, and explicitly labeled inferences.
- `LLMProvider`: provider-neutral generation from selected evidence and whitelisted metadata.

Default `local` mode quotes only verified evidence and never uses network access. `ollama` stays on
the configured local endpoint. `hosted` requires explicit URL, model, and API key; prompt assembly
whitelists minimal profile metadata and sends only the selected evidence budget. Missing, weak,
contradictory, cross-participant, or uncitable evidence produces abstention or a hard error.

Manual context and active corrections remain subject-filtered like chat evidence. Local output
labels them as stored evidence rather than claiming the subject authored them. Correction evidence
uses `source_type=user_correction`, `authority=user`, and an auditable claim ID. Hosted providers
receive only selected excerpts and safe provenance fields, never local paths or source hashes.

Relationship mode uses the effective graph, including active corrections. `participant_in` is
excluded from traversable relationship paths because shared dataset membership does not establish
a personal relationship. Every generated path edge must have supporting source evidence;
correction edges cite their ledger record. Direct queries retain all supported endpoint relations,
while indirect queries choose a bounded shortest path. Earliest and latest endpoint evidence make
the analyzed period explicit. Missing paths, missing support, or insufficient evidence budget
causes abstention. Facts and interpretations remain separate in both rendered and JSON output.

Hosted relationship generation receives only selected evidence plus canonical entity names,
relationship types, hop count, path labels, and observed period. It does not receive local paths,
raw source files, or unrelated participant messages.

### Wiki

`build_wiki.py` deterministically builds six content pages from persona-authored messages:

- `identity.md`
- `voice.md`
- `values.md`
- `thinking.md`
- `relationships.md`
- `timeline.md`

Evidence tags preserve source traceability. System pages define schema, contradictions, change history, and evidence counts. `lint_wiki.py` checks links, stubs, contradictions, evidence density, source coverage, and changelog health.

### Export

`export_training.py` produces authentic alternating user/assistant pairs; it never invents prompts for assistant-only content. Each export records version, conversation hash, source snapshot, quality report, and PII policy.

PII modes:

- `block`: default; fail before output creation.
- `redact`: replace supported PII in all content artifacts.
- `allow`: explicit operator acceptance; preserve content.

## Consistency invariants

After persistent writes, LazoGraph verifies:

```text
unique active source messages
  = dataset.json total_messages
  = participants.json summed message_count
  = ChromaDB vector count
```

Assistant counts and active source counts must also match. Export source snapshots must describe the active source set. An older export after source changes is stale, not corrupt.

## Transactions and locks

`rebuild_all.py --atomic` uses an exclusive `.rebuild.lock`. It snapshots:

- `.mempalace/palace/`
- `participants.json`
- `dataset.json`
- `plans/`
- `wiki/`

Any stage failure or keyboard interruption restores exact prior state and removes paths created during the failed transaction.

Quarantine restoration uses the same lock and snapshots derived layers plus source-index state. A failed rebuild moves restored sources back into quarantine.

## Verification layers

### Unit/regression suite

Tests cover localized parsing, source equivalence, reconciliation, vector compatibility, graph
extraction, lifecycle-aware plans, read-only plan interfaces, plan KG projection, wiki, exports,
Windows runtime, quarantine rollback, and PII policy.

### Smoke tests

`smoke_test.py` probes:

1. Canonical alias resolution.
2. Persona/contact KG path.
3. Participant-filtered semantic retrieval.
4. Wiki lint.
5. Complete user/assistant export pairs.

### Diagnosis

`diagnose.py` reads all persisted layers without mutation and returns non-zero only for critical corruption. Stale or not-yet-built derived artifacts are warnings.

### Disposable E2E

`e2e_test.py` exercises raw parsing through export inside a temporary root. It supports exact message gates, per-stage timeouts, unbuffered output, PII policy, debug preservation, and Windows cleanup retries.

## Privacy boundary

Private data lives below `OPENPERSONA_KNOWLEDGE`, outside Git. Repository `.gitignore` excludes common local datasets, correction ledgers, imports, vector stores, exports, virtual environments, and secrets.

Semantic search and graph/wiki building are local. `query_memory.py` may download the configured
embedding model on first use. The default answer provider is offline. Ollama stays local; hosted
generation is opt-in and receives only the selected evidence budget.
