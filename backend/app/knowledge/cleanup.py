"""Remove deleted sources, all retained versions and delivered evidence receipts."""
from app.core.database import SessionLocal
from app.models import Document, Chunk
from app.utils.minio_client import minio_client
from . import store


def document(document_id):
    with SessionLocal() as db:
        doc = db.query(Document).filter_by(id=document_id).with_for_update().first()
        if doc is None or not doc.is_deleted:
            return
        evidence = (doc.meta or {}).get('pageindex_evidence')
        if evidence:
            ident = evidence['document_id']
            minio_client.remove_prefix(f'pageindex/{ident}/')
            with store.database() as records:
                records.execute("DELETE FROM pageindex_record WHERE (kind='document' AND key=?) OR (kind='document_version' AND key LIKE ?)", (ident, ident + ':%'))
                records.execute('DELETE FROM evidence_receipts WHERE document=?', (ident,))
        minio_client.remove_object(doc.minio_key)
        db.query(Chunk).filter_by(document_id=doc.id).delete(synchronize_session=False)
        doc.full_text = None
        doc.meta = {'index_type': (doc.meta or {}).get('index_type', 'embedding')}
        db.commit()
