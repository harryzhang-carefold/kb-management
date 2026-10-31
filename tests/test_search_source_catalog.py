"""Real MCP helper contracts, isolated from network/storage and source values."""
import ast
import json
import uuid
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def functions():
    source = ROOT / 'backend/mcp_server.py'
    tree = ast.parse(source.read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and
             n.name in ('_attach_citations', '_docs_mapping', '_order_items_for_truncation')]
    ns = {'Optional': Optional, 'uuid': uuid,
          'settings': SimpleNamespace(kb_public_base_url='https://source.example'),
          'create_view_token': lambda *a, **kw: 'fixture-only-token'}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(source), 'exec'), ns)
    return ns


def test_search_reuses_authority_owned_source_metadata_without_a_second_discovery():
    ns = functions()
    doc_id = '10000000-0000-0000-0000-000000000001'
    kb_id = '20000000-0000-0000-0000-000000000001'
    canonical = {'document_id': doc_id, 'kb_document_id': doc_id, 'kb_id': kb_id,
                 'source_id': f'kb:{kb_id}:document:{doc_id}', 'title': 'Fixture workbook',
                 'source_type': 'xlsx', 'status': 'ready', 'version': 'cell-v2',
                 'evidence': {'parsed_text': {'document_id': 'a'*64, 'version': 'text-v1'},
                              'native_cells': {'document_id': doc_id, 'version': 'cell-v2'}},
                 'read_methods': ['pageindex_read_pages', 'spreadsheet_read_cells']}
    looked_up = []
    def lookup(ids):
        looked_up.append(ids)
        return {doc_id: {'kb_id': kb_id, 'index_type': 'pageindex', 'file_type': 'xlsx',
                         'source_reference': canonical}}
    ns['_docs_mapping'] = lookup
    hits = [{'document_id': doc_id, 'metadata': {'node_id': 'node-1'}, 'content': 'snippet one'},
            {'document_id': doc_id, 'metadata': {'node_id': 'node-2'}, 'content': 'snippet two'}]
    catalog = []
    result = ns['_attach_citations'](None, hits, source_documents=catalog)
    assert len(looked_up) == 1
    assert [{k: v for k, v in entry.items() if k != 'doc_url'} for entry in catalog] == [canonical]
    assert catalog[0]['doc_url'].startswith('https://source.example/kb/')
    assert [x['content'] for x in result] == ['snippet one', 'snippet two']
    assert all('checked' not in x for x in result)
    assert catalog[0]['evidence']['native_cells']['document_id'] == doc_id
    assert catalog[0]['evidence']['parsed_text']['document_id'] != doc_id


def test_unresolved_search_ids_do_not_become_native_source_references():
    ns = functions()
    ns['_docs_mapping'] = lambda ids: {}
    catalog = []
    ns['_attach_citations'](None, [{'document_id': '10000000-0000-0000-0000-000000000002',
                                  'content': 'not a verified source version'}], source_documents=catalog)
    assert catalog == []


def test_search_snippet_metadata_cannot_override_authority_source_identity():
    ns = functions()
    doc_id = '10000000-0000-0000-0000-000000000001'
    canonical = {'document_id': doc_id, 'source_id': 'authorized-source', 'version': 'current',
                 'evidence': {}, 'read_methods': []}
    ns['_docs_mapping'] = lambda ids: {doc_id: {'kb_id': 'authorized-kb', 'index_type': 'embedding',
                                              'source_reference': canonical}}
    catalog = []
    ns['_attach_citations'](None, [{'document_id': doc_id,
        'metadata': {'source_id': 'other-source', 'version': 'invented', 'evidence': {'native_cells': {}}}}],
        source_documents=catalog)
    assert [{k: v for k, v in entry.items() if k != 'doc_url'} for entry in catalog] == [canonical]
    assert catalog[0]['doc_url'].startswith('https://source.example/kb/')


def test_document_lookup_rechecks_access_after_search_and_excludes_deleted_documents():
    ns = functions()
    filters = []
    class Column:
        def __init__(self, name): self.name = name
        def in_(self, value): return self.name, 'in', value
        def is_(self, value): return self.name, 'is', value
    model = SimpleNamespace(id=Column('id'), kb_id=Column('kb_id'), is_deleted=Column('deleted'))
    class Session:
        closed = False
        def query(self, *args): return self
        def filter(self, *args): filters.extend(args); return self
        def all(self): return []
        def close(self): self.closed = True
    session = Session()
    ns.update(Document=model, SessionLocal=lambda: session, accessible_kb_ids=lambda: ['authorized-kb'])
    assert ns['_docs_mapping'](['10000000-0000-0000-0000-000000000001']) == {}
    assert ('kb_id', 'in', ['authorized-kb']) in filters
    assert ('deleted', 'is', False) in filters
    assert session.closed


def test_search_returns_catalog_separately_from_snippets_and_keeps_original_modes():
    tree = ast.parse((ROOT / 'backend/mcp_server.py').read_text())
    search = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'search_knowledge')
    keys = [k.value for n in ast.walk(search) if isinstance(n, ast.Dict)
            for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    assert 'documents' in keys
    assert all(k in keys for k in ['query', 'mode', 'total', 'items'])


def test_shared_document_reference_preserves_both_published_identities_without_values():
    from app.knowledge.source_catalog import document_reference
    original = uuid.UUID('10000000-0000-0000-0000-000000000001')
    kb = uuid.UUID('20000000-0000-0000-0000-000000000001')
    doc = SimpleNamespace(id=original, kb_id=kb, filename='Fixture.xlsx', file_type='xlsx', status='ready',
        meta={'pageindex_evidence': {'document_id': 'a'*64, 'version': 'b'*64},
              'spreadsheet_evidence': {'document_id': str(original), 'version': 'c'*64},
              'internal_debug': 'DO_NOT_COPY'})
    reference = document_reference(doc)
    assert reference['source_id'] == f'kb:{kb}:document:{original}'
    assert reference['evidence']['parsed_text']['document_id'] == 'a'*64
    assert reference['evidence']['native_cells']['document_id'] == str(original)
    assert reference['version'] == 'c'*64
    assert 'DO_NOT_COPY' not in json.dumps(reference)
    doc.meta = {}
    assert document_reference(doc)['read_methods'] == []
    assert document_reference(doc)['version'] is None


def test_optional_catalog_respects_the_existing_bound_without_changing_search_hits():
    from app.knowledge.source_catalog import encode_search_payload
    payload = {'items': [{'content': 'requested snippet'}], 'total': 1,
               'documents': [{'title': 'x'*300}, {'title': 'y'*300}]}
    result = json.loads(encode_search_payload(payload, max_chars=500))
    assert result['items'] == payload['items']
    assert result['total'] == 1
    assert result['source_catalog_complete'] is False
    assert len(result['documents']) < 2
    assert len(payload['documents']) == 2
