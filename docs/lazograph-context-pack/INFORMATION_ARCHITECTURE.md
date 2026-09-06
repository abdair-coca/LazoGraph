# Information Architecture

## Problema de la navegación anterior

La navegación anterior estaba demasiado fragmentada:

- Dashboard
- Importar
- Preguntar
- Buscar
- Timeline
- Grafo
- Planes
- Wiki
- Ops

Esto comunica una herramienta técnica y compleja.

El usuario no debería tener que comprender la arquitectura interna del sistema.

---

# Nueva arquitectura recomendada

## Principal

### Inicio

El punto de entrada personal.

Contiene:

- bienvenida contextual;
- pregunta principal;
- grafo/mundo vivo;
- recuerdos destacados;
- insights;
- actividad reciente.

### Preguntar

Espacio dedicado para conversar con LazoGraph sobre la historia personal.

No llamarlo "Preguntar al grafo" en UX principal.

El grafo es una implementación, no el concepto mental del usuario.

### Explorar

Una experiencia de descubrimiento.

Puede contener subniveles:

- Personas
- Temas
- Lugares
- Eventos
- Recuerdos

---

## Tu historia

### Historia

Timeline inteligente.

### Grafo

Vista espacial e inmersiva de conexiones.

Esta puede ser una experiencia más avanzada para usuarios que quieren navegar visualmente.

---

## Datos

### Importar

Entrada de nuevas fuentes.

### Fuentes

Estado de los datos importados.

---

## Sistema

### Ajustes

Privacidad, apariencia y configuración.

---

# Navegación recomendada

Versión expandida:

```text
LazoGraph

Inicio

Preguntar
Explorar

────────────

Historia
Grafo

────────────

Importar

────────────

Ajustes
```

---

# Principio

La navegación debe responder a acciones humanas:

- Quiero entender algo.
- Quiero explorar algo.
- Quiero recordar algo.

No a estructuras técnicas del backend.
