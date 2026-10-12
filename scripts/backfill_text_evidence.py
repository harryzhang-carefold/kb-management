#!/usr/bin/env python3
"""Publish evidence for existing text indexes, preserving their files and trees."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.core.database import SessionLocal, engine
from app.models import Document, KnowledgeBase
from app.knowledge.text_evidence import publish
engine.echo = False


def backfill():
    updated = []
    with SessionLocal() as db:
        candidates = db.query(Document).join(KnowledgeBase, KnowledgeBase.id == Document.kb_id).filter(
            Document.is_deleted.is_(False), KnowledgeBase.is_deleted.is_(False),
            Document.status == 'indexed', Document.file_type != 'pdf').with_for_update(of=Document).all()
        for doc in candidates:
            meta = doc.meta or {}
            tree = meta.get('pageindex_tree')
            if meta.get('index_type') == 'pageindex' and not meta.get('pageindex_evidence') and tree and doc.full_text:
                publish(doc, tree); updated.append(str(doc.id))
        db.commit()
    return updated


if __name__ == '__main__':
    print('Existing text indexes adopted:', len(backfill()))
