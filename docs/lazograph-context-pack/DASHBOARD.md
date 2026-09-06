# Dashboard — Dirección de diseño

## Objetivo

El dashboard debe dejar de sentirse como una landing page dentro de una aplicación.

Debe sentirse como el lugar donde el usuario entra a su mundo personal.

---

# Estructura

## 1. Saludo contextual

Ejemplo:

> Buenas tardes, Abdair.

Subtexto:

> Hay nuevas conexiones en tu historia por explorar.

Evitar un hero corporativo excesivamente grande.

La personalización debe sentirse natural.

---

# 2. Pregunta principal

Debe ser uno de los elementos visuales más importantes.

Ejemplo:

```text
¿Qué quieres entender hoy?

┌─────────────────────────────────────────────┐
│ Pregúntame algo sobre tu vida...            │
└─────────────────────────────────────────────┘
```

Sugerencias:

- ¿Qué patrones se repiten en mis relaciones?
- ¿Qué objetivos menciono más?
- ¿Qué consejo me darías según mis chats?

La entrada debe sentirse como una invitación a reflexionar.

---

# 3. Tu mundo

El centro visual del dashboard.

Un grafo animado y explorable.

No una imagen estática.

Debe ocupar suficiente espacio para convertirse en la pieza memorable de la interfaz.

El usuario debe poder:

- mover;
- hacer zoom;
- seleccionar entidades;
- seguir conexiones;
- abrir detalles.

---

# 4. Recuerdos destacados

Título sugerido:

> Para ti

o

> Algo para recordar

Tipos de contenido:

### Hace un tiempo

Un recuerdo temporal.

### Patrón detectado

Una tendencia encontrada.

### Algo que quizá olvidaste

Una conversación o decisión antigua.

### Reflexión

Una observación interesante.

---

# 5. Actividad de la memoria

Más sutil que un dashboard de analytics.

En vez de tarjetas enormes de métricas:

> 4.932 recuerdos procesados

> 4 personas conectadas

> 51 conexiones observadas

Las estadísticas deben apoyar la experiencia, no dominarla.

---

# Anti-patrones

No llenar el dashboard con:

- KPI cards grandes;
- gráficos corporativos;
- tablas;
- métricas sin significado emocional;
- bloques simétricos sin jerarquía.

---

# Layout conceptual

```text
┌──────────────────────────────────────────────────────┐
│ Navegación                                           │
├──────────────────────────────────────────────────────┤
│                                                      │
│ Buenas tardes, Usuario                               │
│                                                      │
│ ¿Qué quieres entender hoy?                           │
│ [ Pregúntame algo sobre tu vida...              ]    │
│                                                      │
├──────────────────────────────────────────────────────┤
│                                                      │
│                    TU MUNDO                          │
│                                                      │
│              grafo vivo interactivo                  │
│                                                      │
├──────────────────────────────────────────────────────┤
│                                                      │
│ PARA TI                                              │
│                                                      │
│ [patrón] [recuerdo] [reflexión]                      │
│                                                      │
└──────────────────────────────────────────────────────┘
```

---

# Responsive

En móvil:

1. pregunta principal;
2. insight destacado;
3. mini grafo interactivo;
4. recuerdos;
5. navegación simplificada.

Nunca intentar simplemente comprimir el desktop.
