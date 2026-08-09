# LazoGraph Vertical Slice Roadmap

> **Gated delivery document.** Slice 1's `lazo import` command is accepted. Slice 2's `lazo ask`
> command is implemented and awaiting feedback. Commands in Slices 3–8 remain planned and are not
> implemented. Existing
> `scripts/*.py` commands remain supported compatibility interfaces.

## Purpose

This roadmap evolves LazoGraph through complete user capabilities instead of rebuilding every
technical layer separately. Each slice must produce a testable command, a functional demo, and a
user decision before development may continue to the next slice.

The official implementation order is:

1. Import Chat
2. Ask About a Person
3. Add Manual Context
4. Correct Knowledge
5. Ask About Relationships
6. Pending Plans
7. Grounded Suggestions
8. Describe a Relationship

## Current baseline

LazoGraph already provides:

- localized chat parsing and system-notice rejection;
- persona/contact profiles and alias resolution;
- semantic memory with participant filtering;
- a persisted SQLite Knowledge Graph;
- evidence-backed wiki generation and linting;
- source equivalence detection and recoverable quarantine;
- atomic rebuild, diagnosis, smoke tests, and disposable E2E validation;
- authentic training exports with PII policies.

The current runtime now provides the packaged `lazo import` command for Slice 1. It does not yet
provide:

- LLM-backed answers with citations;
- manual context authority semantics;
- a reversible correction ledger;
- a structured plan model;
- grounded suggestions or relationship synthesis.

## Migration strategy

Development must remain incremental:

- Do not rewrite working parsers, storage, graph, wiki, recovery, or export systems.
- Add a minimal packaged `lazo` CLI during Slice 1.
- Keep `scripts/*.py` as compatible wrappers throughout migration.
- A feature owns use-case orchestration; shared infrastructure remains reusable.
- Extract code from scripts only when the active slice needs that boundary.
- Preserve private dataset layout and backward compatibility unless a slice explicitly includes a
  tested migration.

Target structure, introduced progressively:

```text
src/lazograph/
├── cli.py
├── features/
│   ├── import_chat/
│   ├── ask_person/
│   ├── add_context/
│   ├── correct_knowledge/
│   ├── ask_relationship/
│   ├── pending_plans/
│   ├── suggestions/
│   └── describe_relationship/
├── domain/
│   ├── evidence.py
│   ├── claims.py
│   ├── plans.py
│   └── identity.py
├── ports/
│   ├── memory.py
│   ├── graph.py
│   └── llm.py
└── infrastructure/
    ├── chroma/
    ├── sqlite/
    └── llm/
```

## Roadmap status

This table is the single source of truth for roadmap progress.

| Slice | Capability | Status | Availability | Acceptance |
|---:|---|---|---|---|
| 1 | Import Chat | Accepted | Available | Accepted |
| 2 | Ask About a Person | Awaiting Feedback | Demo ready | Pending |
| 3 | Add Manual Context | Planned | Locked by Slice 2 | Pending |
| 4 | Correct Knowledge | Planned | Locked by Slice 3 | Pending |
| 5 | Ask About Relationships | Planned | Locked by Slice 4 | Pending |
| 6 | Pending Plans | Planned | Locked by Slice 5 | Pending |
| 7 | Grounded Suggestions | Planned | Locked by Slice 6 | Pending |
| 8 | Describe a Relationship | Planned | Locked by Slice 7 | Pending |

## Mandatory feedback protocol

Every slice follows this state machine:

```text
Planned
  -> In Progress
  -> Demo Ready
  -> Awaiting Feedback
  -> Changes Requested
  -> Demo Ready
  -> Accepted
```

Rules:

1. Only one slice may be `In Progress`.
2. A slice reaches `Demo Ready` only after its automated tests and demo flow pass.
3. After presenting the demo, development stops at `Awaiting Feedback`.
4. Feedback changes remain inside the current slice; later slices stay locked.
5. Acceptance requires the exact phrase `Slice N accepted`, using the actual slice number.
6. The acceptance record must include date, implementation commit, test results, demo command,
   decision, and user notes.
7. Only an `Accepted` slice unlocks the next slice.
8. A later regression may reopen an accepted slice, but must record why and which later slices are
   affected.

The feedback gate is a delivery rule, not merely documentation. An implementation agent must stop
and wait after every slice demo.

