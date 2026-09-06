# Design: product-polish

> Spec: `docs/specs/product-polish/spec.md`
> Context Pack: `docs/lazograph-context-pack/*`
> Stack: `src/lazograph/ui/app.py`, `templates/base.html`, `static/app.js`, `static/style.css`, `domain/answer.py`

## Architecture & Layout

### 1. Navigation & Information Architecture
Reemplazo de los 9 tabs técnicos planos por la navegación agrupada humana:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ ◈ LazoGraph    [Inicio]  [Preguntar]  [Explorar] │ [Historia] [Grafo] │ [Importar] [Ajustes] │  Dataset: [ Samantha ▼ ] │
└─────────────────────────────────────────────────────────────────────────────┘
```

- **Principal**:
  - `Inicio` (`#tab-inicio`): Entrada personal, saludo, buscador reflexivo, grafo vivo y recuerdos.
  - `Preguntar` (`#tab-ask`): Diálogo reflexivo con la propia historia, feedback por etapas y trazabilidad de evidencia.
  - `Explorar` (`#tab-explore`): Vista unificada de descubrimiento (Personas, Temas, Lugares, Eventos, Recuerdos).
- **Tu Historia**:
  - `Historia` (`#tab-history`): Línea de tiempo interactiva agregada (ex timeline).
  - `Grafo` (`#tab-graph`): Vista espacial inmersiva a gran escala.
- **Datos y Sistema**:
  - `Importar` (`#tab-import`): Flujo de importación guiado y barra de progreso.
  - `Ajustes` (`#tab-settings`): Diagnóstico, copias de seguridad, privacidad y estado local (ex ops).

---

## Design System: Warm Intelligence

### Paleta y Tokens CSS
```css
:root {
  /* Fondo y superficies */
  --color-base: #F5F1E8;         /* Warm Cream */
  --color-surface: #FFFFFF;
  --color-surface-soft: #EDE7DA;
  --color-hairline: #E2DACB;
  
  /* Tipografía y tinta */
  --color-ink: #161616;
  --color-muted: #6B665E;
  
  /* Acentos semánticos de memoria */
  --color-person: #FF5C7A;       /* Coral: Personas */
  --color-memory: #9D8FD1;       /* Lavender: Recuerdos / Reflexión */
  --color-place: #9FC5B7;        /* Sage: Lugares / Contexto */
  --color-event: #F4C65D;        /* Gold: Eventos / Momentos */
  
  /* Radios y elevación */
  --radius-sm: 8px;
  --radius-md: 14px;
  --radius-lg: 22px;
  --shadow-soft: 0 4px 20px rgba(22, 22, 22, 0.05);
  --shadow-elevated: 0 12px 32px rgba(22, 22, 22, 0.08);
}
```

### Reglas Visuales y de Tono
- **Cero jerga técnica**: Prohibido usar "nodos", "aristas", "embeddings", "vectores" o "clusters" en la interfaz principal. Se habla de "personas", "recuerdos", "momentos", "historia" y "conexiones".
- **Tarjetas abiertas**: Evitar encapsular elementos en cajas sobre cajas. Usar fondos limpios y sombras sutiles.
- **Tipografía editorial**: Títulos reflexivos, jerarquía clara y lectura descansada.

---

## Component Specifications

### 1. Inicio — "Tu Mundo" y "Para Ti"
- **Saludo contextual**: Generado a partir del nombre del dataset o perfil ("Buenas tardes, [Nombre]").
- **Buscador reflexivo central**:
  - Título: *"¿Qué quieres entender hoy?"*
  - Placeholder: *"Pregúntame algo sobre tu vida..."*
  - Sugerencias rápidas: *"¿Qué patrones se repiten en mis relaciones?", "¿Qué objetivos menciono más?"*
- **"Tu Mundo" (Grafo vivo central)**:
  - Canvas Cytoscape con física ambiental relajada.
  - Nodos humanos: avatares/emojis con borde Coral para personas, Lavender para recuerdos, Sage para lugares.
  - Al interactuar, abre un panel lateral con resumen de la persona/momento y botón *"Explorar historia"*.
- **"Para ti" (Recuerdos destacados)**:
  - Tarjetas abiertas: *Hace un tiempo*, *Patrón detectado*, *Reflexión*.
