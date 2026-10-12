"""Version parsed text sources without inventing physical PDF coordinates."""
import hashlib
import json
from . import store
from .ingestion import source_id
from app.core.config import settings


def publish(document, tree_meta):
    text = document.full_text or ''
    if not text.strip():
        raise ValueError('Knowledge Source has no readable text')
    source = source_id(document)
    ident = hashlib.sha256(json.dumps([settings.kb_mcp_organization_id, source]).encode()).hexdigest()
    from app.utils.minio_client import minio_client
    data = minio_client.get_object(document.minio_key)
    sha = hashlib.sha256(data).hexdigest()
    version = hashlib.sha256(json.dumps([sha, text, tree_meta['root']], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    def node(value):
        return {'node_id': value['node_id'], 'title': value['title'],
                'start_index': 1, 'end_index': 1,
                'nodes': [node(child) for child in value.get('children', [])]}
    record = {'id': ident, 'version': version, 'sha256': sha, 'reading_sha256': sha,
              'organization_id': settings.kb_mcp_organization_id, 'source_id': source,
              'title': document.filename, 'page_count': 1, 'labels': [None], 'ocr_pages': [],
              'source_type': document.file_type, 'policy': 'kb-text-evidence-1',
              'tree': [node(tree_meta['root'])], 'pages': [{'page_index': 1, 'markdown': text}],
              'artifacts': {'original.pdf': document.minio_key},
              'source_metadata': {'kb_id': str(document.kb_id), 'kb_document_id': str(document.id),
                                  'original_key': document.minio_key}}
    store.put('document_version', ident + ':' + version, record)
    store.put('document', ident, record)
    metadata = dict(document.meta or {})
    metadata['pageindex_evidence'] = {'document_id': ident, 'version': version}
    document.meta = metadata
    return record