## Planned shared contracts

These contracts are introduced by the first slice that needs them and then remain stable.

### Evidence

```text
Evidence:
  message_id: string
  sender: string
  source_file: string
  timestamp: datetime | null
  excerpt: string
  score: float
```

Evidence must resolve to persisted source material. Generated prose is never evidence.

### Answer

```text
Answer:
  text: string
  citations: Evidence[]
  confidence: float
  entities: string[]
  retrieval_summary: object
```

An answer without sufficient evidence must abstain instead of guessing.

### LLM provider

```text
LLMProvider:
  generate(question, evidence, policy) -> Answer
```

A local provider is the privacy-first default. Hosted providers require explicit configuration and
receive only selected evidence, never the complete dataset. Prompt logging is disabled by default.

### User claim

```text
UserClaim:
  id: string
  subject: entity reference
  predicate: string
  object: entity reference or literal
  action: assert | retract
  supersedes: claim IDs[]
  source_type: user_context | user_correction
  created_at: datetime
  confidence: 1.0
```

User claims are immutable and reversible. Effective knowledge is a projection, not destructive
editing of extracted triples.

### Plan

```text
Plan:
  id: string
  title: string
  status: proposed | pending | scheduled | completed | cancelled
  participants: entity references[]
  proposed_at: datetime
  scheduled_for: datetime | null
  location: string | null
  source_ids: string[]
  confidence: float
```

Plan status and dates are structured fields, not freeform graph entities.

---

## Slice 1 — Import Chat

**Status:** Accepted  
**Dependency:** Current ingestion baseline  
**Unlocks:** Slice 2

### Goal

Import one chat and separate the focal persona from contacts correctly through a single product
command.

### Implemented interface — awaiting feedback

```bash
lazo import chat.txt --slug sample --persona Samantha
```

The first import must preview parsing and participants before persistent writes. The final CLI may
use an explicit apply/confirmation step, but must preserve a non-mutating preview.

### Flow

```text
source
-> adapter
-> sender boundary validation
-> focal persona selection
-> PII scan
-> equivalent-source preflight
-> deduplication
-> vectors + normalized source backup + profiles + KG
-> dataset invariants
```

### Implementation requirements

- Wrap existing adapters and ingestion instead of rewriting them.
- Add minimal Python packaging and the `lazo` entry point.
- Keep existing ingestion scripts operational.
- Show adapter, participant candidates, persona/contact counts, rejected notices, duplicates, and
  PII flags before the first write.
- Reject ambiguous focal-person selection.
- Preserve equivalent-source confirmation and recoverable quarantine.

### Out of scope

- LLM answers.
- Manual context or corrections.
- New source formats unrelated to acceptance scenarios.

### Acceptance criteria

- Localized WhatsApp timestamps and multiline messages parse correctly.
- System notices never become participants.
- Persona and contact message counts match the fixture/source expectation.
- Reimport is idempotent.
- Equivalent backup detection stops before writes.
- Source, profile, vector, and dataset counters satisfy invariants.
- Existing ingestion commands remain compatible.

### Required tests and demo

- Unit tests for CLI arguments and participant preview.
- Integration test against localized chat fixture.
- Regression tests for notices, deduplication, and equivalent sources.
- Disposable E2E import with exact participant counts.

Planned demo:

```bash
lazo import sample-chat.txt --slug sample --persona Samantha
python scripts/diagnose.py --slug sample
```

### Feedback checklist

- [ ] Participant preview is understandable.
- [ ] Focal persona selection feels safe.
- [ ] Counts and warnings provide enough trust.
- [ ] Command syntax is comfortable.
- [ ] Reimport behavior is unsurprising.

### Acceptance record

| Field | Value |
|---|---|
| Decision | Accepted |
| Required phrase | `Slice 1 accepted` |
| Date | 2026-08-08 |
| Implementation commit | `c6d90eb` |
| Test results | 121 automated tests passed; localized fixture and equivalent-source regressions passed |
| Demo command | `lazo import <chat> --slug sample --persona Samantha`; repeat import; run `diagnose.py` |
| User notes | Real import, identity split, vectors, graph, diagnostics, and idempotent reimport confirmed |

---

## Slice 2 — Ask About a Person

