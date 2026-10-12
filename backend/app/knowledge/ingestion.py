"""Publish exact PDF evidence into the same Knowledge Base as its upload."""
import hashlib
from datetime import datetime, timezone

from app.core.config import settings
from app.utils.minio_client import minio_client
from . import documents, store


def source_id(doc):
    return f'kb:{doc.kb_id}:document:{doc.id}'


def parse_pdf(data, filename):
    with store.workspace() as work:
        original = work / 'original.pdf'
        original.write_bytes(data)
        _, pages, labels, scanned = documents.prepare_pdf(original, work)
        text = '\n\n'.join(page['markdown'] for page in pages)
        if not text.strip():
            raise ValueError('PDF contains no readable text after OCR')
        return text, {'parse_engine': 'carefold-pageindex', 'source_type': 'pdf',
                      'source_name': filename, 'page_count': len(pages),
                      'printed_labels': labels, 'ocr_pages': scanned,
                      'parsed_at': datetime.now(timezone.utc).isoformat()}


def legacy_tree(record):
    """Keep existing search/chat contracts using exact page-to-text offsets."""
    offsets = []
    position = 0
    for page in record['pages']:
        offsets.append(position)
        position += len(page['markdown']) + 2
    total = max(0, position - 2)

    def node(item):
        start, end = item['start_index'], item['end_index']
        return {'node_id': item['node_id'], 'title': item['title'],
                'summary': item.get('summary', ''), 'start': offsets[start - 1],
                'end': offsets[end] - 2 if end < len(offsets) else total,
                'start_index': start, 'end_index': end,
                'children': [node(child) for child in item.get('nodes', [])]}

    root = {'node_id': 'document-root', 'title': record['title'], 'summary': '',
            'start': 0, 'end': total, 'children': [node(item) for item in record['tree']]}
    def count(n):
        return 1 + sum(count(child) for child in n['children'])
    return {'version': 2, 'created_at': datetime.now(timezone.utc).isoformat(),
            'model': settings.pageindex_llm_model, 'full_text_chars': total,
            'node_count': count(root), 'build_ms': 0, 'status': 'ok',
            'piece_count': 1, 'root': root}


def build_pdf_index(doc, db, *, force=False):
    # Serialize publication with deletion/reparse/rebuild for this document.
    # SQLAlchemy keeps the lock until the caller's transaction commits.
    from app.models import Document, KnowledgeBase
    current = db.query(Document).filter_by(id=doc.id).with_for_update().one()
    kb = db.query(KnowledgeBase).filter_by(id=current.kb_id, is_deleted=False).first()
    if current.is_deleted or kb is None:
        raise ValueError('Knowledge Source was deleted')
    with store.workspace() as work:
        original = work / 'upload.pdf'
        original.write_bytes(minio_client.get_object(current.minio_key))
        record = documents.import_pdf(original, title=current.filename,
            organization_id=settings.kb_mcp_organization_id, source_id=source_id(current),
            source_metadata={'kb_id': str(current.kb_id), 'kb_document_id': str(current.id),
                             'original_key': current.minio_key}, force=force)
    meta = dict(current.meta or {})
    tree = legacy_tree(record)
    meta.update(pageindex_tree=tree, pageindex_status='ok',
                pageindex_evidence={'document_id': record['id'], 'version': record['version']},
                page_count=record['page_count'], ocr_pages=record['ocr_pages'],
                printed_labels=record['labels'], parse_engine='carefold-pageindex')
    current.full_text = '\n\n'.join(page['markdown'] for page in record['pages'])
    current.meta = meta
    db.commit()
    return tree
