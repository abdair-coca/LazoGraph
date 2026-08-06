"""
Chat export adapter.

Handles WhatsApp (.txt), Telegram (result.json), Signal (JSON array),
and iMessage (SQLite .db).
"""

import json
import re
import sqlite3
from pathlib import Path


def parse(source_path: str, *, persona_name: str = '', since: str | None = None, **kwargs) -> list[dict]:
    p = Path(source_path)

    if p.suffix == '.db':
        return _parse_imessage(p, persona_name=persona_name)

    if p.suffix == '.txt':
        return _parse_whatsapp(p, persona_name=persona_name)

    if p.suffix == '.json':
        data = json.loads(p.read_text(errors='replace'))
        if isinstance(data, dict) and 'chats' in data:
            return _parse_telegram(data, persona_name=persona_name)
        if isinstance(data, list):
            if data and 'sender' in data[0]:
                return _parse_signal(data, persona_name=persona_name)

    raise ValueError(f'Unrecognized chat export format: {source_path}')


# --- WhatsApp ---

_WA_DATE = r'\d{1,2}/\d{1,2}/\d{2,4}'
_WA_TIME = r'\d{1,2}:\d{2}(?::\d{2})?'
_WA_MERIDIEM = r'(?:[AaPp](?:\s*\.\s*[Mm]\.?)?|[AaPp][Mm])?'
_WA_TIMESTAMP = rf'{_WA_DATE},?\s*{_WA_TIME}\s*{_WA_MERIDIEM}'
_WA_ANDROID_HEADER = re.compile(
    rf'^[\ufeff\u200e\u200f]*(?P<timestamp>{_WA_TIMESTAMP})\s*-\s*(?P<body>.*)$'
)
_WA_IOS_HEADER = re.compile(
    rf'^[\ufeff\u200e\u200f]*\[(?P<timestamp>{_WA_TIMESTAMP})\]\s*(?P<body>.*)$'
)
_WA_MEDIA_OMITTED = {
    '<media omitted>',
    '<multimedia omitido>',
    'imagen omitida',
    'video omitido',
    'audio omitido',
    'sticker omitido',
}
_WA_SYSTEM_NOTICE_PREFIXES = (
    'los mensajes y las llamadas están cifrados',
    'messages and calls are end-to-end encrypted',
    'se actualizó la duración de los mensajes',
    'se actualizaron los mensajes temporales',
    'se activaron los mensajes temporales',
    'se desactivaron los mensajes temporales',
    'disappearing messages were turned on',
    'disappearing messages were turned off',
    'you changed the disappearing messages timer',
)


def _match_whatsapp_header(line: str):
    """Return a WhatsApp header match for Android or iOS exports."""
    return _WA_ANDROID_HEADER.match(line) or _WA_IOS_HEADER.match(line)


def is_whatsapp_system_notice(text: str) -> bool:
    """Identify known WhatsApp-generated notices, never human senders."""
    normalized = re.sub(r'\s+', ' ', text).strip().casefold()
    return any(normalized.startswith(prefix) for prefix in _WA_SYSTEM_NOTICE_PREFIXES)


def looks_like_whatsapp(text: str) -> bool:
    """Detect a WhatsApp export without assuming English timestamp spacing."""
    for line in text.splitlines():
        match = _match_whatsapp_header(line)
        if match and ':' in match.group('body'):
            sender, _, _ = match.group('body').partition(':')
            if sender.strip():
                return True
    return False


def _parse_whatsapp(path: Path, *, persona_name: str) -> list[dict]:
    text = path.read_text(encoding='utf-8-sig', errors='replace')
    messages = []
    persona_lower = persona_name.lower().strip()
    current = None

    def flush_current():
        nonlocal current
        if current is None:
            return

        content = '\n'.join(current.pop('content_lines')).strip()
        if content and content.casefold() not in _WA_MEDIA_OMITTED:
            current['content'] = content
            messages.append(current)
        current = None

    for line in text.splitlines():
        match = _match_whatsapp_header(line)
        if match:
            flush_current()
            body = match.group('body')

            # Some notices contain a colon, so checking only for a sender
            # separator would incorrectly turn the notice into a participant.
            if is_whatsapp_system_notice(body):
                continue

            sender, separator, content = body.partition(':')

            # Timestamped system notices have no sender separator. They end
            # the previous multiline message but are not persona messages.
            if not separator or not sender.strip():
                continue

            sender = sender.strip()
            is_persona = bool(persona_lower and persona_lower in sender.lower())
            current = {
                'role': 'assistant' if is_persona else 'user',
                'content_lines': [content.strip()],
                'timestamp': _normalize_wa_ts(match.group('timestamp')),
                'source_file': path.name,
                'source_type': 'whatsapp',
                'metadata': {'sender': sender},
            }
            continue

        if current is not None:
            current['content_lines'].append(line)

    flush_current()
    return messages

