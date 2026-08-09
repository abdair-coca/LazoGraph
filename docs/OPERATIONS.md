# LazoGraph operations

## Standard environment

Windows PowerShell:

```powershell
$env:PYTHONUTF8='1'
$env:OPENPERSONA_KNOWLEDGE="$env:LOCALAPPDATA\LazoGraph\knowledge"
Test-Path "$env:OPENPERSONA_KNOWLEDGE\sam\dataset.json"
```

Keep this root outside the Git checkout.

## First import checklist

1. Run packaged dry-run.
2. Confirm adapter, participant candidates, role split, notices, duplicates, PII, and equivalence.
3. Apply through the same command; a missing dataset initializes automatically.
4. Re-run once to verify idempotency.
5. Diagnose.
6. Run smoke tests.
7. Export with `redact` when sharing.

```powershell
lazo import "C:\private\chat.txt" `
  --slug sam `
  --persona "Samantha" `
  --dry-run

lazo import "C:\private\chat.txt" --slug sam --persona "Samantha"
lazo import "C:\private\chat.txt" --slug sam --persona "Samantha"

python scripts/diagnose.py --slug sam
python scripts/smoke_test.py --slug sam
```

The second import must report zero new messages and leave the dataset unchanged. Existing
`init_knowledge.py` and `ingest.py` workflows remain supported for advanced or legacy operation.

## Ask about one participant

Default offline provider:

```powershell
lazo ask "¿Qué cosas le gustan a Samantha?" `
  --about Samantha `
  --slug sam
```

Use `--debug` for counts, filters, provider mode, and evidence budget without printing unrelated
participant content. Use `--json` for the complete `Answer` contract.

Optional local Ollama:

```powershell
$env:LAZOGRAPH_OLLAMA_MODEL='llama3.2'
lazo ask "¿Qué cosas le gustan a Samantha?" --about Samantha --slug sam --provider ollama
```

Explicit hosted boundary:

```powershell
$env:LAZOGRAPH_HOSTED_URL='https://provider.example/v1/chat/completions'
$env:LAZOGRAPH_HOSTED_MODEL='configured-model'
$env:LAZOGRAPH_HOSTED_API_KEY='secret'
lazo ask "¿Qué cosas le gustan a Samantha?" --about Samantha --slug sam --provider hosted
```

Hosted mode sends the question, canonical participant name, selected evidence, and whitelisted
profile metadata. It never sends the full dataset. Provider errors and invalid citations exit
non-zero without changing knowledge.

## Add manual context

Write UTF-8 text or Markdown with blank lines between records:

```text
ASSERT: Alex's birthday is March 14.

CONTEXT: Alex mentioned flowers while discussing gifts.

INFERENCE: Alex may prefer tulips.
```

Preview first:

```powershell
lazo context "C:\private\context.txt" --slug sam --dry-run
```

The preview must show the expected subject, record kind, authority, confidence, duplicate count,
PII flags, and SHA-256 source hash. `ASSERT`, `ASSERTION`, `FACT`, `HECHO`, and `AFIRMACION` are
explicit user assertions at confidence `1.0`. `CONTEXT`, `NOTE`, their Spanish equivalents, and
unprefixed blocks are freeform at `0.75`. `INFERENCE` and `INFERENCIA` remain inferences at `0.5`.

If text does not name exactly one known participant, set the subject explicitly:

```powershell
lazo context "C:\private\context.txt" --slug sam --about Alex --dry-run
```

Apply only after reviewing the same file:

```powershell
lazo context "C:\private\context.txt" --slug sam --apply
lazo ask "When is Alex's birthday?" --about Alex --slug sam
lazo context "C:\private\context.txt" --slug sam --apply
python scripts/diagnose.py --slug sam
```

The second apply must report `Already stored` and leave every dataset file unchanged. Apply stores
normalized context and vectors locally, records source hash/authorship/authority, and validates
cross-layer invariants. If persistence or validation fails, the command restores managed files and
deletes only vectors introduced by the failed attempt.

PII is reported during preview and stored only after explicit `--apply`. The default answer provider
remains offline. Explicit hosted mode receives only selected evidence and safe provenance, never
the local context path or source hash.

## Adding another source

Run `lazo import ... --dry-run` first. If equivalent-source preflight stops ingestion, do not use
`--allow-equivalent-source` until confirming both backups represent intentionally separate data.

To replace equivalent active backups:

```powershell
lazo import "C:\private\new-export.txt" `
  --slug sam `
  --persona "Samantha" `
  --reconcile-equivalent-source `
  --dry-run
