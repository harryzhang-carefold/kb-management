"""Joint search reuses the current tree engine over the exact authorized KB set."""
import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Optional
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services import pageindex_engine as engine


def grouped_function(compositions):
    path = ROOT / 'backend/app/services/auto_retrieval.py'
    node = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'try_grouped_pageindex')
    seen = []
    def composition(db, kid):
        seen.append(kid)
        return compositions[kid]
    ns = {'Optional': Optional, 'kb_index_composition': composition, 'LEG_PAGEINDEX': 'pageindex'}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(path), 'exec'), ns)
    return ns['try_grouped_pageindex'], seen


def test_small_homogeneous_source_set_uses_one_engine_request_without_losing_scope(monkeypatch):
    fn, looked_up = grouped_function({k: {'embedding_docs': 0, 'pageindex_docs': 2} for k in ['kb-a', 'kb-b']})
    requests = []
    session = object()
    def retrieve(ids, query, limit, **kwargs):
        requests.append((ids, query, limit, kwargs))
        return [{'document_id': 'doc-b', 'metadata': {'node_id': 'n3'}}], 42, {}
    monkeypatch.setattr(engine, 'retrieve', retrieve)
    result = fn(session, ['kb-a', 'kb-b'], 'original query', 5)
    assert looked_up == ['kb-a', 'kb-b']
    assert requests == [(['kb-a', 'kb-b'], 'original query', 5, {'db': session, 'prefer_lexical': True})]
    assert result == {'hits': [{'document_id': 'doc-b', 'metadata': {'node_id': 'n3', 'leg': 'pageindex'}}],
                      'took_ms': 42, 'route': 'multi', 'degraded': [], 'message': None}


@pytest.mark.parametrize('composition', [
    {'embedding_docs': 1, 'pageindex_docs': 2},
    {'embedding_docs': 0, 'pageindex_docs': engine.MAX_OUTLINE_DOCS},
    {'embedding_docs': 0, 'pageindex_docs': 0},
])
def test_mixed_large_or_empty_sources_keep_the_original_per_source_paths(monkeypatch, composition):
    fn, _ = grouped_function({'kb-a': composition, 'kb-b': composition})
    monkeypatch.setattr(engine, 'retrieve', lambda *a, **kw: pytest.fail('Must preserve original legs'))
    assert fn(object(), ['kb-a', 'kb-b'], 'unchanged', 5) is None


@pytest.mark.parametrize('extra', [{'error': 'unavailable'}, {'grouping_unavailable': 'source_inventory_exceeds_joint_bound'}])
def test_joint_failure_or_inventory_growth_does_not_turn_into_false_empty(monkeypatch, extra):
    fn, _ = grouped_function({k: {'embedding_docs': 0, 'pageindex_docs': 1} for k in ['kb-a', 'kb-b']})
    monkeypatch.setattr(engine, 'retrieve', lambda *a, **kw: ([], 2, extra))
    assert fn(object(), ['kb-a', 'kb-b'], 'unchanged', 5) is None


def test_multi_source_engine_binds_only_the_supplied_ids(monkeypatch):
    constraints = []
    class Query:
        def filter(self, *args): constraints.extend(args); return self
        def order_by(self, *args): return self
        def all(self): return []
    session = SimpleNamespace(query=lambda *args: Query())
    monkeypatch.setattr(engine.llm_client, 'chat', lambda *a, **kw: pytest.fail('No documents'))
    hits, _, extra = engine.retrieve(['authorized-a', 'authorized-b'], 'original', db=session, prefer_lexical=True)
    assert hits == [] and extra['empty_reason'] == 'no_pageindex_docs'
    assert constraints[0].right.value == ['authorized-a', 'authorized-b']
    assert 'is_deleted IS false' in str(constraints[1])


def test_multi_source_inventory_change_never_silently_truncates_another_kb(monkeypatch):
    docs = [SimpleNamespace(id=f'doc-{i}', kb_id='kb-a' if i % 2 else 'kb-b', file_type='txt',
            full_text='alpha beta gamma', meta={'index_type': 'pageindex', engine.TREE_KEY: {
                'status': 'ok', 'full_text_chars': 16, 'root': {'node_id': 'n1', 'start': 0, 'end': 16, 'children': []}}})
            for i in range(engine.MAX_OUTLINE_DOCS + 1)]
    class Query:
        def filter(self, *_args): return self
        def order_by(self, *_args): return self
        def all(self): return docs
    monkeypatch.setattr(engine.llm_client, 'chat', lambda *a, **kw: pytest.fail('No partial joint request'))
    hits, _, extra = engine.retrieve(['kb-a', 'kb-b'], 'alpha beta gamma', db=SimpleNamespace(query=lambda *a: Query()), prefer_lexical=True)
    assert hits == []
    assert extra['grouping_unavailable'] == 'source_inventory_exceeds_joint_bound'
    assert extra['docs_considered'] == engine.MAX_OUTLINE_DOCS + 1
