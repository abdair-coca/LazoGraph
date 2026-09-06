# Design: product-polish

> Spec: `docs/specs/product-polish/spec.md`
> Stack: `src/lazograph/ui/app.py:83`, `templates/base.html`, `static/app.js`, `domain/answer.py`

## Architecture

```
Browser (base.html + app.js + style.css)
  ├─ GET /           → wizard.html si no datasets (app.py:598) else base.html
  ├─ POST /api/import/preview (multipart) → build_preview() → token store _PREVIEWS
  ├─ POST /api/import/apply {token} → build_preview + init_knowledge + ingest.main + invariants
  ├─ GET  /api/progress/{id}            → {stored,total,pct,elapsed,eta}
  ├─ POST /api/ask {question,about,limit,budget,provider}
  │     → route: about|plan|suggestion|describe|participant|relationship|dataset (cli.py:379)
  │     → Answer.to_dict() {text,facts,inferences,suggestions,missing_information,citations,confidence,retrieval_summary}
  ├─ GET  /api/search, /api/timeline, /api/graph, /api/wiki, /api/plans, /api/datasets, /api/diagnose
  └─ POST /api/backup, /api/restore, DELETE /api/datasets/{slug}, GET /api/update-check, /api/telemetry
```

Preserve: `adapters/`, `domain/evidence.py|claims.py|plans.py`, `infrastructure/chroma|sqlite|llm`, `scripts/*.py` wrappers, dataset layout `knowledge_root/{slug}/`.

## Contracts

**Answer rendering (REQ-PP-002)**
- Input `Answer.to_dict()` fields: `text, citations[Evidence{message_id,sender,timestamp,excerpt,score,source_type,authority}], confidence, entities, retrieval_summary, facts[], inferences[], suggestions[], missing_information[]`.
- UI function `renderAsk(j)` splits into 4 cards + citations list with `data-message-id` click → `search?participant=citation.sender`.

**Progress (REQ-PP-001)**
- In-memory `_JOBS: dict[job_id->{stored,total,pct,elapsed,eta, status}]` updated durante `ingest.main` batch 128. `GET /api/progress/{id}` polling 500ms. Fallback `pct 0` si no job (app.py:592).

**Timeline filter (REQ-PP-004)**
- `app.py:463` returns `buckets:[{date:YYYY-MM-DD,count}]`. `app.js` click sets `searchFrom/searchTo = b.date` and calls `GET /api/search?from&to&participant`.

## Component Changes

**`ui/app.py`**
- Add `_JOBS` + update in `import_apply` wrapper around `ingest.main` (or stub pct increment).
- Fix `import_preview` to keep `_PREVIEWS` with `tmp_path, slug, persona`.
- Add `timeline` `from/to` filter passthrough (currently only aggregates, search will filter client-side).
- Ensure `graph` fallback returns `nodes` from `participants.json` if KG empty (already app.py:538).
- Add `wiki` lint summary already present (app.py:559).
- Keep `check_token`, `validate_slug`, `CSP` intact.

**`templates/base.html`**
- Fix missing ids: add `id="wiki-load"` to button, add `id="kpi-messages|personas|graph"`, add ops buttons `backup, restore, delete, telemetry`.
- Keep dataset select and nav tabs.

**`static/app.js`**
- `loadDiagnose()` populate KPIs.
- `renderAsk` split sections + confidence badge + citations clickable + abstention handler (if `j.text` contains "No encontré" style).
- `doSearch` add `from/to` params from timeline state, human empty state.
- `timeline` click → set filter + switch to search tab.
- `graph` add catch for `!window.cytoscape` → list fallback.
- Add `humanError(j)` mapping status→copy ES.

**`static/style.css`**
- Toast `.toast-error` red + `.toast-success` green, spinner `.loading`.

## Data Flow per Slice

- **A Import**: file → preview (no write) → token → apply → jobs → diagnose.
- **B Ask**: question → resolve participant → filtered retrieval → LLM local → validate citations → Answer → render sections.
- **C Explore**: sources/*.jsonl → search/timeline/graph/wiki derived reads.
- **D Operate**: dataset.json + sources + .mempalace → backup zip (atomic) → restore atomic → quarantine.

## Testing Strategy

- Unit `TestClient` per REQ (reuse `test_product_ux.py` patterns).
- E2E `playwright test e2e/product.spec.ts` ampliado a 9 flows + error cases.
- Invariants: after every write `dataset_invariants.validate_dataset` ok.
- No hosted LLM in tests (fake provider).

## Risks

- Large chat 15MB memory: stream file read, cap 20MB before tmp write.
- Windows locks: retry 5× 0.5s in `delete_dataset` (already app.py:813).
