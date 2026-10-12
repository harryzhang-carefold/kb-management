#!/usr/bin/env python3
"""Adopt verified 9383 evidence for existing identical KB uploads, without deletion."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.core.config import settings
from app.core.database import SessionLocal
from app.models import Document, KnowledgeBase
from app.utils.minio_client import minio_client
from app.knowledge import documents, store
from app.knowledge.ingestion import source_id, legacy_tree


def migrate(directory):
    connection = sqlite3.connect(f'file:{directory / "knowledge.sqlite3"}?mode=ro', uri=True)
    try:
        records = [json.loads(row[0]) for row in connection.execute("SELECT value FROM records WHERE kind='document'")]
    finally:
        connection.close()
    adopted = []
    for old in records:
        folder = directory / 'documents' / old['id'] / old['version']
        original = folder / 'original.pdf'
        reading = folder / ('processed.pdf' if old['ocr_pages'] else 'original.pdf')
        if documents.digest(original) != old['sha256'] or documents.digest(reading) != old['reading_sha256']:
            raise ValueError('Legacy original or reading revision does not match')
        documents.validate_tree(old['tree'], old['page_count'])
        with SessionLocal() as db:
            candidates = db.query(Document).join(KnowledgeBase, KnowledgeBase.id == Document.kb_id).filter(
                Document.is_deleted.is_(False), KnowledgeBase.is_deleted.is_(False),
                Document.file_type == 'pdf', Document.filename.ilike(old['title'])).with_for_update(of=Document).all()
            matches = 0
            for doc in candidates:
                if (doc.meta or {}).get('index_type') != 'pageindex':
                    continue
                if hashlib.sha256(minio_client.get_object(doc.minio_key)).hexdigest() != old['sha256']:
                    continue
                source = source_id(doc)
                ident = hashlib.sha256(json.dumps([settings.kb_mcp_organization_id, source]).encode()).hexdigest()
                record = dict(old, id=ident, organization_id=settings.kb_mcp_organization_id,
                    source_id=source, title=doc.filename,
                    source_metadata={'kb_id': str(doc.kb_id), 'kb_document_id': str(doc.id),
                                     'original_key': doc.minio_key, 'legacy_source_id': old['source_id']})
                record['artifacts'] = store.persist_files(folder, ident, record['version'], record['source_metadata'])
                store.put('document_version', ident + ':' + record['version'], record)
                store.put('document', ident, record)
                doc.meta = dict(doc.meta or {}, pageindex_tree=legacy_tree(record),
                    pageindex_status='ok', page_count=record['page_count'],
                    pageindex_evidence={'document_id': ident, 'version': record['version']},
                    parse_engine='carefold-pageindex', ocr_pages=record['ocr_pages'], printed_labels=record['labels'])
                doc.full_text = '\n\n'.join(page['markdown'] for page in record['pages'])
                doc.status = 'indexed'; doc.error_message = None
                adopted.append(str(doc.id)); matches += 1
            if not matches:
                raise ValueError(f'No identical existing PageIndex upload for {old["title"]}; retain legacy service')
            db.commit()
    return adopted


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'adopted_existing_documents': migrate(args.source_dir), 'legacy_data_preserved': True}))
