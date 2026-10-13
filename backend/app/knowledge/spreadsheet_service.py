"""Native cell evidence on the existing Knowledge Authority and MCP endpoint."""
import hashlib
import base64
import hmac
import json
import time
from typing import Literal
from uuid import UUID

from pydantic import Field
from app.core.database import SessionLocal
from app.models import Document, KnowledgeBase
from app.utils.minio_client import minio_client
from . import store, spreadsheet
from .access import KBKnowledgeService, accessible_kb_ids
from .service import Input, ID
from .reading import read_batch, fully_read


class Discover(Input):
    kb_id: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=50)


class DocumentReference(Input):
    document_id: str = Field(pattern=r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')
    version: ID


class Structure(DocumentReference):
    sheet_id: str | None = Field(default=None, max_length=24)
    table_id: str | None = Field(default=None, max_length=100)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=20)


class Filter(Input):
    column_id: str = Field(min_length=1, max_length=3)
    operator: Literal['eq', 'contains']
    value: str | int | float | bool | None


class Read(DocumentReference):
    sheet_id: str = Field(min_length=1, max_length=24)
    cell_range: str | None = Field(default=None, max_length=40)
    table_id: str | None = Field(default=None, max_length=100)
    filters: list[Filter] = Field(default_factory=list, max_length=10)
    cursor: str | None = Field(default=None, max_length=1024)
    max_chars: int = Field(default=20000, ge=2000, le=24000)


class Citation(Input):
    sheet_id: str = Field(min_length=1, max_length=24)
    cell_range: str = Field(min_length=1, max_length=40)
    evidence_id: ID
    claim: str = Field(min_length=1, max_length=2000)


class Verify(DocumentReference):
    citations: list[Citation] = Field(min_length=1, max_length=3)


OPERATIONS = {'knowledge_discover': Discover, 'spreadsheet_get_structure': Structure,
              'spreadsheet_read_cells': Read, 'spreadsheet_verify_citations': Verify}


def publish(document, db):
    """Enrich an existing source; never replace full_text, its tree or index type."""
    doc = db.query(Document).filter_by(id=document.id).with_for_update().one()
    if doc.is_deleted or doc.file_type != 'xlsx':
        raise ValueError('Native cell evidence requires an active XLSX source')
    record = spreadsheet.parse(minio_client.get_object(doc.minio_key),
                               (doc.meta or {}).get('spreadsheet_tables', []))
    record |= {'document_id': str(doc.id), 'id': str(doc.id), 'source_id': f'kb:{doc.kb_id}:document:{doc.id}',
               'title': doc.filename, 'kb_id': str(doc.kb_id), 'original_key': doc.minio_key}
    # Publication is complete before a new pointer is installed. Existing pointers survive failure.
    store.put('spreadsheet_version', str(doc.id) + ':' + record['version'], record)
    doc.meta = dict(doc.meta or {}) | {'spreadsheet_evidence': {
        'document_id': str(doc.id), 'version': record['version'], 'sha256': record['sha256']}}
    db.flush()
    return record