def _normalize_wa_ts(raw: str) -> str:
    localized_meridiem = bool(re.search(r'(?i)[ap]\s*\.\s*m\.?', raw))
    cleaned = raw.translate(str.maketrans({
        '\u00a0': ' ',
        '\u202f': ' ',
        '\u200e': None,
        '\u200f': None,
        '\ufeff': None,
    }))
    cleaned = re.sub(
        r'(?i)([ap])\s*\.\s*m\.?',
        lambda match: f'{match.group(1).upper()}M',
        cleaned,
    )
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    date_part = cleaned.split(',', 1)[0].split(' ', 1)[0]
    try:
        first_date_number = int(date_part.split('/', 1)[0])
    except (ValueError, IndexError):
        first_date_number = 0

    day_first = localized_meridiem or first_date_number > 12
    date_orders = ('%d/%m', '%m/%d') if day_first else ('%m/%d', '%d/%m')
    formats = []
    for date_order in date_orders:
        for year in ('%y', '%Y'):
            for separator in (', ', ' '):
                formats.extend((
                    f'{date_order}/{year}{separator}%I:%M %p',
                    f'{date_order}/{year}{separator}%I:%M:%S %p',
                    f'{date_order}/{year}{separator}%H:%M',
                    f'{date_order}/{year}{separator}%H:%M:%S',
                ))

    for fmt in formats:
        try:
            from datetime import datetime
            return datetime.strptime(cleaned, fmt).isoformat()
        except ValueError:
            continue
    return cleaned


# --- Telegram ---

def _parse_telegram(data: dict, *, persona_name: str) -> list[dict]:
    messages = []
    persona_lower = persona_name.lower().strip()
    chat_list = data.get('chats', {}).get('list', [])

    for chat in chat_list:
        for msg in chat.get('messages', []):
            sender = msg.get('from', msg.get('from_id', ''))
            text_parts = msg.get('text', '')

            if isinstance(text_parts, list):
                text = ''.join(
                    p if isinstance(p, str) else p.get('text', '')
                    for p in text_parts
                )
            else:
                text = str(text_parts)

            if not text.strip():
                continue

            is_persona = bool(persona_lower and persona_lower in str(sender).lower())

            messages.append({
                'role': 'assistant' if is_persona else 'user',
                'content': text.strip(),
                'timestamp': msg.get('date'),
                'source_file': 'telegram-export',
                'source_type': 'telegram',
                'metadata': {'sender': str(sender), 'chat': chat.get('name', '')},
            })

    return messages


# --- Signal ---

def _parse_signal(data: list, *, persona_name: str) -> list[dict]:
    messages = []
    persona_lower = persona_name.lower().strip()

    for msg in data:
        sender = msg.get('sender', msg.get('source', ''))
        body = msg.get('body', msg.get('text', ''))
        if not body or not body.strip():
            continue

        ts = msg.get('timestamp')
        if isinstance(ts, (int, float)) and ts > 1e12:
            from datetime import datetime
            ts = datetime.fromtimestamp(ts / 1000).isoformat()
        elif isinstance(ts, (int, float)):
            from datetime import datetime
            ts = datetime.fromtimestamp(ts).isoformat()

        is_persona = bool(persona_lower and persona_lower in str(sender).lower())

        messages.append({
            'role': 'assistant' if is_persona else 'user',
            'content': body.strip(),
            'timestamp': str(ts) if ts else None,
            'source_file': 'signal-export',
            'source_type': 'signal',
            'metadata': {'sender': str(sender)},
        })

    return messages


# --- iMessage ---

_IMESSAGE_QUERY = '''
SELECT
    m.text,
    m.is_from_me,
    m.date,
    h.id AS handle_id
FROM message m
LEFT JOIN handle h ON m.handle_id = h.ROWID
WHERE m.text IS NOT NULL AND m.text != ''
ORDER BY m.date ASC
'''


def _parse_imessage(db_path: Path, *, persona_name: str) -> list[dict]:
    messages = []

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(_IMESSAGE_QUERY)
    except sqlite3.Error as e:
        raise ValueError(f'Failed to read iMessage database: {e}')

    for text, is_from_me, date_val, handle_id in cursor:
        if not text or not text.strip():
            continue

        ts = None
        if date_val:
            from datetime import datetime
            try:
                # iMessage stores nanoseconds since 2001-01-01
                epoch_offset = 978307200
                ts = datetime.fromtimestamp(date_val / 1e9 + epoch_offset).isoformat()
            except (ValueError, OSError):
                ts = str(date_val)

        messages.append({
            'role': 'assistant' if is_from_me else 'user',
            'content': text.strip(),
            'timestamp': ts,
            'source_file': db_path.name,
            'source_type': 'imessage',
            'metadata': {'handle': handle_id or '', 'is_from_me': bool(is_from_me)},
        })

    conn.close()
    return messages
