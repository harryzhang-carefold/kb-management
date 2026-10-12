"""Integration contracts against an isolated PostgreSQL database and source store."""
import base64
import json
import os
import sys
import uuid
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.core.database import Base, engine, SessionLocal
from app.core.config import settings
from app.models import User, KnowledgeBase, Document
from app.knowledge import documents, store
from app.knowledge.access import KBKnowledgeService, request_headers
from app.knowledge.ingestion import build_pdf_index, parse_pdf


@pytest.fixture(autouse=True)
def isolated_database():
    assert settings.pg_db == 'kb_migration_test', 'Integration tests require the isolated test database'
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text('DROP TABLE IF EXISTS pageindex_evidence_receipt'))
        connection.execute(text('DROP TABLE IF EXISTS pageindex_record'))
        migration = Path(__file__).resolve().parents[1] / 'infra/migrations/20261012_knowledge_evidence.sql'
        for statement in migration.read_text().split(';'):
            if statement.strip() and statement.strip() not in {'BEGIN', 'COMMIT'}:
                connection.execute(text(statement))
    settings.kb_mcp_api_key = 'test-service-' + 'k' * 40
    settings.kb_mcp_actor_bindings = {'test-actor': 'owner', 'other-actor': 'outsider'}
    settings.kb_mcp_organization_id = 'test-org'
    settings.kb_mcp_agent_definition_ids = ['test-agent']
    settings.carefold_scope_signing_secret = ''


@pytest.fixture
def source(monkeypatch):
    objects = {}
    from app.utils.minio_client import minio_client
    monkeypatch.setattr(minio_client, 'get_object', lambda key: objects[key])
    monkeypatch.setattr(minio_client, 'put_object', lambda key, data, content_type='': objects.__setitem__(key, data))
    monkeypatch.setattr(minio_client, 'remove_object', lambda key: objects.pop(key, None))
    monkeypatch.setattr(minio_client, 'remove_prefix', lambda prefix: [objects.pop(key) for key in list(objects) if key.startswith(prefix)])
    with SessionLocal() as db:
        owner = User(username='owner', email='owner@test.invalid', password_hash='fixture', role='user')
        outsider = User(username='outsider', email='outsider@test.invalid', password_hash='fixture', role='user')
        db.add_all([owner, outsider]); db.flush()
        kb = KnowledgeBase(owner_id=owner.id, name='Synthetic knowledge')
        db.add(kb); db.flush()
        document = Document(kb_id=kb.id, uploaded_by=owner.id, filename='fixture.pdf',
                            file_type='pdf', minio_key='fixture/original.pdf', status='parsed',
                            meta={'index_type': 'pageindex'})
        db.add(document); db.commit()
        ident = document.id
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 80), 'The synthetic follow-up interval is seven days.\nThe sample identifier is KBFOLD-7421.', fontsize=12)
        page = pdf.new_page()
        page.insert_text((50, 80), 'Second page has a distinct source condition.', fontsize=12)
        pdf.set_toc([[1, 'Follow-up', 1], [1, 'Conditions', 2]])
        objects['fixture/original.pdf'] = pdf.tobytes()
    with SessionLocal() as db:
        doc = db.get(Document, ident)
        build_pdf_index(doc, db)
        doc.status = 'indexed'; db.commit()
        record_id = doc.meta['pageindex_evidence']['document_id']
    record = store.get('document', record_id)
    return record, ident, objects


def headers(actor='test-actor', invocation='invocation-1'):
    scope = {'invocationId': invocation, 'organizationId': 'test-org',
             'connectorInstallationId': 'test-connector', 'actorId': actor,
             'conversationType': 'direct', 'conversationId': 'test-conversation',
             'externalMessageId': 'test-message', 'agentDefinitionId': 'test-agent',
             'correlationId': 'test-correlation'}
    encoded = base64.urlsafe_b64encode(json.dumps(scope).encode()).decode().rstrip('=')
    return {'authorization': 'Bearer ' + settings.kb_mcp_api_key,
            'x-carefold-interaction-scope': encoded}


def call(name, args, *, actor='test-actor', invocation='invocation-1'):
    values = headers(actor, invocation)
    token = request_headers.set(values)
    try:
        return KBKnowledgeService().call(name, args, values['x-carefold-interaction-scope'])
    finally:
        request_headers.reset(token)


def arguments(record):
    return {'document_id': record['id'], 'version': record['version']}