**Status:** Awaiting Feedback
**Dependency:** Slice 1 accepted  
**Unlocks:** Slice 3

### Goal

Answer grounded questions about one known participant with verifiable citations.

### Implemented interface — awaiting feedback

```bash
lazo ask "What does Alex like?" --about Alex
```

Spanish questions and answers are required even though product documentation remains English.

### Flow

```text
question
-> canonical alias resolution
-> participant-filtered semantic retrieval
-> KG/wiki enrichment
-> evidence ranking and budget
-> LLM provider
-> citation validation
-> grounded answer or abstention
```

### Implementation requirements

- Introduce `Evidence`, `Answer`, and `LLMProvider` contracts.
- Use canonical sender filters before retrieval, not after answer generation.
- Keep retrieved participant evidence isolated from other identities.
- Validate that every citation points to persisted material included in the prompt.
- Provide retrieval/debug output without exposing unrelated private content.
- Use local inference by default; make hosted inference explicit and evidence-limited.
- Abstain when evidence is missing, contradictory, or too weak.

### Out of scope

- Relationship-wide synthesis.
- Suggestions.
- Persisting new conclusions as facts.

### Acceptance criteria

- Answers are in Spanish for Spanish questions.
- Claims are supported by citations.
- No cross-participant evidence leakage occurs.
- Unknown preferences produce abstention, not invention.
- Alias and canonical-name queries return equivalent results.
- Provider failure returns a clear, non-destructive error.

### Required tests and demo

- Fake-provider unit tests with deterministic output.
- Retrieval isolation tests for two participants.
- Citation existence and citation-coverage checks.
- Abstention corpus for unsupported questions.
- Hosted-provider policy test proving only selected evidence leaves the boundary.

Planned demo:

```bash
lazo ask "¿Qué cosas le gustan a Alex?" --about Alex
```

### Feedback checklist

- [ ] Answer is useful and natural.
- [ ] Citations make the answer trustworthy.
- [ ] Tone and language feel correct.
- [ ] Abstention behavior is preferable to guessing.
- [ ] Provider/privacy behavior is acceptable.

### Acceptance record

| Field | Value |
|---|---|
| Decision | Pending |
| Required phrase | `Slice 2 accepted` |
| Date | — |
| Implementation commit | — |
| Test results | — |
| Demo command | — |
| User notes | — |

---

## Slice 3 — Add Manual Context

**Status:** Planned  
**Dependency:** Slice 2 accepted  
**Unlocks:** Slice 4

### Goal

Add user-provided context through the same privacy, provenance, retrieval, and consistency system
used by imported sources.

### Planned interface — not implemented

```bash
lazo context context.txt --slug sample --dry-run
lazo context context.txt --slug sample --apply
```

### Flow

```text
manual source
-> PII scan + deduplication
-> normalized user_context records
-> explicit claim detection
-> preview
-> vectors + provenance + source backup
-> invariants
```

### Implementation requirements

- Distinguish freeform context, explicit user assertion, and derived inference.
- Assign `confidence=1.0` only to explicit user assertions.
- Make manual context searchable and citable by Slice 2.
- Store source hash, import timestamp, authorship, and authority metadata.
- Use preview/apply semantics and retain PII protections.
- Keep idempotent behavior for repeated files.

### Out of scope

- Editing extracted graph triples directly.
- Natural-language correction of an existing claim; Slice 4 owns that behavior.

### Acceptance criteria

- Repeated context does not duplicate memories or claims.
- Context appears in semantic answers with correct provenance.
- Freeform text is not automatically promoted to certain fact.
- Explicit assertions receive user authority.
- PII and equivalent-source behavior remain safe.
- Dataset invariants pass after apply.

### Required tests and demo

- Freeform versus explicit-assertion classification tests.
- Context idempotency and source-hash tests.
- Retrieval/citation integration test.
- PII block/redaction policy tests appropriate to storage and provider boundaries.

Planned demo:

```bash
lazo context sample-context.txt --slug sample --dry-run
lazo context sample-context.txt --slug sample --apply
lazo ask "¿Cuándo cumple años Alex?" --about Alex
```

### Feedback checklist

- [ ] Preview clearly distinguishes text from assertions.
- [ ] Authority level matches user intent.
- [ ] Added context appears correctly in answers.
- [ ] Provenance is understandable.
- [ ] Apply semantics feel safe.

