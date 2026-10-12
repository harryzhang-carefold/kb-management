"""Knowledge persistence in the KB PostgreSQL database and MinIO authority."""
import json
import re
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from app.core.database import engine
from app.utils.minio_client import minio_client

_work = ContextVar('knowledge_work', default=None)


@contextmanager
def workspace():
    with tempfile.TemporaryDirectory(prefix='kb-pageindex-') as directory:
        token = _work.set(Path(directory))
        try:
            yield Path(directory)
        finally:
            _work.reset(token)


def data_dir():
    root = _work.get()
    if root is None:
        raise RuntimeError('Knowledge files require a request-local workspace')
    return root


class Database:
    def __init__(self, connection):
        self.connection = connection

    def sql(self, value):
        value = re.sub(r'\bevidence_receipts\b', 'pageindex_evidence_receipt', value)
        value = value.replace('MAX(end,excluded.end)', 'GREATEST(pageindex_evidence_receipt."end",excluded."end")')
        value = value.replace('MAX(expires,excluded.expires)', 'GREATEST(pageindex_evidence_receipt.expires,excluded.expires)')
        value = re.sub(r'\bend\b', '"end"', value)
        # Avoid quoting a previously quoted identifier twice.
        value = value.replace('""end""', '"end"')
        return value.replace('?', '%s')

    def execute(self, sql, parameters=()):
        cursor = self.connection.cursor()
        cursor.execute(self.sql(sql), parameters)
        return cursor

    def executemany(self, sql, parameters):
        cursor = self.connection.cursor()
        cursor.executemany(self.sql(sql), parameters)
        return cursor


@contextmanager
def database():
    connection = engine.raw_connection()
    try:
        yield Database(connection)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def get(kind, key, default=None):
    with database() as db:
        row = db.execute('SELECT value FROM pageindex_record WHERE kind=? AND key=?', (kind, key)).fetchone()
    return json.loads(row[0]) if row else default


def put(kind, key, value):
    with database() as db:
        db.execute('INSERT INTO pageindex_record(kind,key,value) VALUES(?,?,?) ON CONFLICT(kind,key) DO UPDATE SET value=excluded.value, updated_at=now()',
                   (kind, key, json.dumps(value, ensure_ascii=False)))
        if kind in {'index_completion', 'index_rejected'}:
            # Recovery caches are bounded independently of retained source versions.
            db.execute("DELETE FROM pageindex_record WHERE kind=? AND (updated_at < now() - interval '7 days' OR key NOT IN (SELECT key FROM pageindex_record WHERE kind=? ORDER BY updated_at DESC LIMIT 4096))", (kind, kind))
    return value


def documents(identifiers):
    # ACL filtering happens before page text or other source content is loaded.
    if not identifiers:
        return []
    with database() as db:
        rows = db.execute("SELECT value FROM pageindex_record WHERE kind='document' AND key = ANY(?) ORDER BY key", (list(identifiers),))
        return [json.loads(row[0]) for row in rows]


def persist_files(folder, ident, version, metadata):
    prefix = f'pageindex/{ident}/{version}/'
    keys = {}
    for name in ['original.pdf', 'processed.pdf']:
        path = folder / name
        if not path.exists():
            continue
        if name == 'original.pdf' and metadata.get('original_key'):
            # Uploaded originals are immutable; retain that authority reference.
            keys[name] = metadata['original_key']
        else:
            key = prefix + name
            minio_client.put_object(key, path.read_bytes(), 'application/pdf')
            keys[name] = key
    return keys


def materialize(doc):
    root = data_dir() / 'documents' / doc['id'] / doc['version']
    root.mkdir(parents=True, exist_ok=True)
    for name, key in doc['artifacts'].items():
        path = root / name
        if not path.exists():
            path.write_bytes(minio_client.get_object(key))
    return root
