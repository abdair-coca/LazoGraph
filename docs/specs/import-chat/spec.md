# Spec: import-chat

> Source: `docs/VERTICAL_SLICES.md:205-298` Slice 1 Accepted (`c6d90eb`, 2026-08-08), `docs/ARCHITECTURE.md:38-43`, `README.md:88-124`
> Change: `docs/changes/docs-sdd-baseline`

Resumen ES: Importar un chat con preview no mutante, resolver persona focal, validar PII/equivalencia y persistir invariantes.

## Requirements

### REQ-IC-001: Non-mutating preflight
System SHALL expose `lazo import <path> --slug <s> --persona <name> --dry-run` that parses without writing and prints adapter, participant candidates, persona/contact counts, rejected system notices, duplicates, PII flags, equivalent backups.

### REQ-IC-002: Focal persona resolution
System SHALL require exactly one focal persona match; ambiguous selection SHALL fail with exit 2 and write nothing.

### REQ-IC-003: Equivalent-source guard
System SHALL detect equivalent active backups via normalized content overlap + size ratio (large >=95% overlap, small exact) before any write and stop unless `--reconcile-equivalent-source` or `--allow-equivalent-source`.

### REQ-IC-004: Idempotent apply
Second import of same source SHALL report zero new messages and leave dataset unchanged.

### REQ-IC-005: Invariant validation
After any write, system SHALL verify `unique active source messages = dataset.json total_messages = participants.json sum = ChromaDB count` per `ARCHITECTURE.md:227-237`.

## Scenarios

### Scenario: Dry-run preview
Given a WhatsApp txt with Spanish `a. m./p. m.` and `U+00A0` spaces
When `lazo import --dry-run`
Then output includes `Parsed`, `Persona`, `Equivalent active sources: none` and no file is created

### Scenario: Ambiguous persona
Given participants `Alex` and `Alexandra` both match `--persona Alex`
When importing
Then exit 2, error `ambiguous focal-person`, zero writes

### Scenario: Equivalent detection
Given active backup covers 96% overlap
When importing duplicate export without reconcile flag
Then exit 2 with `Import stopped before writes`

### Scenario: Idempotency
Given dataset already contains source
When re-importing same file
Then `Already imported. Dataset unchanged.` and file hashes unchanged