class SpreadsheetService:
    def __init__(self):
        self.authority = KBKnowledgeService()

    def authorize(self, header, issued_at, signature):
        scope, _ = self.authority.scope(header, issued_at, signature)
        if scope.get('authorization', {}).get('expiresAt', time.time() + 1) <= time.time():
            raise PermissionError('Actor authorization expired')
        return scope, accessible_kb_ids()

    def source(self, ident, version, allowed):
        # IDs are UUIDs of the existing source authority, not PDF-derived IDs.
        try:
            ident = UUID(ident)
        except ValueError:
            raise ValueError('Invalid spreadsheet document ID') from None
        with SessionLocal() as db:
            doc = db.query(Document).filter(Document.id == ident, Document.kb_id.in_(allowed),
                Document.is_deleted.is_(False)).first()
            if doc is None:
                raise PermissionError('Knowledge Source unavailable or not authorized')
            pointer = (doc.meta or {}).get('spreadsheet_evidence')
            if doc.file_type != 'xlsx' or not pointer or pointer['version'] != version:
                raise ValueError('Native cell evidence unavailable or source version changed')
            record = store.get('spreadsheet_version', str(ident) + ':' + version)
            if not record or record['sha256'] != hashlib.sha256(minio_client.get_object(doc.minio_key)).hexdigest():
                raise ValueError('Spreadsheet source changed; rebuild native cell evidence')
            return record

    def metadata(self, record, scope):
        from app.core.security import create_view_token
        from app.core.config import settings
        return {key: record[key] for key in ['document_id', 'version', 'source_id', 'title', 'kb_id']} | {
            'page_kind': 'cells', 'source_type': 'xlsx', 'doc_url':
            f"{settings.kb_public_base_url.rstrip('/')}/kb/{record['kb_id']}/doc/{record['document_id']}?token=" +
            create_view_token(record['document_id'], record['kb_id'], scope['actorId'])}

    def catalog(self, items, total, offset, **extra):
        # Respect the trusted result bound even for large descriptions/catalogs.
        while True:
            result = extra | {'total': total, 'offset': offset,
                'next_offset': offset + len(items) if offset + len(items) < total else None}
            if len(spreadsheet.encode(result).encode('utf-16-le')) // 2 <= 64000:
                return result
            if len(items) <= 1: raise ValueError('Catalog item exceeds the response bound')
            items.pop()

    def call(self, name, values, header, issued_at=None, signature=None):
        scope, allowed = self.authorize(header, issued_at, signature)
        args = OPERATIONS[name].model_validate(values)
        if name == 'knowledge_discover':
            with SessionLocal() as db:
                if not args.kb_id:
                    query = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(allowed), KnowledgeBase.is_deleted.is_(False)).order_by(KnowledgeBase.id)
                    total = query.count()
                    items = [{'kb_id': str(kb.id), 'name': kb.name, 'description': (kb.description or '')[:2000], 'description_truncated': len(kb.description or '') > 2000}
                        for kb in query.offset(args.offset).limit(args.limit)]
                    return self.catalog(items, total, args.offset, collections=items, documents=[])
                try: kb_id = UUID(args.kb_id)
                except ValueError: raise ValueError('Invalid knowledge base ID') from None
                if kb_id not in allowed:
                    raise PermissionError('Knowledge Base unavailable or not authorized')
                query = db.query(Document).filter(Document.kb_id == kb_id, Document.is_deleted.is_(False)).order_by(Document.id)
                total = query.count(); items = []
                for doc in query.offset(args.offset).limit(args.limit):
                    meta = doc.meta or {}; page = meta.get('pageindex_evidence'); cells = meta.get('spreadsheet_evidence')
                    items.append({'document_id': str(doc.id), 'kb_document_id': str(doc.id), 'kb_id': str(doc.kb_id),
                        'title': doc.filename, 'source_id': f'kb:{doc.kb_id}:document:{doc.id}', 'source_type': doc.file_type,
                        'status': doc.status, 'version': (cells or page or {}).get('version'),
                        'evidence': {'parsed_text': page, 'native_cells': cells},
                        'read_methods': (['pageindex_read_pages'] if page else []) + (['spreadsheet_read_cells'] if cells else [])})
                return self.catalog(items, total, args.offset, documents=items)
        # Existing source UUIDs have a different contract from hashed PDF IDs.
        record = self.source(args.document_id, args.version, allowed)
        metadata = self.metadata(record, scope)
        if name == 'spreadsheet_get_structure':
            if args.table_id and not args.sheet_id: raise ValueError('A table selector requires its worksheet ID')
            sheet = next((s for s in record['sheets'] if s['id'] == args.sheet_id), None) if args.sheet_id else None
            if args.sheet_id and sheet is None: raise ValueError('Unknown worksheet ID')
            table = next((t for t in sheet['tables'] if t['id'] == args.table_id), None) if args.table_id else None
            if args.table_id and table is None: raise ValueError('Unknown table ID')
            if table:
                items = [c | ({'header': c['header'][:1000], 'header_truncated': True} if isinstance(c['header'], str) and len(c['header']) > 1000 else {}) for c in table['columns']]; key = 'columns'
                extra = {'sheet_id': sheet['id'], 'sheet': sheet['name'], 'table': {k: v for k, v in table.items() if k != 'columns'}}
            elif sheet:
                # Table descriptors and merge descriptors are independently identifiable records.
                items = [{'kind': 'table', **{k: v for k, v in t.items() if k != 'columns'}, 'column_count': len(t['columns'])} for t in sheet['tables']] + [{'kind': 'merge', **m} for m in sheet['merged_ranges']]
                key = 'regions'; extra = {'sheet_id': sheet['id'], 'sheet': sheet['name']}
            else:
                items = [{k: v for k, v in s.items() if k not in ['cells', 'tables', 'merged_ranges']} | {'table_count': len(s['tables']), 'merged_count': len(s['merged_ranges'])} for s in record['sheets']]
                key = 'sheets'; extra = {}
            result = metadata | extra | {key: items[args.offset:args.offset + args.limit], 'total': len(items), 'next_offset': args.offset + min(args.limit, len(items) - args.offset) if args.offset + args.limit < len(items) else None}
            if len(spreadsheet.encode(result).encode('utf-16-le')) // 2 > 64000: raise ValueError('Structure exceeds response bound; request fewer items')
            return result
        fingerprint = self.authority.fingerprint(scope)
        if name == 'spreadsheet_read_cells':
            identity = hashlib.sha256(spreadsheet.encode([fingerprint, record['version'], args.sheet_id,
                args.cell_range, args.table_id, [f.model_dump() for f in args.filters], args.max_chars]).encode()).hexdigest()
            row_start, inner_cursor = 0, None
            if args.cursor:
                try:
                    body, signature = args.cursor.split('.')
                    expected = hmac.new(self.authority.token.encode(), body.encode(), hashlib.sha256).hexdigest()
                    if not hmac.compare_digest(signature, expected): raise ValueError()
                    binding, row_start, inner_cursor = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
                    if binding != identity or type(row_start) is not int or row_start < 0 or (inner_cursor is not None and not isinstance(inner_cursor, str)): raise ValueError()
                except (ValueError, TypeError, UnicodeError): raise ValueError('Invalid cell cursor for this source, selector, version or Invocation') from None
            sheet, entries = spreadsheet.select(record, args.sheet_id, args.cell_range, args.table_id,
                [condition.model_dump() for condition in args.filters], row_start=row_start, row_limit=256)
            result, spans = read_batch(metadata | {'invocation_id': scope['invocationId']},
                [{'page': sheet['index'], 'passages': entries}], identity=f'{identity}:{row_start}', secret=self.authority.token,
                cursor=inner_cursor, max_chars=args.max_chars - 512)
            reading = result['reading']
            next_inner = reading['next_cursor']; next_row = row_start if next_inner else sheet['next_row']
            complete = next_row is None
            if complete: next_cursor = None
            else:
                body = base64.urlsafe_b64encode(spreadsheet.encode([identity, next_row, next_inner]).encode()).decode().rstrip('=')
                next_cursor = body + '.' + hmac.new(self.authority.token.encode(), body.encode(), hashlib.sha256).hexdigest()
            reading |= {'next_cursor': next_cursor, 'complete': complete, 'window_passages': reading.pop('total_passages')}
            self.source(args.document_id, args.version, self.authorize(header, issued_at, signature)[1])
            with store.database() as db:
                db.execute('DELETE FROM evidence_receipts WHERE expires < ?', (time.time(),))
                db.executemany('INSERT INTO evidence_receipts VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(scope,document,version,page,passage,start) DO UPDATE SET end=MAX(end,excluded.end), expires=MAX(expires,excluded.expires)',
                    [(fingerprint, str(record['document_id']), record['version'], p, ident, start, end, total, time.time()+3600)
                     for p, ident, start, end, total in spans])
            # Sheet ordinals are only internal receipt keys, never physical page locations.
            result['reading'].pop('requested_pages', None)
            result['reading'] |= {'sheet_id': args.sheet_id, 'cell_range': args.cell_range, 'table_id': args.table_id}
            return {key: value for key, value in result.items() if key != 'pages'} | {
                'evidence': [entry for page in result['pages'] for entry in page['passages']]}
        citations = []
        for citation in args.citations:
            sheet, entries = spreadsheet.select(record, citation.sheet_id, citation.cell_range)
            entry = next((item for item in entries if item['id'] == citation.evidence_id), None)
            if entry is None: raise ValueError('Evidence ID does not match selected cell range')
            with store.database() as db:
                rows = list(db.execute('SELECT start,end FROM evidence_receipts WHERE scope=? AND document=? AND version=? AND passage=? AND expires>?',
                    (fingerprint, str(record['document_id']), record['version'], entry['id'], time.time())))
            if not fully_read(rows, len(entry['text'])):
                raise PermissionError('Citation requires complete cells read in this Invocation')
            if len(entry['text']) > 60000: raise ValueError('Select a smaller cell range for claim verification')
            from .models import support_check
            # Text support only: no PDF image, synthetic page or coordinate checks.
            support_record = {'ocr_pages': []}
            try:
                check = support_check(support_record, 0, entry['text'], [], citation.claim)
                status, reason = ('checked' if check['supported'] else 'needs_review'), check['reason']
            except Exception:
                status, reason = 'needs_review', 'Citation verifier unavailable or invalid response'
            citations.append(metadata | {'locator': entry['locator'], 'passage_id': entry['id'],
                'claim': citation.claim, 'quote': entry['text'][:3000], 'quote_truncated': len(entry['text']) > 3000, 'invocation_id': scope['invocationId'],
                'location_status': 'located', 'support_status': status, 'reason': reason})
        self.source(args.document_id, args.version, self.authorize(header, issued_at, signature)[1])
        return {'citations': citations}
