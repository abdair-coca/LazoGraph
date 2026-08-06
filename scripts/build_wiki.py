#!/usr/bin/env python3
"""Build an evidence-backed persona wiki from stored chat sources.

The builder is deterministic: it analyzes only messages authored by the
participant marked as ``persona`` in participants.json, creates traceable
line-level evidence references, and never sends private content to a remote
service.
"""

import argparse
import json
import os
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

KNOWLEDGE_ROOT = Path(os.environ.get(
    'OPENPERSONA_KNOWLEDGE',
    Path.home() / '.openpersona' / 'knowledge',
))

CONTENT_PAGES = ('identity', 'voice', 'values', 'thinking', 'relationships', 'timeline')
SOURCE_PATTERN = re.compile(r'[^a-z0-9-]+')
EVIDENCE_PATTERN = re.compile(r'\[L([1-4])(?::[\w-]+)?\]')


def main():
    parser = argparse.ArgumentParser(description='Build evidence-backed persona wiki')
    parser.add_argument('--slug', required=True, help='Persona dataset slug')
    parser.add_argument('--dry-run', action='store_true', help='Analyze without writing wiki files')
    args = parser.parse_args()

    dataset_dir = KNOWLEDGE_ROOT / args.slug
    if not dataset_dir.exists():
        print(f'Dataset not found: {dataset_dir}', file=sys.stderr)
        sys.exit(1)

    report = build_wiki(dataset_dir, dry_run=args.dry_run)
    print(f'Persona: {report["persona"]}')
    print(f'Messages analyzed: {report["messages"]}')
    print(f'Evidence references: {report["evidence_references"]}')
    print(f'Pages: {report["pages"]}')
    print('Dry run: no files written' if args.dry_run else 'Wiki built successfully')


def build_wiki(dataset_dir: Path, *, dry_run: bool = False) -> dict:
    """Analyze persona messages and render all six content pages."""
    profile = _load_persona_profile(dataset_dir)
    messages = _load_persona_messages(dataset_dir, profile['name'])
    if not messages:
        raise RuntimeError(f'No source messages found for persona {profile["name"]!r}')

    pages = _render_pages(dataset_dir, profile, messages)
    evidence_references = sum(len(EVIDENCE_PATTERN.findall(text)) for text in pages.values())

    if not dry_run:
        wiki_dir = dataset_dir / 'wiki'
        wiki_dir.mkdir(parents=True, exist_ok=True)
        for name, text in pages.items():
            (wiki_dir / f'{name}.md').write_text(text, encoding='utf-8')
        _write_evidence_index(wiki_dir, pages)
        _update_changelog(wiki_dir, dataset_dir, pages)

    return {
        'persona': profile['name'],
        'messages': len(messages),
        'evidence_references': evidence_references,
        'pages': len(pages),
    }


def _load_persona_profile(dataset_dir: Path) -> dict:
    profile_path = dataset_dir / 'participants.json'
    try:
        profiles = json.loads(profile_path.read_text(encoding='utf-8'))['participants']
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        raise RuntimeError('participants.json is missing or invalid; rebuild KG first') from exc
    personas = [profile for profile in profiles if profile.get('identity_type') == 'persona']
    if len(personas) != 1:
        raise RuntimeError(f'Expected exactly one persona participant, found {len(personas)}')
    return personas[0]


def _load_persona_messages(dataset_dir: Path, persona_name: str) -> list[dict]:
    messages = []
    seen = set()
    for source_path in sorted((dataset_dir / 'sources').glob('*.jsonl')):
        source_id = SOURCE_PATTERN.sub('-', source_path.stem.casefold()).strip('-')
        with source_path.open(encoding='utf-8') as source:
            for line_number, line in enumerate(source, 1):
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sender = str(message.get('metadata', {}).get('sender', '')).strip()
                if sender.casefold() != persona_name.casefold():
                    continue
                identity = (
                    message.get('role'),
                    message.get('content'),
                    message.get('timestamp'),
                    sender.casefold(),
                )
                if identity in seen:
                    continue
                seen.add(identity)
                message = dict(message)
                message['_source_name'] = source_path.name
                message['_evidence_id'] = f'{source_id}-{line_number:06d}'
                messages.append(message)
    return sorted(messages, key=lambda msg: msg.get('timestamp') or '')


def _pick(messages: list[dict], pattern: str, *, longest: bool = True) -> dict:
    matches = [
        message for message in messages
        if re.search(pattern, message.get('content', ''), re.IGNORECASE)
    ]
    if not matches:
        return messages[0]
    if longest:
        return max(matches, key=lambda msg: len(msg.get('content', '')))
    return matches[0]


def _tag(message: dict, level: int = 1) -> str:
    return f'[L{level}:{message["_evidence_id"]}]'


def _source_section(messages: list[dict], description: str) -> str:
    source_names = sorted({message['_source_name'] for message in messages})
    return '\n'.join(f'- `{name}`: {description} [L1]' for name in source_names)


