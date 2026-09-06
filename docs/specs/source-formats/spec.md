# Spec: source-formats

> Source: `references/source-formats.md`, `adapters/universal.py`, `adapters/chat_export.py`, `adapters/social.py`
> Change: `docs/changes/docs-sdd-baseline`

Resumen ES: Contratos de adapters y detección para todas las fuentes soportadas.

## Requirements

### REQ-SF-001: Adapter registry
System SHALL expose three adapters: `universal` (extension/directory), `chat_export` (timestamp pattern/schema/SQLite), `social` (archive structure). Auto-detection SHALL follow table in `references/source-formats.md:5-14`.

### REQ-SF-002: WhatsApp localized parsing
`chat_export` SHALL parse localized Spanish `a. m./p. m.`, optional seconds, bracket layouts, narrow/non-breaking spaces (`U+00A0`, `U+202F`), multiline messages, and reject system notices even with colon at shared boundary.

### REQ-SF-003: Telegram/Signal/iMessage schemas
Telegram SHALL require top-level `chats.list` with `from/text/date`; Signal SHALL require array with `sender`+`body`; iMessage SHALL read SQLite `message`+`handle` tables via `sqlite3`.

### REQ-SF-004: Universal flexibility
Universal SHALL handle Obsidian vault (`.obsidian/`), GBrain exports (`.raw/` sidecars), `.md`/`.txt` (paragraphs >=20 chars split by double newline), `.csv` (auto-detect speaker/content columns), `.pdf` (`pdfplumber`/`PyPDF2`), `.json/.jsonl` (flexible field names `content|text|message` etc). Role mapping: `persona=assistant`, others `user`.

### REQ-SF-005: Unified output
All adapters SHALL emit `{role, content, timestamp, source_file, source_type, metadata:{sender}}` preserving `metadata.sender` for identity without role ambiguity.

## Scenarios

### Scenario: WhatsApp Spanish timestamp
Given line `7/8/24, 9:41 p. m. - Juan: Hola` with `U+202F`
When parsing
Then timestamp `2024-08-07T21:41:00` sender `Juan` content `Hola`

### Scenario: System notice rejected
Given notice `Messages are end-to-end encrypted` with colon
When boundary validation
Then rejected before dedup/vectors/KG

### Scenario: CSV auto-detect
Given CSV headers `sender, message`
When universal parsing
Then rows become messages with role via `--persona-name` match

### Scenario: Unified schema
Given any adapter output
When inspected
Then JSON has all six fields and `metadata.sender` equals canonical sender
