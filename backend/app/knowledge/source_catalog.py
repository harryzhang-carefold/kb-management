"""Published source references shared by discovery and authenticated search.

These are versioned locators, not read receipts or verified source claims.
The caller owns authorization; original document rows supply every field.
"""
import json


def document_reference(doc):
    meta = doc.meta or {}
    page = meta.get('pageindex_evidence')
    cells = meta.get('spreadsheet_evidence')
    return {
        'document_id': str(doc.id), 'kb_document_id': str(doc.id),
        'kb_id': str(doc.kb_id), 'title': doc.filename,
        'source_id': f'kb:{doc.kb_id}:document:{doc.id}',
        'source_type': doc.file_type, 'status': doc.status,
        'version': (cells or page or {}).get('version'),
        'evidence': {'parsed_text': page, 'native_cells': cells},
        'read_methods': (['pageindex_read_pages'] if page else []) +
                        (['spreadsheet_read_cells'] if cells else []),
    }


def encode_search_payload(payload, max_chars=64000):
    """Optional references must not enlarge a fitting search beyond its bound.

    Retain all requested search hits. If metadata cannot fit, explicitly mark
    the source catalog partial; normal authorized discovery remains available.
    An already-oversized legacy search still follows the existing adapter limit.
    """
    result = dict(payload)
    result['documents'] = list(payload.get('documents', []))
    # Explicitly distinguish a complete catalog for the returned search hits
    # from a catalog truncated by the bounded response. This never claims the
    # entire Knowledge Base was enumerated.
    result['source_catalog_scope'] = 'returned_hits'
    result['source_catalog_complete'] = True
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    while result['documents'] and len(encoded.encode('utf-16-le')) // 2 > max_chars:
        result['documents'].pop()
        result['source_catalog_complete'] = False
        encoded = json.dumps(result, ensure_ascii=False, indent=2)
    return encoded
