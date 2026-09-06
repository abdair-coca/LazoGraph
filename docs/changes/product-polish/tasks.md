# Tasks: product-polish

> Spec: `docs/specs/product-polish/spec.md` | Design: `docs/changes/product-polish/design.md`
> Context Pack: `docs/lazograph-context-pack/*`
> Mode: single spec, 4 functional slices A-D (completados) + 4 UX/UI slices E-H (transformación)

---

## Fase 1 — Fundación Funcional y Hardening (Completada)

### Slice A — Import pulido (REQ-PP-001, PP-011 parcial, PP-010 parcial)
- [x] **A1** Fix `ui/app.py:139` import preview/apply: keep `_PREVIEWS` token, wire `allow/reconcile_equivalent_source` flags to UI, validate slug/file size, return human `detail` ES.
- [x] **A2** Add `GET /api/progress/{job_id}` real tracking (in-memory `_JOBS` updated per 128 batch, or stub increment) + wire `app.js` polling bar.
- [x] **A3** Fix `templates/base.html:80` + `wizard.html:30` ids únicos, add duplicate `import-form` handler that works for both pages, progress bar element.
- [x] **A4** Update `static/app.js:30` import flow: render preview human (participants badges, PII, equivalent warning), disable button during apply, show progress pct/eta, handle 401/413/422 con copy humano.
- [x] **A5** Tests: extend `tests/test_ui_import.py` (preview human, progress polling, equivalent guard, 20MB, slug traversal).

### Slice B — Ask interpretado (REQ-PP-002, PP-011)
- [x] **B1** Update `static/app.js:48` `ask-form` handler: split `renderAsk(j)` into cards Text/Facts/Inferences/Suggestions/Missing + confidence badge + retrieval_summary debug toggle + citations clickable → `search?participant=`.
- [x] **B2** Handle abstención: if `j.citations=[]` o `confidence<0.4` show human copy "No encontré evidencia suficiente — probá con ..." + suggested queries, no stack.
- [x] **B3** Add UI routing hint: placeholder examples + `about` auto-suggest from `GET /api/datasets` participants.
- [x] **B4** Tests: `tests/test_ui_ask.py` fake provider, verify facts/inferences separation, citations existence, abstención, no leak; plus `test_ask_person` regression.

### Slice C — Explorar (REQ-PP-003, PP-004, PP-005, PP-006)
- [x] **C1** Fix `static/app.js:65` search: add `from/to` filter state from timeline, virtualized list or pagination correct, human empty state, `has_more` check.
- [x] **C2** Fix `static/app.js:87` timeline: `GET /api/timeline?granularity=day` buckets render + click sets `searchFrom/To = b.date` + switch to search tab.
- [x] **C3** Fix `static/app.js:113` graph: inject `GET /api/graph?format=json`, filter `plan_*` edges, `cytoscape` CDN fallback to list + `GET /api/graph/stats`, click node → search panel sin leak.
- [x] **C4** Fix `templates/base.html:157` wiki: add `id="wiki-load"` + `id="wiki-content"` handler, ensure `GET /api/wiki` lint badge visible, evidence tags link.
- [x] **C5** Populate `static/app.js:14` `loadDiagnose()` KPIs `kpi-messages/personas/graph` from diagnose.
- [x] **C6** Tests: `tests/test_product_ux.py` pass `test_search_pagination`, `test_timeline_aggregation`, `test_graph_json`, `test_wiki_render`.

### Slice D — Operar (REQ-PP-007, PP-008, PP-009, PP-010)
- [x] **D1** Plans tab: `static/app.js:58` add filters `status` select + `participant` input + `show` detail modal with transitions, reuse `GET /api/plans`.
- [x] **D2** Ops tab: `templates/base.html:166` add buttons `Backup`, `Restore`, `Delete dataset`, `Telemetry toggle`, `Update check`; wire handlers con copy humano.
- [x] **D3** Harden `ui/app.py:60` ensure `X-UI-Token` 401, `validate_slug` 422, `413 file too large`, CSP header, logs sin PII cruda.
- [x] **D4** E2E `e2e/product.spec.ts:3` ampliar a 9 flujos.
- [x] **D5** Final verify: `pytest tests -q -p no:warnings` + diagnose healthy.

---

## Fase 2 — Transformación UX/UI: Warm Intelligence (Context Pack)

