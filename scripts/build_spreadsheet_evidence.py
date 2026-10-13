#!/usr/bin/env python3
"""Rebuild one explicitly selected existing XLSX source; never writes text indexes."""
import argparse
import sys
from pathlib import Path
from uuid import UUID
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.core.database import SessionLocal, engine
from app.models import Document
from app.knowledge.spreadsheet_service import publish
engine.echo = False

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--document-id', type=UUID, required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        doc = db.query(Document).filter_by(id=args.document_id, is_deleted=False).with_for_update().one()
        record = publish(doc, db)
        doc.meta = dict(doc.meta or {}) | {'spreadsheet_status': 'ready'}
        db.commit()
        print('Existing XLSX source enriched:', record['document_id'], record['version'], len(record['sheets']), 'worksheets')
