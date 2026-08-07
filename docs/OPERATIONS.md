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

1. Initialize dataset.
2. Dry-run raw source.
3. Confirm adapter, count, role split, sender names, and PII flags.
4. Ingest once.
5. Run atomic rebuild.
6. Diagnose.
7. Run smoke tests.
8. Export with `redact` when sharing.

```powershell
python scripts/init_knowledge.py --slug sam --name "Samantha"

python scripts/ingest.py `
  --slug sam `
  --source "C:\private\chat.txt" `
  --adapter chat_export `
  --persona-name "Samantha" `
  --dry-run

python scripts/ingest.py `
  --slug sam `
  --source "C:\private\chat.txt" `
  --adapter chat_export `
  --persona-name "Samantha"

python scripts/rebuild_all.py --slug sam --atomic
python scripts/diagnose.py --slug sam
python scripts/smoke_test.py --slug sam
```

## Adding another source

Run the same dry-run first. If equivalent-source preflight stops ingestion, do not use `--allow-equivalent-source` until confirming both backups represent intentionally separate data.

To replace equivalent active backups:

```powershell
python scripts/ingest.py `
  --slug sam `
  --source "C:\private\new-export.txt" `
  --persona-name "Samantha" `
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

LazoGraph can retrieve relevant memories and graph facts, but it does not generate a synthesized conversational answer. A future `ask`/chat layer should combine semantic retrieval, graph context, wiki context, citations, and an explicit local-or-hosted model privacy policy.