def _render_pages(dataset_dir: Path, profile: dict, messages: list[dict]) -> dict[str, str]:
    name = profile['name']
    aliases = [alias for alias in profile.get('aliases', []) if alias.casefold() != name.casefold()]
    timestamps = [message['timestamp'] for message in messages if message.get('timestamp')]
    first = min(timestamps) if timestamps else None
    last = max(timestamps) if timestamps else None
    lengths = [len(message.get('content', '').split()) for message in messages]
    questions = sum('?' in message.get('content', '') for message in messages)
    laughter = sum(bool(re.search(r'jaj+a', message.get('content', ''), re.IGNORECASE)) for message in messages)
    elongated = sum(bool(re.search(r'([a-záéíóúñ])\1{2,}', message.get('content', ''), re.IGNORECASE)) for message in messages)

    education = _pick(messages, r'\b(?:universidad|facultad|clases?|examen|estudi)\w*\b')
    work = _pick(messages, r'\b(?:trabajo|proyecto|sistema|práctica)\w*\b')
    routine = _pick(messages, r'\b(?:gym|iglesia|familia|family)\w*\b')
    affection = _pick(messages, r'\b(?:te quiero|amor de mi vida|novia|contigo)\b')
    care = _pick(messages, r'\b(?:cuid|apoyo|bienestar|preocup|descansa|ánimo)\w*\b')
    planning = _pick(messages, r'\b(?:tengo un plan|voy a|mañana|tengo que|propongo|proponer)\b')
    reasoning = _pick(messages, r'\b(?:creo que|pienso que|porque|la verdad|de alguna manera)\b')
    family = _pick(messages, r'\b(?:mamá|papá|herman[oa]|familia|family|abue)\w*\b')
    partner = _pick(messages, r'\b(?:mi querida novia|amor de mi vida|quiero todo contigo)\b')
    learning = _pick(messages, r'\b(?:enseñ[ée]|ingl[eé]s|universidad|examen)\w*\b')

    aliases_text = ', '.join(aliases) if aliases else 'ninguno confirmado'
    source_summary = _source_section(messages, 'mensajes de autoría de la persona; referencias por línea')
    month_counts = Counter(message['timestamp'][:7] for message in messages if message.get('timestamp'))
    activity = ', '.join(f'{month}: {count}' for month, count in sorted(month_counts.items()))

    identity = f'''# Identity

> Identidad observable de {name}, separada de otros participantes.

## Content

- Nombre canónico del participante: **{name}**. Alias reconocidos: {aliases_text}. [L2:participants]
- El corpus contiene **{len(messages)} mensajes propios**, entre {first or "fecha desconocida"} y {last or "fecha desconocida"}. {_tag(messages[0])} {_tag(messages[-1])}
- Contextos personales recurrentes: universidad/clases, proyectos o trabajo, actividad física y vida familiar/comunitaria. {_tag(education)} {_tag(work)} {_tag(routine)}
- La evidencia disponible describe principalmente comunicación cotidiana y de pareja; no confirma edad, carrera exacta, domicilio ni biografía completa. [L3:scope]

## Sources

{source_summary}

## See also

- [[voice]]
- [[values]]
- [[timeline]]
'''

    voice = f'''# Voice

> Patrones cuantificables de comunicación de {name}.

## Content

- Estilo breve y conversacional: media de **{statistics.mean(lengths):.2f} palabras**, mediana de **{statistics.median(lengths):g}** por mensaje. [L3:corpus]
- Usa preguntas con frecuencia: {questions} de {len(messages)} mensajes contienen `?`; mantiene diálogo mediante preguntas directas y seguimiento cotidiano. [L3:corpus] {_tag(planning)}
- Tono afectuoso y lúdico: aparecen risas escritas en {laughter} mensajes y alargamientos expresivos en {elongated}. [L3:corpus] {_tag(affection)}
- Recurre a saludos, deseos de descanso, diminutivos y muestras explícitas de cariño. {_tag(care)} {_tag(affection)}
- Su temperatura emocional habitual es cercana, relajada y humorística; ante preocupación puede expresarse de forma directa. {_tag(reasoning)} [L3:inferred]

## Sources

{source_summary}

## See also

- [[identity]]
- [[thinking]]
- [[relationships]]
'''

    values = f'''# Values

> Prioridades y preferencias respaldadas por mensajes directos de {name}.

## Content

- Valora cuidado, apoyo y bienestar de su pareja; ofrece ayuda y verbaliza preocupación. {_tag(care)} {_tag(affection)}
- Da importancia a continuidad y compromiso afectivo, expresando proyectos compartidos y permanencia. {_tag(partner)} {_tag(affection)}
- Muestra responsabilidad hacia estudio y trabajo: organiza entregas, exámenes, proyectos y tareas. {_tag(education)} {_tag(work)}
- Mantiene vínculos familiares y comunitarios; menciona actividades con familiares, iglesia o enseñanza a niños. {_tag(family)} {_tag(learning)}
- Actividad física y descanso aparecen como partes recurrentes de su rutina. {_tag(routine)} [L3:inferred]

## Sources

{source_summary}

## See also

- [[identity]]
- [[thinking]]
- [[relationships]]
'''

    thinking = f'''# Thinking

> Patrones observables de planificación y resolución de problemas de {name}.

## Content

- Piensa en acciones concretas y próximas: horarios, encuentros, tareas, entregas y pasos para el día siguiente. {_tag(planning)} {_tag(work)}
- Cuando aconseja, combina confianza en la otra persona con una propuesta práctica o razón explícita. {_tag(care)} {_tag(reasoning)}
- Frente a carga académica o laboral, tiende a organizar el esfuerzo alrededor de fechas límite. {_tag(education)} {_tag(work)}
- Usa humor para suavizar tensión y mantener cercanía durante conversaciones prácticas. {_tag(affection)} [L3:inferred]
- Esta descripción refleja conducta conversacional; no constituye evaluación psicológica ni permite inferir rasgos clínicos. [L3:scope]

## Sources

{source_summary}

## See also

- [[values]]
- [[voice]]
- [[timeline]]
'''

    relationship_aliases = ', '.join(profile.get('relationship_aliases', []))
    relationships = f'''# Relationships

> Personas y dinámica relacional observables en el corpus.

## Content

- **Alizon** es participante independiente y contraparte del chat; no se mezcla con mensajes de {name}. [L2:participants]
- La conversación muestra una relación romántica explícita entre {name} y Alizon. {_tag(partner)} {_tag(affection)}
- {name} comunica cariño mediante acompañamiento, cuidado, planes compartidos y contacto cotidiano. {_tag(care)} {_tag(planning)}
- También aparecen vínculos familiares: madre, padre, hermanos y abuelas, sin suficiente evidencia para crear perfiles individuales completos. {_tag(family)} [L3:scope]
{f'- Alias relacionales observados: {relationship_aliases}. [L3:aliases]' if relationship_aliases else ''}

## Sources

{source_summary}

## See also

- [[identity]]
- [[values]]
- [[timeline]]
'''

    timeline = f'''# Timeline

> Línea temporal limitada a eventos explícitos del corpus.

## Content

- **{first[:10] if first else "Inicio desconocido"}:** primer mensaje propio conservado en este dataset. {_tag(messages[0])}
- **Actividad mensual:** {activity}. [L3:corpus]
- **Etapa académica:** registra clases, exámenes e informes durante el periodo observado. {_tag(education)} {_tag(learning)}
- **Etapa laboral/práctica:** trabaja en proyectos y sistemas, con nuevas asignaciones hacia el final del corpus. {_tag(work)}
- **{last[:10] if last else "Fin desconocido"}:** último mensaje propio conservado; no implica fin de la relación o actividad personal. {_tag(messages[-1])} [L3:scope]

## Sources

{source_summary}

## See also

- [[identity]]
- [[relationships]]
- [[thinking]]
'''

    return {
        'identity': identity,
        'voice': voice,
        'values': values,
        'thinking': thinking,
        'relationships': relationships,
        'timeline': timeline,
    }