### Acceptance record

| Field | Value |
|---|---|
| Decision | Pending |
| Required phrase | `Slice 3 accepted` |
| Date | — |
| Implementation commit | — |
| Test results | — |
| Demo command | — |
| User notes | — |

---

## Slice 4 — Correct Knowledge

**Status:** Planned  
**Dependency:** Slice 3 accepted  
**Unlocks:** Slice 5

### Goal

Correct extracted knowledge safely, reversibly, and without losing the correction during rebuilds.

### Planned interfaces — not implemented

```bash
lazo correct "Carlos is Juan's cousin, not his brother" --dry-run
lazo correct "Carlos is Juan's cousin, not his brother" --apply
lazo corrections list
lazo corrections undo <claim-id>
```

### Flow

```text
natural-language correction
-> entity resolution
-> proposed assertion/retraction set
-> preview and ambiguity checks
-> immutable correction ledger
-> effective KG projection
-> answer/retrieval visibility
```

### Implementation requirements

- Never edit generated triples destructively.
- Store corrections as immutable assertions, retractions, and superseding records.
- Give user assertions priority in effective reads.
- Preserve original extracted evidence for audit.
- Require clarification for ambiguous entities or relations.
- Support list, history, and undo.
- Preserve corrections through vector/KG/wiki rebuilds.

### Out of scope

- Bulk ontology editing.
- Silent automatic correction from LLM output.

### Acceptance criteria

- Dry-run shows exact affected claims before writes.
- Applied correction overrides generated knowledge in queries.
- Rebuild preserves correction priority.
- Undo restores previous effective knowledge without deleting history.
- Ambiguous corrections write nothing.
- Answers cite correction provenance separately from extracted evidence.

### Required tests and demo

- Assertion/retraction/supersede ledger tests.
- Rebuild persistence test.
- Ambiguous-entity no-write test.
- Undo and audit-history test.
- Integration test through person/graph answers.

Planned demo:

```bash
lazo correct "Carlos is Juan's cousin, not his brother" --dry-run
lazo correct "Carlos is Juan's cousin, not his brother" --apply
lazo corrections list
lazo ask "¿Qué relación tiene Carlos con Juan?"
```

### Feedback checklist

- [ ] Proposed change matches intended meaning.
- [ ] Preview is safe and readable.
- [ ] Corrected answers behave as expected.
- [ ] History and undo are understandable.
- [ ] User priority feels correct without hiding provenance.

### Acceptance record

| Field | Value |
|---|---|
| Decision | Pending |
| Required phrase | `Slice 4 accepted` |
| Date | — |
| Implementation commit | — |
| Test results | — |
| Demo command | — |
| User notes | — |

---

## Slice 5 — Ask About Relationships

**Status:** Planned  
**Dependency:** Slice 4 accepted  
**Unlocks:** Slice 6

### Goal

Explain who a person is and how people are connected using effective graph knowledge and original
evidence.

### Planned interface — not implemented

```bash
lazo ask "Who is Carlos and how is he related to Juanita?"
```

### Flow

```text
entity detection and alias resolution
-> effective KG path
-> participant-filtered memories
-> chronology/wiki context
-> evidence fusion
-> LLM
-> cited facts + explicitly labeled inferences
```

### Implementation requirements

- Use effective KG, including accepted user corrections.
- Include path, relationship confidence, time range, and supporting source messages.
- Separate observations from interpretations in the answer schema/rendering.
- Resolve repeated aliases to canonical identities without merging distinct people.
- Abstain when no supported relationship exists.

### Out of scope

- Broad emotional or psychological relationship analysis.
- Gift or activity recommendations.

### Acceptance criteria

- Known aliases produce the same effective relationship.
- Corrected relationships override extracted ones visibly.
- Unsupported relationships are not invented.
- Graph path and cited messages agree.
- Temporal evidence is represented accurately.
- Facts and inferences are visibly separate.

### Required tests and demo

- Alias/path integration tests.
- Corrected versus generated graph projection test.
- No-path abstention test.
- Citation/path consistency evaluation.
- Temporal relationship fixture.

Planned demo:

```bash
lazo ask "¿Quién es Carlos y qué relación tiene con Juanita?"
```

### Feedback checklist

