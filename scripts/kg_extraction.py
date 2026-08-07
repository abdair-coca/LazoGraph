"""Conservative multilingual person and relationship extraction primitives."""

import re
from collections import Counter


MIN_CONFIDENCE = 0.80
NAME_TOKEN = r'[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+'
PERSON_NAME = rf'{NAME_TOKEN}(?:\s+{NAME_TOKEN}){{0,2}}'

INVALID_NAME_TOKENS = {
    'ahora', 'ayer', 'buenas', 'buenos', 'chat', 'después', 'domingo', 'ella',
    'enero', 'febrero', 'gracias', 'he', 'hola', 'hoy', 'jueves', 'lunes',
    'mañana', 'martes', 'miércoles', 'mensaje', 'november', 'sábado', 'san', 'santa',
    'se', 'she', 'sistema', 'system', 'viernes', 'whatsapp',
}

EXPLICIT_RELATIONSHIPS = (
    (re.compile(rf'\b(?i:my\s+friend|mi\s+amig[oa])\s+(?P<name>{PERSON_NAME})\b'), 'friend_of'),
    (re.compile(rf'\b(?i:my\s+(?:brother|sister)|mi\s+herman[oa])\s+(?P<name>{PERSON_NAME})\b'), 'sibling_of'),
    (re.compile(rf'\b(?i:my\s+(?:mom|dad|mother|father)|mi\s+(?:mamá|madre|papá|padre))\s+(?P<name>{PERSON_NAME})\b'), 'parent_of'),
    (re.compile(rf'\b(?i:my\s+(?:wife|husband)|mi\s+espos[oa])\s+(?P<name>{PERSON_NAME})\b'), 'spouse_of'),
    (re.compile(rf'\b(?i:my\s+partner|mi\s+pareja)\s+(?P<name>{PERSON_NAME})\b'), 'partner_of'),
    (re.compile(rf'\b(?i:my\s+boss|mi\s+jef[ea])\s+(?P<name>{PERSON_NAME})\b'), 'reports_to'),
    (re.compile(rf'\b(?i:my\s+(?:colleague|coworker)|mi\s+(?:colega|compañer[oa](?:\s+de\s+trabajo)?))\s+(?P<name>{PERSON_NAME})\b'), 'colleague_of'),
)

CONTEXT_MENTIONS = (
    re.compile(rf'\b(?:with|told|asked|met|called|texted|emailed)\s+(?P<name>{PERSON_NAME})\b'),
    re.compile(rf'\b(?:con|(?:le\s+)?dije\s+a|pregunté\s+a|conocí\s+a|llamé\s+a|escribí\s+a|hablé\s+con|mensajeé\s+a)\s+(?P<name>{PERSON_NAME})\b'),
    re.compile(rf'\b(?:hola|oye|gracias|querid[oa])[,]?\s+(?P<name>{PERSON_NAME})\b', re.IGNORECASE),
    re.compile(rf'\b(?P<name>{PERSON_NAME})\s+(?:me\s+(?:dijo|preguntó|llamó|escribió)|(?:said|asked|called|wrote)\b)'),
)

COREFERENCE_RELATIONSHIPS = (
    (re.compile(r'\b(?:ella|él|she|he)\s+(?:es|is)\s+(?:mi|my)\s+amig[oa]?\b', re.IGNORECASE), 'friend_of'),
    (re.compile(r'\b(?:ella|él|she|he)\s+(?:es|is)\s+(?:mi|my)\s+jef[ea]?\b', re.IGNORECASE), 'reports_to'),
    (re.compile(r'\b(?:ella|él|she|he)\s+(?:es|is)\s+(?:mi|my)\s+(?:colega|coworker|colleague)\b', re.IGNORECASE), 'colleague_of'),
    (re.compile(r'\b(?:ella|él|she|he)\s+(?:es|is)\s+(?:mi|my)\s+(?:pareja|partner)\b', re.IGNORECASE), 'partner_of'),
)

MULTIWORD_NAME = re.compile(rf'\b(?P<name>{NAME_TOKEN}\s+{NAME_TOKEN}(?:\s+{NAME_TOKEN})?)\b')


def valid_person_name(name: str, known_names: set[str] | None = None) -> bool:
    clean = ' '.join(name.split()).strip('.,:;!?¿¡()[]{}')
    if not clean or len(clean) > 80 or '\n' in clean or '\r' in clean:
        return False
    if known_names and clean.casefold() in {item.casefold() for item in known_names}:
        return True
    tokens = clean.split()
    if not 1 <= len(tokens) <= 3:
        return False
    if any(token.casefold() in INVALID_NAME_TOKENS for token in tokens):
        return False
    return all(re.fullmatch(NAME_TOKEN, token) for token in tokens)