```

Remove `--dry-run` only after reviewing the printed replacement plan.

## Rebuild choices

### Atomic full rebuild

```powershell
python scripts/rebuild_all.py --slug sam --atomic
```

Use after source reconciliation, code upgrades, graph extraction changes, or wiki logic changes.

### Vector-only rebuild

```powershell
python scripts/ingest.py --slug sam --rebuild-vectors
```

Use after authoritative source changes or vector ID drift. Progress, elapsed time, ETA, and flushed count print every 128 messages.

### Metadata-only migration

```powershell
python scripts/ingest.py --slug sam --migrate-vector-metadata --dry-run
python scripts/ingest.py --slug sam --migrate-vector-metadata
```

Use when only sender metadata schema changed. Command aborts if vector IDs drift; it never recomputes embeddings.

### Graph-only rebuild

```powershell
python scripts/ingest.py --slug sam --rebuild-kg
```

Generated triples are replaced; unmanaged/manual triples remain.

## Health interpretation

```powershell
python scripts/diagnose.py --slug sam
```

- `healthy`: all critical persisted layers agree.
- `warning`: dataset is usable, but an export is stale or a derived artifact is not built.
- `error`: counts diverge, a database is unreadable, wiki has structural issues, or export artifact is corrupt.

Machine-readable output:

```powershell
python scripts/diagnose.py --slug sam --json
```

Functional verification:

```powershell
python scripts/smoke_test.py --slug sam
```

All five probes should pass. Export pair check is reported as skipped when no export exists yet.

## Quarantine operations

List batches:

```powershell
python scripts/quarantine.py --slug sam list
```

Inspect manifest, size, line count, and SHA-256:

```powershell
python scripts/quarantine.py --slug sam show <batch>
```

Preview restore:

```powershell
python scripts/quarantine.py --slug sam restore <batch>
```

Apply:

```powershell
python scripts/quarantine.py --slug sam restore <batch> --apply
```

An active source with the same filename blocks restoration before writes.

## Export policy

### Default block

```powershell
python scripts/export_training.py --slug sam --output training\sam
```

If PII exists, command exits before creating output.

### Redacted export

```powershell
python scripts/export_training.py `
  --slug sam `
  --output training\sam-redacted `
  --pii-policy redact
```

Inspect `metadata.json -> pii` for detected types, policy, and replacement totals.

### Explicit unchanged export

```powershell
python scripts/export_training.py `
  --slug sam `
  --output training\sam-private `
  --pii-policy allow
```

Treat this directory as private. Older exports created before PII policies are not rewritten automatically.

## End-to-end test

```powershell
python scripts/e2e_test.py `
  --source "C:\private\chat.txt" `
  --persona-name "Samantha" `
  --persona-query "Sam" `
  --contact-query "Alex" `
  --expect-messages 1000 `
  --expect-persona-messages 600 `
  --expect-contact-messages 400 `
  --stage-timeout 900 `
  --pii-policy redact
```

Remove exact-count arguments when testing an evolving source. Add `--keep-temp` only to inspect a failed disposable run; the command prints its temporary path.

## Common failures

### No messages parsed

- Force `--adapter chat_export` for a chat export.
- Confirm file encoding and timestamp format.
- Spanish `a. m.` / `p. m.` plus `U+00A0` and `U+202F` spaces are supported.

### Equivalent source detected

- Preferred: reconcile with dry-run and recoverable quarantine.
- Use `--allow-equivalent-source` only for intentional overlap.

### No semantic results

- Confirm `OPENPERSONA_KNOWLEDGE` points to the expected root.
- Run `diagnose.py`.
- Rebuild vectors.
- Query with a canonical participant or stored alias.

### No graph path

- Confirm both aliases resolve with `query_kg.py --entity`.
- Rebuild graph.
- Inspect graph stats and confidence distribution.

### Stale export

Source state changed after export. Create a new redacted export; do not treat stale status as dataset corruption.

### Windows SQLite cleanup failure

E2E retries briefly locked files automatically. Close external database viewers. Use `--keep-temp` to preserve state when debugging.

## Current product boundary

LazoGraph imports chats, answers grounded questions about one participant, and adds auditable manual
context. The default answer is conservative and extractive; Ollama or an explicitly configured
hosted provider supplies generative synthesis. Natural-language corrections, relationship-wide
answers, structured plans, suggestions, and relationship descriptions remain planned slices.
