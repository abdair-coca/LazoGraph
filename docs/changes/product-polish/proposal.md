# Proposal: product-polish

## Intent

Evolucionar la interfaz de LazoGraph de un dashboard técnico fragmentado a una experiencia premium de **Personal Memory Intelligence** con la identidad visual **Warm Intelligence**, acoplando la visión estratégica de `docs/lazograph-context-pack/*` sobre la base funcional y robustecida ya implementada en los Slices A-D. 

El producto debe sentirse personal, cálido, reflexivo y fundamentado en evidencia verificable, dejando atrás la estética de herramientas analíticas de datos o visualizaciones técnicas de grafos.

## Scope

### In Scope
- **Alineación con Context Pack**: Integración de las directrices de `CONSTITUTION.md`, `PRODUCT.md`, `USER_EXPERIENCE.md`, `INFORMATION_ARCHITECTURE.md`, `DASHBOARD.md`, `GRAPH_EXPERIENCE.md`, `ASK_LAZO.md` y `DESIGN_SYSTEM.md`.
- **Fundación Funcional (Slices A-D ya implementados)**:
  - Fix de botones muertos y flujos rotos (preview/apply, progress bar real, backup/restore/delete, CSP, tokens).
  - Search paginado sin solapamiento, timeline agregada filtrable y graph fallback sin dependencias CDN.
- **Transformación UX/UI (Slices E-H)**:
  - **Design System Warm Intelligence**: Paleta base Warm Cream (`#F5F1E8`), Ink (`#161616`), Coral (`#FF5C7A`), Lavender (`#9D8FD1`), Sage (`#9FC5B7`), Gold (`#F4C65D`), bordes suaves, microinteracciones y erradicación de jerga técnica en la UI.
  - **Nueva Arquitectura de Información**: Reemplazo de los 9 tabs planos por la navegación agrupada:
    - *Principal*: Inicio, Preguntar, Explorar.
    - *Tu historia*: Historia, Grafo.
    - *Datos & Sistema*: Importar, Ajustes.
  - **Inicio & "Tu Mundo"**: Saludo contextual, buscador reflexivo ("¿Qué quieres entender hoy?"), grafo vivo interactivo en el centro con nodos personalizados (emojis/colores semánticos), sección "Para ti" con recuerdos y patrones, y estadísticas sutiles de apoyo.
  - **Ask Lazo & Evidencia Interactiva**: Diálogo reflexivo ("Habla con tu historia"), retroalimentación por etapas de búsqueda comprensibles, respuesta estructurada en Conclusión directa / Lo que encontré / Evidencia explorable / Mi perspectiva / Explorar más, y trazabilidad interactiva hacia mensajes originales.
  - **Explorar Unificado**: Integración de Personas, Temas, Lugares, Eventos y Recuerdos en un espacio de descubrimiento coherente (reemplazando la dispersión entre Search, Wiki y Planes).

### Out of Scope
- Reescribir `adapters/`, `domain/*`, `scripts/ingest`, o la infraestructura de almacenamiento (`infrastructure/chroma/sqlite`).
- Sincronización multi-dispositivo o aplicación móvil nativa.
- Modelos LLM remotos por defecto (se mantiene el principio local-first y offline-first).

## Capabilities

### New Capabilities
- `product-polish`: experiencia completa de Personal Memory Intelligence con IA reflexiva, evidencia interactiva, navegación humana y diseño Warm Intelligence.

### Modified Capabilities
- `ui`: adopta la nueva arquitectura de información (7 secciones organizadas vs 9 tabs técnicos) y el design system Warm Intelligence.
- `ask`: incorpora etapas de progreso comprensibles, estructura de respuesta reflexiva en 5 partes y navegación hacia fuentes originales.
- `dashboard`: pasa de tarjetas KPI corporativas a un espacio personal centrado en "Tu mundo" y "Para ti".
- `graph`: representación viva con identidad visual por tipo de entidad (personas, recuerdos, lugares, eventos) y panel contextual.

## Approach

Evolución incremental en dos grandes fases:
1. **Fase 1 (Completada en commits previos)**: Slices A-D — Respaldo técnico, APIs verificadas, progress tracking, endpoints de backup/restore/delete y hardening de seguridad.
2. **Fase 2 (Transformación UX/UI)**: Slices E-H — Aplicación del Design System Warm Intelligence, restructuración del shell HTML/CSS/JS hacia la nueva arquitectura de información humana, construcción del nuevo Inicio interactivo ("Tu Mundo"), y elevación de la experiencia de Ask Lazo con evidencia explorable.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `docs/specs/product-polish/spec.md` | Modified | Incorpora REQ-PP-012 a REQ-PP-015 derivados del context pack |
| `docs/changes/product-polish/*` | Modified | Actualización de proposal, design y tasks hacia la visión UX/UI |
| `src/lazograph/ui/templates/base.html` | Modified | Reestructuración del layout a la nueva IA y componentes humanos |
| `src/lazograph/ui/static/style.css` | Modified | Tokens de diseño Warm Intelligence, tipografía editorial, cards abiertas |
| `src/lazograph/ui/static/app.js` | Modified | Lógica de navegación agrupada, grafo vivo de inicio, Ask reflexivo y evidencia |
| `src/lazograph/ui/app.py` | Modified | Ajustes menores en endpoints para alimentar "Para ti" y detalles de entidades |
| `e2e/product.spec.ts` | Modified | Actualización de selectores y validación de la nueva jerarquía de navegación |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Densidad visual en pantallas pequeñas | Medium | Layout responsivo pensado desde cero, sin comprimir escritorio |
| Rendimiento de grafo vivo en dashboard | Medium | Cytoscape optimizado con clustering, LOD y fallback liviano |
| Desconexión entre backend y nueva IA | Low | Mapeo directo de endpoints existentes (`diagnose`, `search`, `graph`, `wiki`, `plans`) a las nuevas vistas |

## Success Criteria

- [ ] Navegación responde a la estructura humana (Inicio, Preguntar, Explorar, Historia, Grafo, Importar, Ajustes)
- [ ] Dashboard Inicio muestra saludo contextual, buscador reflexivo, grafo vivo ("Tu mundo") y recuerdos ("Para ti")
- [ ] Paleta y estilos cumplen con el Design System Warm Intelligence (Warm Cream `#F5F1E8`, radios suaves, tipografía cuidada)
- [ ] No hay presencia de términos técnicos internos (nodos, aristas, embeddings, vectores) en la interfaz principal
- [ ] Ask Lazo presenta conclusiones con perspectiva y citas navegables hacia el mensaje original
- [ ] Se preservan todas las garantías de seguridad y estabilidad validadas en Slices A-D
