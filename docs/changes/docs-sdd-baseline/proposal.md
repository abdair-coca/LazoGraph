# Proposal: docs-sdd-baseline

## Intent

LazoGraph has 8 accepted slices, stable architecture, and thorough docs (`ARCHITECTURE.md`, `OPERATIONS.md`, `VERTICAL_SLICES.md`), but lacks formal SDD specs and auditable history. Docs are narrative-only; no `Requirement SHALL` + `Scenario` contract, no per-capability spec, no `tasks.md` linking commits to acceptance. LLMs must read 1000+ lines to answer. Baseline converts narratives to hybrid SDD docs (`docs/` + Engram) without code changes.

## Scope

### In Scope
- 12 specs under `docs/specs/` (8 slices + architecture, operations, source-formats, wiki-schema)
- `docs/changes/docs-sdd-baseline/` with `proposal.md`, `specs.md`, `tasks.md`
- `docs/README.md` human index (ES) linking specs/changes
- Refresh `.atl/skill-registry.md` and persist `sdd/lazograph/testing-capabilities` hybrid
- Engram mirrors `sdd/docs-sdd-baseline/*` for token-efficient retrieval

### Out of Scope
- Code changes in `src/`, `adapters/`, `scripts/`
- Rewriting `ARCHITECTURE.md`/`OPERATIONS.md`/`VERTICAL_SLICES.md` (they remain source of truth)
- New slices, refactors, or `openspec/` creation
- Automated migration of legacy git history beyond linking commits

## Capabilities

### New Capabilities
- `import-chat`: single-command chat import with preflight
- `ask-person`: grounded person QA with citations
- `add-context`: manual context with authority levels
- `correct-knowledge`: relationship correction ledger
- `ask-relationship`: effective-graph relationship QA
- `pending-plans`: lifecycle plans with timezone-aware dates
- `grounded-suggestions`: preference-grounded suggestions
- `describe-relationship`: time-bounded relationship summaries
- `architecture`: invariants, transactions, privacy boundary
- `operations`: rebuild, diagnose, smoke, quarantine
- `source-formats`: adapter contracts
- `wiki-schema`: evidence levels and page templates

### Modified Capabilities
- None (baseline is additive)

## Approach

Extract `Requirement` + `Scenario` from `VERTICAL_SLICES.md` acceptance criteria and `ARCHITECTURE.md` invariants. Keep `docs/` as SDD root (custom vs `openspec/` default), document deviation in `README.md`. Specs in English (SHALL), human index in Spanish. Hybrid persistence: Engram topic `sdd/docs-sdd-baseline/*` mirrors filesystem for fast LLM retrieval.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `docs/specs/*` | New | 12 spec files, English, traced to source docs |
| `docs/changes/docs-sdd-baseline/*` | New | proposal/specs/tasks baseline history |
| `docs/README.md` | New | Spanish index for humans |
| `.atl/skill-registry.md` | Modified | Timestamp refresh |
| `sdd/lazograph/*` (Engram) | New | testing-capabilities + baseline mirrors |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Drift `docs/` vs `specs/` | Medium | `docs/README.md` states sync rule; verify links in CI |
| Deviation from `openspec/` convention confuses tooling | Low | Document custom root in README + proposal |
| Incomplete traceability | Low | Cite `file:line` for every requirement |

## Rollback Plan

`git revert` or `Remove-Item docs/specs, docs/changes/docs-sdd-baseline, docs/README.md` + restore `.atl/skill-registry.md`. Engram entries remain but are versioned via topic_key upsert. No code rollback needed.

## Dependencies

- Existing docs as sources; no external service
- Engram available for hybrid save (fallback to filesystem-only if expired)

## Success Criteria

- [ ] 12 specs created, each with >=1 Requirement SHALL + >=1 Scenario
- [ ] `docs/changes/docs-sdd-baseline/{proposal,specs,tasks}.md` present and <450 words for proposal
- [ ] `docs/README.md` Spanish index links all specs/changes
- [ ] `.atl/skill-registry.md` refreshed (date >=2026-08-31)
- [ ] Engram mirrors saved (or filesystem-only noted)
- [ ] `pytest -q` still passes (no code touched)