def extract_message_facts(
    content: str,
    *,
    sender: str,
    known_names: set[str],
    recent_entity: str | None = None,
) -> dict:
    """Extract high-confidence facts from one message with bounded coreference."""
    mentions = {}
    relationships = []
    rejected = []

    def mention(name: str, confidence: float, method: str):
        clean = ' '.join(name.split()).strip('.,:;!?¿¡()[]{}')
        if confidence < MIN_CONFIDENCE or not valid_person_name(clean, known_names):
            rejected.append({'name': clean, 'confidence': confidence, 'method': method})
            return
        current = mentions.get(clean.casefold())
        if current is None or confidence > current['confidence']:
            mentions[clean.casefold()] = {
                'name': clean, 'confidence': confidence, 'method': method,
            }

    for name in known_names:
        if name and re.search(rf'(?<!\w){re.escape(name)}(?!\w)', content, re.IGNORECASE):
            mention(name, 0.99, 'known-identity')

    for pattern, relationship_type in EXPLICIT_RELATIONSHIPS:
        for match in pattern.finditer(content):
            name = match.group('name')
            mention(name, 0.96, 'explicit-relationship')
            if valid_person_name(name, known_names):
                relationships.append({
                    'from': name,
                    'to': sender,
                    'type': relationship_type,
                    'confidence': 0.96,
                    'method': 'explicit-relationship',
                })

    for pattern in CONTEXT_MENTIONS:
        for match in pattern.finditer(content):
            mention(match.group('name'), 0.90, 'context-ner')

    for match in MULTIWORD_NAME.finditer(content):
        start = match.start('name')
        if start == 0 or content[max(0, start - 2):start].endswith(('. ', '! ', '? ')):
            continue
        mention(match.group('name'), 0.82, 'multiword-ner')

    if recent_entity and valid_person_name(recent_entity, known_names):
        for pattern, relationship_type in COREFERENCE_RELATIONSHIPS:
            if pattern.search(content):
                mention(recent_entity, 0.84, 'bounded-coreference')
                relationships.append({
                    'from': recent_entity,
                    'to': sender,
                    'type': relationship_type,
                    'confidence': 0.84,
                    'method': 'bounded-coreference',
                })

    ordered_mentions = sorted(
        mentions.values(),
        key=lambda item: (-item['confidence'], item['name'].casefold()),
    )
    return {
        'mentions': ordered_mentions,
        'relationships': relationships,
        'rejected': rejected,
        'recent_entity': ordered_mentions[0]['name'] if ordered_mentions else recent_entity,
    }


def extract_content_facts(messages: list[dict], known_names: set[str]) -> dict:
    """Extract facts sequentially; coreference expires after two messages per sender."""
    entities = set()
    relationships = []
    rejected = []
    recent = {}
    methods = Counter()
    for message in messages:
        if message.get('role') != 'assistant':
            continue
        sender = str(message.get('metadata', {}).get('sender', '')).strip()
        sender_key = sender.casefold()
        previous_name, age = recent.get(sender_key, (None, 99))
        facts = extract_message_facts(
            str(message.get('content', '')),
            sender=sender,
            known_names=known_names,
            recent_entity=previous_name if age <= 2 else None,
        )
        for item in facts['mentions']:
            if item['name'].casefold() != sender_key:
                entities.add(item['name'])
            methods[item['method']] += 1
        for relationship in facts['relationships']:
            relationship = {
                **relationship,
                'timestamp': message.get('timestamp'),
                'source': message.get('source_file'),
            }
            relationships.append(relationship)
            methods[relationship['method']] += 1
        rejected.extend(facts['rejected'])
        if facts['mentions']:
            recent[sender_key] = (facts['recent_entity'], 0)
        elif previous_name:
            recent[sender_key] = (previous_name, age + 1)
    return {
        'entities': entities,
        'relationships': relationships,
        'diagnostics': {
            'accepted_entities': len(entities),
            'accepted_relationships': len(relationships),
            'rejected_candidates': len(rejected),
            'methods': dict(sorted(methods.items())),
        },
    }


def evaluate_cases(cases: list[dict]) -> dict:
    """Measure entity precision/recall/F1 on explicitly labeled text cases."""
    true_positive = false_positive = false_negative = 0
    for case in cases:
        facts = extract_message_facts(
            str(case.get('text', '')),
            sender=str(case.get('sender', 'Persona')),
            known_names=set(map(str, case.get('known_names', []))),
        )
        actual = {item['name'].casefold() for item in facts['mentions']}
        expected = {str(item).casefold() for item in case.get('expected_entities', [])}
        true_positive += len(actual & expected)
        false_positive += len(actual - expected)
        false_negative += len(expected - actual)
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        'cases': len(cases),
        'true_positive': true_positive,
        'false_positive': false_positive,
        'false_negative': false_negative,
        'precision': round(precision, 4),
        'recall': round(recall, 4),
        'f1': round(f1, 4),
    }