def test_pdf_does_not_depend_on_mineru(source, monkeypatch):
    record, _, objects = source
    monkeypatch.setattr('app.parsing.router.parse_with_mineru', lambda *a: pytest.fail('PDF used MinerU'))
    from app.parsing import parse_document
    body, meta = parse_document(objects['fixture/original.pdf'], 'fixture.pdf', 'pdf')
    assert 'seven days' in body and meta['page_count'] == 2
    assert record['engine'] != 'heading-degraded'


def test_import_is_idempotent_and_retains_source_version(source):
    record, ident, objects = source
    with SessionLocal() as db:
        build_pdf_index(db.get(Document, ident), db)
    assert store.get('document', record['id'])['version'] == record['version']
    assert store.get('document_version', record['id'] + ':' + record['version'])
    assert list(objects) == ['fixture/original.pdf']  # No duplicate original or permanent local copies.


def test_actual_acl_precedes_source_materialization(source, monkeypatch):
    record, _, _ = source
    monkeypatch.setattr(store, 'materialize', lambda *a: pytest.fail('Denied source was opened'))
    assert call('pageindex_list_documents', {}, actor='other-actor')['documents'] == []
    with pytest.raises(PermissionError):
        call('pageindex_read_pages', arguments(record) | {'pages': [1]}, actor='other-actor')
    with pytest.raises(PermissionError):
        call('pageindex_list_documents', {}, actor='unbound-actor')


def test_read_receipt_exact_location_and_invocation_binding(source, monkeypatch):
    record, _, _ = source
    read = call('pageindex_read_pages', arguments(record) | {'pages': [1]})
    passage = read['pages'][0]['passages'][0]
    citations = arguments(record) | {'citations': [{'page': 1, 'passage_id': passage['id'], 'claim': 'The follow-up interval is seven days.'}]}
    monkeypatch.setattr('app.knowledge.service.support_check', lambda *a: {'supported': True, 'reason': 'Exact support'})
    checked = call('pageindex_verify_citations', citations)['citations'][0]
    assert checked['location_status'] == 'located' and checked['support_status'] == 'checked'
    assert checked['boxes'] and checked['quote'] == passage['text']
    with pytest.raises(PermissionError, match='this Invocation'):
        call('pageindex_verify_citations', citations, invocation='different-invocation')
    monkeypatch.setattr('app.knowledge.service.support_check', lambda *a: {'supported': False, 'reason': 'Broader claim'})
    assert call('pageindex_verify_citations', citations)['citations'][0]['support_status'] == 'needs_review'


def test_partial_read_cannot_be_cited_and_cursor_is_bound(source):
    record, _, _ = source
    record['pages'][0]['markdown'] = 'Unicode evidence ' + ('汉字😀\\\"' * 3000) + ' unique ending.'
    store.put('document', record['id'], record)
    args = arguments(record) | {'pages': [1], 'max_chars': 4000}
    first = call('pageindex_read_pages', args)
    assert not first['reading']['complete']
    passage = first['pages'][0]['passages'][0]
    with pytest.raises(PermissionError):
        call('pageindex_verify_citations', arguments(record) | {'citations': [{'page': 1, 'passage_id': passage['id'], 'claim': 'Unicode evidence'}]})
    cursor = first['reading']['next_cursor']
    from app.knowledge.reading import ReadingCursorError, serialize
    with pytest.raises(ReadingCursorError):
        call('pageindex_read_pages', args | {'cursor': cursor}, invocation='another-invocation')
    fragments = [passage['text']]
    while cursor:
        page = call('pageindex_read_pages', args | {'cursor': cursor})
        assert len(serialize(page).encode('utf-16-le')) // 2 <= 4000
        fragments.extend(p['text'] for entry in page['pages'] for p in entry['passages'])
        cursor = page['reading']['next_cursor']
    assert ''.join(fragments) == record['pages'][0]['markdown']


def test_deletion_reclaims_source_and_evidence(source):
    record, ident, objects = source
    with SessionLocal() as db:
        document = db.get(Document, ident); document.is_deleted = True; db.commit()
    from app.knowledge.cleanup import document as cleanup
    cleanup(str(ident))
    assert not objects and store.get('document', record['id']) is None
    assert store.get('document_version', record['id'] + ':' + record['version']) is None
    with SessionLocal() as db:
        assert db.get(Document, ident).full_text is None