### Slice E — Design System & Shell de Navegación Humana (REQ-PP-012, REQ-PP-013)
- [x] **E1** Actualizar `static/style.css` con variables Warm Intelligence (`--color-base: #F5F1E8`, `--color-ink: #161616`, `--color-person: #FF5C7A`, `--color-memory: #9D8FD1`, `--color-place: #9FC5B7`, `--color-event: #F4C65D`), tipografía editorial, radios suaves y sombras sutiles.
- [x] **E2** Reestructurar `templates/base.html` reemplazando los 9 tabs planos por la navegación agrupada:
  - *Principal*: Inicio (`#tab-inicio`), Preguntar (`#tab-ask`), Explorar (`#tab-explore`).
  - *Tu historia*: Historia (`#tab-history`), Grafo (`#tab-graph`).
  - *Datos & Sistema*: Importar (`#tab-import`), Ajustes (`#tab-settings`).
- [x] **E3** Actualizar `static/app.js` para gestionar el nuevo enrutamiento de pestañas y estado activo de la navegación.

### Slice F — Inicio: "Tu Mundo" y "Para Ti" (REQ-PP-014)
- [x] **F1** Maquetar la vista de `Inicio` en `templates/base.html`:
  - Saludo contextual cálido ("Buenas tardes, [Nombre]").
  - Pregunta inspiradora central ("¿Qué quieres entender hoy?") con sugerencias de reflexión.
  - Contenedor central prominente para "Tu Mundo" (grafo vivo interactivo).
  - Sección de tarjetas abiertas "Para ti" (patrón detectado, recuerdo, reflexión).
  - Indicador sutil de actividad de memoria ("X recuerdos procesados · Y personas conectadas") eliminando tarjetas KPI corporativas.
- [x] **F2** Configurar en `static/app.js` la instancia Cytoscape de "Tu Mundo":
  - Estilos de nodos personalizados por entidad (avatares/emojis y bordes Coral/Lavender/Sage/Gold).
  - Microinteracciones ambientales (movimiento sutil al hover/focus).
  - Panel contextual al seleccionar entidad con resumen de mensajes, tiempo de historia y botón para explorar.
- [x] **F3** Conectar la sección "Para ti" con datos representativos del dataset (`/api/diagnose`, `/api/plans`, `/api/wiki`).

### Slice G — Preguntar: Reflexión y Evidencia Interactiva (REQ-PP-015)
- [x] **G1** Rediseñar el formulario de consulta en `templates/base.html` con tono humano ("Habla con tu historia", no "Preguntar al grafo").
- [x] **G2** Implementar animación de progreso por etapas comprensibles en `static/app.js` (*Buscando conversaciones → Personas relacionadas → Analizando patrones → Construyendo respuesta*).
- [x] **G3** Renderizar la respuesta reflexiva en 5 secciones claras:
  1. *Conclusión directa*
  2. *Lo que encontré* (patrones y hechos)
  3. *Evidencia interactiva* (citas clicables con origen y fragmento)
  4. *Mi perspectiva* (consejo o reflexión fundamentada)
  5. *Explorar más* (preguntas complementarias sugeridas)
- [x] **G4** Implementar panel lateral o modal interactivo de evidencia que despliegue el hilo de la conversación original al hacer clic en una cita.

### Slice H — Explorar Unificado, Ajustes y Verificación (REQ-PP-012, REQ-PP-013)
- [x] **H1** Construir la vista unificada `Explorar` en `templates/base.html` con subniveles (Personas, Temas, Lugares, Momentos) y buscador textual integrado, consolidando la información de búsqueda, wiki y planes.
- [x] **H2** Adaptar `Historia` (Timeline) a los nuevos estilos Warm Intelligence manteniendo el filtrado interactivo por fechas.
- [x] **H3** Rediseñar la vista `Ajustes` (ex Ops) con comunicación tranquila de privacidad ("Local-first · Sin red · Tus recuerdos"), y acciones limpias de backup, restore y eliminación con cuarentena.
- [x] **H4** Actualizar suite de tests E2E en `e2e/product.spec.ts` para cubrir la nueva navegación y flujos visuales.
- [x] **H5** Ejecutar suite completa de tests de regresión (`pytest tests -q`) y verificación de invariantes.