- **Actividad de memoria**:
  - Resumen cuantitativo sutil en el pie (ej. *"4.932 recuerdos procesados · 4 personas conectadas"*), desterrando tarjetas KPI corporativas gigantes.

### 2. Preguntar — Experiencia Reflexiva y Evidencia Interactiva
- **Progreso por etapas**: Al consultar, en lugar de un spinner genérico, se muestran pasos humanos:
  1. *Buscando conversaciones relevantes...*
  2. *Identificando personas y momentos...*
  3. *Analizando patrones en tu historia...*
  4. *Construyendo perspectiva fundamentada...*
- **Estructura de respuesta**:
  1. **Conclusión Directa**: Síntesis clara y honesta.
  2. **Lo que encontré**: Hechos y patrones observados en los datos.
  3. **Evidencia Interactiva**: Citas clicables con origen (`[chat.jsonl:23]`), remitente y fragmento, que permiten desplegar la conversación original completa.
  4. **Mi perspectiva**: Consejo o reflexión reflexiva basada en la evidencia.
  5. **Explorar más**: Sugerencias de preguntas complementarias.
- **Abstención**: Si la confianza es baja o no hay citas, se muestra copy humano y empático sugerido alternativas, sin inventar hechos.

### 3. Explorar — Descubrimiento Unificado
- Unifica en una sola vista lo que antes estaba disperso en *Buscar*, *Wiki* y *Planes*:
  - Pestañas internas de descubrimiento: **Personas**, **Temas**, **Lugares**, **Momentos**.
  - Cada tarjeta de entidad muestra: mensajes compartidos, tiempo de historia, temas asociados y botón para ver conversaciones fuente.
  - Buscador textual integrado para localizar mensajes específicos con resaltado.

### 4. Historia (Timeline)
- Línea de tiempo con barras de densidad por día/semana/mes.
- Al hacer clic en un período o momento, filtra la vista de mensajes asociados preservando la coherencia temporal.

### 5. Ajustes y Privacidad (Ops)
- Espacio dedicado a la salud del sistema:
  - Estado local ("Todo permanece en este equipo · Sin conexión exterior").
  - Botones discretos de gestión: *Crear copia de seguridad*, *Restaurar copia*, *Gestionar fuentes*.
  - Eliminación segura con confirmación explícita y cuarentena de 30 días.

---

## Data Flow & Integration

```text
Browser (Warm Intelligence UI)
  │
  ├─► Inicio:
  │     GET /api/diagnose   ──► Saludo, actividad de memoria sutil
  │     GET /api/graph      ──► "Tu Mundo" (Cytoscape vivo central)
  │     GET /api/plans      ──► Recuerdos y compromisos destacados ("Para ti")
  │
  ├─► Preguntar:
  │     POST /api/ask       ──► Progreso simulado/etapas ──► Respuesta 5 partes + Citas
  │     Click en Cita       ──► GET /api/search?participant=&from=... ──► Modal / Panel lateral
  │
  ├─► Explorar:
  │     GET /api/datasets   ──► Lista de personas y entidades
  │     GET /api/wiki       ──► Temas y resúmenes sintetizados
  │     GET /api/search     ──► Exploración profunda de mensajes
  │
  ├─► Historia:
  │     GET /api/timeline   ──► Buckets de densidad y filtrado temporal
  │
  └─► Ajustes:
        GET /api/diagnose, POST /api/backup, POST /api/restore, DELETE /api/datasets
```

---

## Testing & Verification

1. **Pruebas de Componentes y UI**:
   - Verificación de la navegación agrupada (sin presencia de los 9 tabs antiguos).
   - Comprobación visual de tokens de diseño Warm Intelligence (Warm Cream, Ink, Coral, Lavender).
   - Verificación de renderizado del grafo vivo en Inicio y de la respuesta estructurada en Preguntar.
2. **Pruebas E2E (Playwright)**:
   - Recorrido completo: Selección de dataset → Inicio con grafo vivo → Hacer pregunta en Preguntar → Clic en evidencia → Navegación a Explorar e Historia.
3. **Invariantes del Backend**:
   - Todos los tests existentes en `tests/test_ui_*.py` y `tests/test_product_ux.py` continúan pasando, ya que los contratos de API se preservan.
