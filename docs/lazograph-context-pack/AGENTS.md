# Instructions for Coding Agents

## Context

You are working on LazoGraph.

Before making significant changes, read:

1. `CONSTITUTION.md`
2. `PRODUCT.md`
3. `USER_EXPERIENCE.md`
4. `DESIGN_SYSTEM.md`

Then read the document corresponding to the area you are modifying.

---

# Mission

Your mission is not merely to implement requested components.

Your mission is to move the product toward the LazoGraph vision:

> A personal intelligence system that helps users understand their own history through conversations and evidence.

---

# Working principles

## 1. Understand before changing

Before large changes:

- inspect the existing implementation;
- identify reusable components;
- understand routing;
- understand design tokens;
- avoid replacing architecture unnecessarily.

Do not rewrite working systems merely because another approach is personally preferred.

---

## 2. Preserve product intent

When requirements are ambiguous, prefer the solution that:

- feels more personal;
- reduces technical language;
- increases discoverability;
- strengthens evidence and trust;
- supports exploration.

---

## 3. Avoid generic AI dashboards

Do not default to:

- purple gradients;
- glowing borders everywhere;
- excessive glassmorphism;
- dozens of KPI cards;
- chatbot layouts copied from common AI products.

LazoGraph must feel distinctive.

---

## 4. Design hierarchy

Every important screen should answer:

1. What is this screen for?
2. What should the user do first?
3. What can they discover?
4. What happens next?

Do not present every action with equal visual weight.

---

## 5. Component quality

Build reusable primitives when patterns repeat.

Examples:

- EntityAvatar
- MemoryCard
- EvidenceSource
- InsightCard
- GraphNode
- QuestionSuggestion
- ContextPanel

Do not create giant monolithic components if the existing architecture supports composition.

---

## 6. Graph implementation

The graph must be useful.

Before adding visual effects, ensure:

- entities are distinguishable;
- labels remain understandable;
- focus state works;
- selection works;
- relationships communicate meaning;
- large graphs remain performant.

---

## 7. Motion

Use motion intentionally.

Every animation should answer:

> What changed?

Motion should communicate state transitions and spatial relationships.

Respect reduced-motion preferences.

---

## 8. Accessibility

Do not sacrifice accessibility for visual quality.

Ensure:

- keyboard navigation;
- focus states;
- contrast;
- semantic structure;
- screen-reader labels where needed.

Canvas/WebGL graph experiences must still expose meaningful accessible alternatives where possible.

---

## 9. Responsive design

Do not simply shrink desktop.

Reconsider:

- hierarchy;
- density;
- interaction model;
- graph controls;
- side panels.

Mobile should feel intentionally designed.

---

## 10. Evidence UX

Any feature involving AI conclusions should consider evidence.

Prefer a UI where the user can inspect:

```text
Claim
↓
Evidence group
↓
Conversation
↓
Original message
```

---

# Before implementing a feature

Answer internally:

- What user problem does this solve?
- Which LazoGraph principle does it reinforce?
- Does it make the experience more human or more technical?
- What is the primary action?
- How does it behave on mobile?
- Does it need loading, empty and error states?

---

# Definition of done

A feature is not done merely when it compiles.

It should have:

- coherent hierarchy;
- responsive behavior;
- loading state where applicable;
- empty state where applicable;
- interaction states;
- accessible controls;
- visual consistency;
- no obvious regressions.

---

# Do not

- invent product requirements as facts;
- remove useful functionality without reason;
- replace the warm identity with generic SaaS aesthetics;
- expose internal graph/database terminology unnecessarily;
- add animations without purpose;
- hide evidence behind inaccessible UI;
- prioritize visual spectacle over usability.

---

# Preferred implementation approach

For substantial UI work:

1. Inspect.
2. Plan.
3. Explain intended changes briefly.
4. Implement incrementally.
5. Validate visually and functionally.
6. Check responsiveness.
7. Review against `CONSTITUTION.md`.

---

# Final quality question

Before considering work complete, ask:

> Does this feel like a tool for analyzing data, or like a place for understanding a person's own history?

Prefer the second.
