# Spec: wiki-schema

> Source: `references/wiki-schema.md`, `scripts/build_wiki.py`, `scripts/lint_wiki.py`
> Change: `docs/changes/docs-sdd-baseline`

Resumen ES: Wiki derivada con páginas, niveles evidencia y lint.

## Requirements

### REQ-WS-001: Derived layer
Wiki SHALL be derived from `sources/*.jsonl` + participants/vector graph; `sources/` remains source of truth. Corruption SHALL be recoverable via re-ingest.

### REQ-WS-002: Six content pages
Builder SHALL deterministically generate `identity.md, voice.md, values.md, thinking.md, relationships.md, timeline.md` from persona-authored messages only, using template `# {Title} > scope ## Content ## Sources ## See also` with `[L?:source]` tags and `[[backlinks]]`.

### REQ-WS-003: Evidence levels
Claims SHALL be tagged `L1 [L1:whatsapp]` direct quote, `L2 [L2]` paraphrase, `L3 [L3:inferred]`, `L4 [L4:inspired]`; each content page SHALL have >=2 evidence tags to be considered populated.

### REQ-WS-004: System pages and update protocol
System pages SHALL be `_schema.md, _contradictions.md, _changelog.md, _evidence.md`. Contradictions SHALL not overwrite, add entry in `_contradictions.md` with both claims and status. KG-driven `relationships.md`/`timeline.md` regeneration SHALL preserve annotations and log to `_changelog.md`.

### REQ-WS-005: Health bar and lint
Healthy wiki SHALL have all pages >=2 tags, zero unresolved contradictions >1 ingestion cycle, each page >=1 backlink, `_changelog` entries per ingestion, `_evidence` counts current. `lint_wiki.py` SHALL check links, stubs, contradictions, evidence density, coverage, changelog health.

## Scenarios

### Scenario: Build from persona messages
Given 3 persona messages about voice
When `build_wiki.py --slug sam`
Then `voice.md` contains >=2 `[L1` or `[L2` tags and `[[relationships]]` backlink

### Scenario: Contradiction handling
Given existing claim `likes coffee L1` and new `dislikes coffee L1`
When ingested
Then `_contradictions.md` adds topic with both claims, status unresolved

### Scenario: Lint healthy
Given compliant wiki
When `lint_wiki.py --slug sam`
Then exit 0, no `stale` warning

### Scenario: Lint missing backlink
Given page without `[[`
When lint
Then warning `missing backlink`
