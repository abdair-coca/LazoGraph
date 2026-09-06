# Graph Experience

## Visión

El grafo es una representación visual del mundo personal del usuario.

No debe parecer una herramienta académica de graph theory.

---

# Principio visual

No usar exclusivamente círculos idénticos como nodos.

Las entidades deben tener personalidad visual.

---

# Personas

Las personas pueden representarse mediante:

- emojis;
- avatares;
- ilustraciones simples;
- símbolos distintivos.

Ejemplo conceptual:

```text
       ❤️ Alizon

          ╲
           ╲
           🧑‍💻 Tú
          ╱      ╲

       🏋️         💻
```

Cada persona puede tener:

- identidad visual;
- color;
- tamaño relativo;
- conexiones;
- microanimación;
- información contextual.

---

# Tipos de entidades

## Personas

Representación humana y distinguible.

## Temas

Símbolos o iconos conceptuales.

Ejemplo:

💻 Tecnología
❤️ Relaciones
🏋️ Fitness
📚 Estudios

## Lugares

📍
🏠
🏫
✈️

## Eventos

Momentos concretos de la historia.

---

# Tamaño

El tamaño visual puede comunicar:

- frecuencia;
- importancia;
- centralidad;
- actividad reciente.

Pero no debe utilizarse de manera que confunda al usuario.

---

# Relaciones

Las conexiones deben comunicar algo.

Posibles características:

- grosor = intensidad;
- transparencia = relevancia;
- color = tipo de relación;
- animación = actividad o descubrimiento.

No animar todas las líneas constantemente.

---

# Estados del grafo

## Estado ambiental

Movimiento sutil.

## Hover

La entidad responde y revela identidad.

## Focus

Se atenúa el contexto irrelevante.

Las conexiones importantes se iluminan.

## Deep exploration

El usuario puede expandir conexiones de segundo nivel.

---

# Panel contextual

Al seleccionar una persona:

```text
Alizon

1.284 mensajes
8 meses de historia

Conexiones principales:
• Relación
• Medicina
• Planes futuros

Momentos destacados:
[ ... ]

[ Explorar historia ]
```

---

# Grafo + narrativa

La visualización no debe ser el final.

Debe servir para contar una historia.

Ejemplo:

> Esta persona conecta tres etapas diferentes de tu historia.

El usuario debe poder pasar de la visualización a una explicación.

---

# Performance

El grafo debe seguir siendo fluido.

Para grafos grandes:

- clustering;
- progressive disclosure;
- nivel de detalle;
- virtualización cuando corresponda;
- no renderizar todo innecesariamente.

La espectacularidad nunca debe destruir la usabilidad.