def test_mcp_http_preserves_tools_and_authenticated_evidence(source):
    from starlette.testclient import TestClient
    import mcp_server
    record, _, _ = source
    def message(client, method, params=None):
        response = client.post('/mcp', headers=headers() | {
            'accept': 'application/json, text/event-stream',
            'mcp-protocol-version': '2025-11-25'}, json={
            'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}})
        assert response.status_code == 200, response.text
        if response.headers['content-type'].startswith('application/json'):
            return response.json()
        return json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith('data: ')))
    with TestClient(mcp_server.streamable_app, base_url='http://127.0.0.1:9100') as client:
        init = message(client, 'initialize', {'protocolVersion': '2025-11-25',
            'capabilities': {}, 'clientInfo': {'name': 'kb-contract', 'version': '1'}})
        assert 'result' in init
        listed = message(client, 'tools/list')['result']['tools']
        names = {tool['name'] for tool in listed}
        assert {'list_knowledge_bases', 'search_knowledge', 'rag_query',
                'pageindex_list_documents', 'pageindex_get_structure',
                'pageindex_read_pages', 'pageindex_verify_citations'} <= names
        result = message(client, 'tools/call', {'name': 'pageindex_read_pages',
            'arguments': arguments(record) | {'pages': [1]}})['result']
        assert not result.get('isError'), result
        assert json.loads(result['content'][0]['text'])['reading']['complete']
        assert client.post('/mcp', json={}).status_code == 401
        assert client.post('/mcp', headers={'authorization': 'Bearer a.b.c'}, json={}).status_code == 401


def test_legacy_tools_keep_actual_kb_permissions(source):
    import mcp_server
    _, ident, _ = source
    token = request_headers.set(headers('other-actor'))
    try:
        assert json.loads(mcp_server.list_knowledge_bases())['items'] == []
        assert 'error' in json.loads(mcp_server.get_document_chunks(str(ident)))
    finally:
        request_headers.reset(token)


def test_legacy_adoption_preserves_existing_original_and_documents(source, tmp_path):
    import importlib.util
    record, ident, objects = source
    directory = tmp_path / 'legacy'; directory.mkdir()
    folder = directory / 'documents' / record['id'] / record['version']; folder.mkdir(parents=True)
    raw = objects['fixture/original.pdf']; (folder / 'original.pdf').write_bytes(raw)
    import sqlite3
    with sqlite3.connect(directory / 'knowledge.sqlite3') as connection:
        connection.execute('CREATE TABLE records(kind TEXT, key TEXT, value TEXT)')
        connection.execute('INSERT INTO records VALUES(?,?,?)', ('document', record['id'], json.dumps(record)))
    path = Path(__file__).resolve().parents[1] / 'scripts/migrate_legacy_sources.py'
    spec = importlib.util.spec_from_file_location('legacy_adoption', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.migrate(directory) == [str(ident)]
    assert objects == {'fixture/original.pdf': raw}
    assert (folder / 'original.pdf').read_bytes() == raw
    with SessionLocal() as db:
        assert db.query(Document).count() == 1
        assert db.get(Document, ident).status == 'indexed'


def test_source_change_and_revoked_access_invalidate_evidence(source):
    record, ident, objects = source
    call('pageindex_read_pages', arguments(record) | {'pages': [1]})
    objects['fixture/original.pdf'] = b'changed source'
    with pytest.raises(ValueError, match='Source revision mismatch'):
        call('pageindex_read_pages', arguments(record) | {'pages': [1]})
    with SessionLocal() as db:
        document = db.get(Document, ident); document.is_deleted = True; db.commit()
    with pytest.raises(PermissionError):
        call('pageindex_get_structure', arguments(record))


def test_scanned_pdf_uses_local_ocr(monkeypatch):
    tessdata = os.environ.get('KB_TEST_TESSDATA', '/usr/share/tesseract-ocr/5/tessdata')
    if not (Path(tessdata) / 'eng.traineddata').exists():
        pytest.skip('Set KB_TEST_TESSDATA to the local OCR language directory')
    monkeypatch.setenv('PAGEINDEX_TESSDATA', tessdata)
    monkeypatch.setenv('PAGEINDEX_OCR_LANGUAGES', 'eng')
    with pymupdf.open() as digital:
        page = digital.new_page()
        page.insert_text((45, 100), 'Synthetic follow up interval is seven days.', fontsize=20)
        pixels = page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes('png')
    with pymupdf.open() as scanned:
        page = scanned.new_page(); page.insert_image(page.rect, stream=pixels)
        body, metadata = parse_pdf(scanned.tobytes(), 'scan.pdf')
    assert 'seven days' in body and metadata['ocr_pages'] == [1]
