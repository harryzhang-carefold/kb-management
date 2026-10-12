"""Lossless bounded evidence delivery, independent of document and model names."""
import base64
import hashlib
import hmac
import json


class ReadingCursorError(ValueError):
    """The caller supplied a cursor that does not match its reading request."""


def serialize(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def read_batch(metadata, pages, *, identity, secret, cursor=None, max_chars=20000):
    records = [(page, passage) for page in pages for passage in (page['passages'] or [None])]

    def encode(index, offset):
        if index == len(records): return None
        body = base64.urlsafe_b64encode(serialize([identity, index, offset]).encode()).decode().rstrip('=')
        signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        return body + '.' + signature

    index, offset = 0, 0
    if cursor:
        try:
            body, signature = cursor.split('.')
            expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected): raise ValueError()
            binding, index, offset = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
            if binding != identity or type(index) is not int or type(offset) is not int or not 0 <= index < len(records) or offset < 0: raise ValueError()
            passage = records[index][1]
            if offset and (passage is None or offset >= len(passage['text'])): raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            raise ReadingCursorError('Invalid reading cursor for this document, version, pages or Invocation') from None

    delivered = []; spans = []

    def response(next_index, next_offset):
        grouped = []
        for page, passage in delivered:
            if not grouped or grouped[-1]['page'] != page['page']:
                grouped.append({k: v for k, v in page.items() if k != 'passages'} | {'passages': []})
            if passage is not None: grouped[-1]['passages'].append(passage)
        return metadata | {'pages': grouped, 'reading': {
            'requested_pages': [p['page'] for p in pages],
            'total_passages': sum(len(p['passages']) for p in pages),
            'next_cursor': encode(next_index, next_offset), 'complete': next_index == len(records),
        }}

    def fits(value):
        # JS and Runtime count UTF-16 characters; include JSON escaping and cursor.
        return len(serialize(value).encode('utf-16-le')) // 2 <= max_chars

    while index < len(records):
        page, original = records[index]
        if original is None:
            delivered.append((page, None))
        else:
            text = original['text']; remaining = text[offset:]
            passage = dict(original)
            if offset:
                passage |= {'text': remaining, 'text_offset': offset, 'total_text_chars': len(text), 'is_fragment': True}
            delivered.append((page, passage))
        candidate = response(index + 1, 0)
        if fits(candidate):
            if original is not None: spans.append((page['page'], original['id'], offset, len(text), len(text)))
            index += 1; offset = 0
            continue
        delivered.pop()
        if delivered: break
        if original is None: raise ValueError('Reading metadata exceeds response budget')
        # A single large passage remains source-backed; fragments have explicit offsets.
        low, high = 0, len(remaining)
        fragment = original | {'text': '', 'text_offset': offset, 'total_text_chars': len(text), 'is_fragment': True}
        delivered.append((page, fragment))
        while low < high:
            middle = (low + high + 1) // 2
            fragment['text'] = remaining[:middle]
            if fits(response(index, offset + middle)): low = middle
            else: high = middle - 1
        if low == 0: raise ValueError('Reading metadata exceeds response budget')
        fragment['text'] = remaining[:low]
        spans.append((page['page'], original['id'], offset, offset + low, len(text)))
        offset += low
        if offset == len(text): index += 1; offset = 0
        break
    result = response(index, offset)
    if not fits(result): raise ValueError('Reading metadata exceeds response budget')
    return result, spans


def fully_read(rows, total):
    end = 0
    for start, stop in sorted(rows):
        if start > end: return False
        end = max(end, stop)
    return bool(rows) and end >= total
