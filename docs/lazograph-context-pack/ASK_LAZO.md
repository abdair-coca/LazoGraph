# Ask Lazo — Experiencia de IA

## Objetivo

Esta es la funcionalidad central del producto.

El usuario viene aquí para entender algo sobre su propia vida utilizando su historia como contexto.

---

# Naming

Evitar como nombre principal:

> Preguntar al grafo

Preferir:

> Preguntar

o:

> Pregunta sobre tu vida

o:

> Habla con tu historia

El nombre final puede evolucionar, pero la UX debe ser humana.

---

# Pantalla inicial

```text
¿Qué quieres entender mejor?

[ Escribe una pregunta sobre tu vida... ]

Prueba preguntando:

• ¿Qué patrones se repiten en mis relaciones?
• ¿Qué objetivos abandono con frecuencia?
• ¿Qué consejo me darías según mis conversaciones?
• ¿He cambiado de opinión sobre algo importante?
```

---

# Durante la investigación

No mostrar simplemente un spinner genérico.

Comunicar progreso de forma significativa:

```text
Buscando conversaciones relevantes

✓ Personas relacionadas
✓ Momentos importantes
• Analizando patrones
○ Construyendo respuesta
```

No revelar razonamiento interno privado del modelo.

Solo mostrar etapas de procesamiento comprensibles.

---

# Respuesta

La estructura ideal:

## Respuesta directa

Una conclusión clara.

## Lo que encontré

Patrones o evidencias principales.

## Evidencia

Fuentes explorables.

## Mi perspectiva

Consejo o reflexión.

## Explorar más

Preguntas relacionadas o caminos de navegación.

---

# Ejemplo conceptual

Pregunta:

> ¿Qué patrones se repiten en mis relaciones?

Respuesta:

```text
Basándome en las conversaciones disponibles,
aparecen tres patrones que vale la pena considerar.

01
Tiendes a posponer conversaciones difíciles...

[Evidencia: 6 conversaciones]

02
Durante periodos de estrés académico...

[Evidencia: 4 conversaciones]

03
...

────────────────────

Mi perspectiva

No parece que el problema sea únicamente...
```

---

# Panel visual paralelo

En desktop, la respuesta puede coexistir con una representación visual.

A la derecha:

- personas relevantes;
- eventos;
- temas;
- conexiones;
- cantidad de fuentes.

Cuando el usuario selecciona una afirmación:

- el grafo resalta las entidades relacionadas;
- las fuentes relevantes aparecen;
- el usuario puede explorar.

---

# Principio crítico

Nunca hacer que la evidencia sea secundaria.

La confianza del producto depende de:

> "¿Por qué LazoGraph piensa eso?"

El usuario debe poder responder esa pregunta.