- [ ] Entity interpretation is correct.
- [ ] Relationship explanation matches user understanding.
- [ ] Facts and inference are distinguishable.
- [ ] Citations/path provide enough trust.
- [ ] Missing-evidence behavior is acceptable.

### Acceptance record

| Field | Value |
|---|---|
| Decision | Pending |
| Required phrase | `Slice 5 accepted` |
| Date | — |
| Implementation commit | — |
| Test results | — |
| Demo command | — |
| User notes | — |

---

## Slice 6 — Pending Plans

**Status:** Planned  
**Dependency:** Slice 5 accepted  
**Unlocks:** Slice 7

### Goal

Identify, update, list, and answer questions about plans or commitments.

### Planned interfaces — not implemented

```bash
lazo ask "Do we have any pending plans?"
lazo plans list
lazo plans show <plan-id>
```

### Flow

```text
messages + manual claims
-> plan candidate extraction
-> participant/date/location resolution
-> duplicate and lifecycle matching
-> structured Plan records
-> KG projections + citations
-> query/list interfaces
```

### Implementation requirements

- Use the shared `Plan` model and fixed lifecycle statuses.
- Resolve relative dates from message timestamp and dataset timezone.
- Match later completion, cancellation, or rescheduling evidence to earlier plans.
- Keep ambiguous candidates unresolved until confirmed.
- Project participants and locations into KG without representing status as an entity.
- Retain source IDs and confidence for every state transition.

### Out of scope

- Calendar synchronization.
- Automatic external reminders.
- Suggestions based on plans; Slice 7 owns those.

### Acceptance criteria

- Proposed, pending, scheduled, completed, and cancelled states behave correctly.
- Relative dates resolve deterministically.
- Duplicate plans merge only with sufficient evidence.
- Participants and locations remain queryable.
- Ambiguous updates do not silently change plan state.
- Answers cite creation and latest transition evidence.

### Required tests and demo

- Relative-date/timezone fixtures.
- State-transition tests.
- Duplicate and ambiguous-plan fixtures.
- Multi-participant and location tests.
- Query/list output tests with citations.

Planned demo:

```bash
lazo plans list
lazo ask "¿Tenemos alguna actividad pendiente?"
lazo plans show <plan-id>
```

### Feedback checklist

- [ ] Extracted plans match user intent.
- [ ] Dates and statuses are correct.
- [ ] Duplicate handling is understandable.
- [ ] Pending-plan answer is useful.
- [ ] Evidence makes transitions trustworthy.

### Acceptance record

| Field | Value |
|---|---|
| Decision | Pending |
| Required phrase | `Slice 6 accepted` |
| Date | — |
| Implementation commit | — |
| Test results | — |
| Demo command | — |
| User notes | — |

---

## Slice 7 — Grounded Suggestions

**Status:** Planned  
**Dependency:** Slice 6 accepted  
**Unlocks:** Slice 8

### Goal

Provide useful personal suggestions supported by preferences, memories, corrected knowledge,
dates, constraints, and plans.

### Planned interface — not implemented

```bash
lazo ask "What could I give Alex as a gift?"
```

### Flow

```text
target person
-> preferences + relevant memories
-> corrected claims + plans + dates + constraints
-> evidence ranking
-> LLM
-> known facts + inference + suggestion + missing information
```

### Implementation requirements

- Separate known evidence, derived inference, suggested action, and missing information.
- Never persist a suggestion as fact automatically.
- Respect corrections, current plans, timing, and stated constraints.
- Ask a clarifying question or abstain when context is too weak or sensitive.
- Persist outcomes only after explicit user confirmation through context/correction flows.

### Out of scope

- Purchasing, messaging, or calendar side effects.
- Uncited psychological profiling.

### Acceptance criteria

- Every justification traces to evidence.
- Suggestions do not invent preferences.
- Corrections and current plan status influence output.
- Uncertainty and missing information are explicit.
- Unsupported requests ask for context or abstain.
- No suggestion changes stored knowledge automatically.

### Required tests and demo

- Preference grounding and hallucination evals.
- Correction-compliance test.
- Pending-plan/date constraint test.
- Insufficient-context and sensitive-context fixtures.
- Confirmation-required persistence test.

Planned demo:

```bash
lazo ask "¿Qué podría regalarle a Alex?"
```