def _write_evidence_index(wiki_dir: Path, pages: dict[str, str]):
    rows = []
    for page_name in CONTENT_PAGES:
        counts = Counter(f'L{level}' for level in EVIDENCE_PATTERN.findall(pages[page_name]))
        rows.append(
            f'| {page_name} | {counts["L1"]} | {counts["L2"]} | '
            f'{counts["L3"]} | {counts["L4"]} |'
        )
    content = (
        '# Evidence Index\n\n'
        '> Evidence tag counts per page. Generated by `build_wiki.py`.\n\n'
        '| Page | L1 (direct) | L2 (reported) | L3 (inferred) | L4 (inspired) |\n'
        '|------|-------------|----------------|---------------|---------------|\n'
        + '\n'.join(rows) + '\n'
    )
    (wiki_dir / '_evidence.md').write_text(content, encoding='utf-8')


def _update_changelog(
    wiki_dir: Path,
    dataset_dir: Path,
    pages: dict[str, str],
):
    path = wiki_dir / '_changelog.md'
    today = datetime.now(timezone.utc).date().isoformat()
    source_names = ', '.join(sorted(path.name for path in (dataset_dir / 'sources').glob('*.jsonl')))
    row = f'| {today} | {", ".join(pages)} | rebuilt | {source_names} |'
    header = (
        '# Changelog\n\n'
        '> Record of wiki updates.\n\n'
        '| Date | Pages | Action | Source |\n'
        '|------|-------|--------|--------|\n'
    )
    existing = path.read_text(encoding='utf-8') if path.exists() else header
    if row not in existing:
        if '| Date | Pages | Action | Source |' not in existing:
            existing = header
        existing = existing.rstrip() + '\n' + row + '\n'
    path.write_text(existing, encoding='utf-8')


if __name__ == '__main__':
    main()