### Feedback checklist

- [ ] Suggestions feel personally relevant.
- [ ] Justifications match known facts.
- [ ] Uncertainty is presented appropriately.
- [ ] Missing information prompts are useful.
- [ ] Nothing is stored without confirmation.

### Acceptance record

| Field | Value |
|---|---|
| Decision | Pending |
| Required phrase | `Slice 7 accepted` |
| Date | — |
| Implementation commit | — |
| Test results | — |
| Demo command | — |
| User notes | — |

---

## Slice 8 — Describe a Relationship

**Status:** Planned  
**Dependency:** Slice 7 accepted  
**Unlocks:** Roadmap completion

### Goal

Produce careful, time-bounded relationship summaries that distinguish observation from
interpretation.

### Planned interface — not implemented

```bash
lazo ask "How would you describe my relationship with Alex?"
```

### Flow

```text
effective KG
-> participant-filtered memories
-> chronology and communication patterns
-> contradictions and corrections
-> evidence/inference separation
-> cited, time-bounded relationship summary
```

### Implementation requirements

- State the analyzed period and evidence coverage.
- Separate observations, measured patterns, interpretations, and unknowns.
- Respect corrections and changes over time.
- Represent contradictory evidence instead of forcing one conclusion.
- Avoid psychological diagnosis, absolute judgments, or unsupported labels.
- Protect third-party privacy in rendered answers and provider prompts.

### Out of scope

- Mental-health diagnosis.
- Automated relationship scoring.
- External actions based on the summary.

### Acceptance criteria

- Summary states time range and coverage.
- Positive, negative, and contradictory evidence are balanced.
- Every factual claim has citations.
- Interpretations are labeled and appropriately uncertain.
- Corrections and temporal changes affect the summary.
- Unsafe diagnostic language is rejected.

### Required tests and demo

- Time-window and chronology fixtures.
- Contradiction and correction tests.
- Balanced-evidence evaluation.
- Citation coverage and safe-language evaluation.
- Privacy/provider-boundary test.

Planned demo:

```bash
lazo ask "¿Cómo describirías mi relación con Alex?"
```

### Feedback checklist

- [ ] Time range and evidence coverage are clear.
- [ ] Description feels balanced and accurate.
- [ ] Facts and interpretations remain separate.
- [ ] Uncertainty and contradictions are handled well.
- [ ] Language feels safe and respectful.

### Acceptance record

| Field | Value |
|---|---|
| Decision | Pending |
| Required phrase | `Slice 8 accepted` |
| Date | — |
| Implementation commit | — |
| Test results | — |
| Demo command | — |
| User notes | — |

---

## Global testing and evaluation requirements

Every slice must preserve the existing regression suite and add proportional coverage:

- unit tests for new domain contracts and CLI behavior;
- integration tests against temporary ChromaDB and SQLite state;
- deterministic fake-LLM tests for answer behavior;
- participant identity isolation and alias tests;
- citation existence, precision, and coverage checks;
- abstention and hallucination evaluations;
- PII/provider-boundary tests;
- backward compatibility for existing scripts and datasets;
- functional E2E demo for the active slice.

No slice may use a real hosted model in automated tests. Provider tests use fakes or explicitly
opted-in manual evaluation.

## Privacy rules

- Private datasets remain outside the Git repository.
- Hosted providers receive only evidence selected for the current answer.
- Full source files, vector stores, participant databases, and unrelated memories never leave the
  local boundary automatically.
- User corrections and context remain auditable.
- Third-party personal data is shown only when relevant to the user's query and configured policy.
- Suggestions and relationship interpretations are never stored as facts without confirmation.

## Explicit non-goals

This roadmap does not include:

- rewriting all current infrastructure before delivering a slice;
- automatic messaging, purchasing, calendar writes, or other external side effects;
- unreviewed LLM writes to the Knowledge Graph;
- silent bulk export to hosted providers;
- psychological diagnosis or universal relationship scoring;
- beginning a later slice before explicit acceptance of the current one.

## Roadmap completion

The roadmap is complete only when all eight rows show `Accepted`, every acceptance record is
filled, existing regression tests pass, and the final E2E workflow demonstrates import, grounded
answers, manual context, corrections, relationships, plans, suggestions, and safe relationship
description.
