"""Exercise the actual MCP fanout functions with isolated engine/session fixtures.

Only source retrieval I/O changes concurrency: no model planner, task routing,
query rewriting, new authorization or fallback is introduced here.
"""
import ast
from contextvars import ContextVar
from pathlib import Path
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
from typing import Optional

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'backend/mcp_server.py'


@pytest.fixture
def searches(monkeypatch):
    tree = ast.parse(SOURCE.read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('_auto_search', '_pageindex_search')]
    namespace = {'Optional': Optional, 'logger': SimpleNamespace(error=lambda *args: None)}
    modules = {}
    for name in ('app', 'app.services', 'app.services.auto_retrieval', 'app.services.pageindex_engine'):
        module = ModuleType(name); module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module); modules[name] = module
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(SOURCE), 'exec'), namespace)
    sessions = []
    class Session:
        def __init__(self):
            self.owner = threading.get_ident(); self.closed = False; sessions.append(self)
        def close(self):
            assert self.owner == threading.get_ident()
            self.closed = True
    namespace['SessionLocal'] = Session
    return namespace, modules, sessions


@pytest.mark.parametrize('kind', ['auto', 'pageindex'])
def test_authorized_sources_overlap_with_thread_confined_sessions_and_copied_context(searches, kind):
    ns, modules, sessions = searches
    marker = ContextVar('caller_context', default='MISSING')
    token = marker.set('authorized-actor-one')
    barrier = threading.Barrier(3)
    lock = threading.Lock(); active = 0; peak = 0
    seen = []
    def retrieve(kid, query, top_k, db):
        nonlocal active, peak
        assert db.owner == threading.get_ident()
        with lock:
            active += 1; peak = max(peak, active)
            seen.append((kid, query, top_k, marker.get(), id(db)))
        try:
            barrier.wait(timeout=3)
            time.sleep((2-int(kid[-1])) * 0.01)
            hits = [{'chunk_id': kid, 'score': 1.0}]
            return hits
        finally:
            with lock: active -= 1
    modules['app.services.auto_retrieval'].run_auto = lambda db, kid, query, top_k, **kw: {
        'hits': retrieve(kid, query, top_k, db), 'route': 'pageindex', 'message': kid, 'degraded': []}
    modules['app.services.pageindex_engine'].retrieve = lambda kid, query, top_k, *, db: (
        retrieve(kid, query, top_k, db), 1, {'message': kid})
    try: result = ns[f'_{kind}_search'](['scope-0', 'scope-1', 'scope-2'], 'unchanged-query', 3)
    finally: marker.reset(token)
    assert peak == 3
    assert [hit['chunk_id'] for hit in result[0]] == ['scope-0', 'scope-1', 'scope-2']
    assert len({x[4] for x in seen}) == 3
    assert all(x[1:4] == ('unchanged-query', 3, 'authorized-actor-one') for x in seen)
    assert all(s.closed for s in sessions)
    if kind == 'auto': assert result[1] == {'route': 'multi', 'message': 'scope-0 scope-1 scope-2', 'degraded': []}
    else: assert result[1:] == (['scope-0', 'scope-1', 'scope-2'], [])


def test_auto_keeps_failures_isolated_sorting_and_top_k(searches):
    ns, modules, sessions = searches
    def retrieve(db, kid, query, top_k, **kwargs):
        if kid == 'bad': raise TimeoutError('fixture failure')
        return {'hits': [{'chunk_id': kid, 'score': {'low': 0.2, 'high': 0.8}[kid]}],
                'route': 'hybrid', 'degraded': ['one-leg'], 'message': 'degraded fixture'}
    modules['app.services.auto_retrieval'].run_auto = retrieve
    hits, meta = ns['_auto_search'](['low', 'bad', 'high'], 'unchanged', 1)
    assert [h['chunk_id'] for h in hits] == ['high']
    assert meta['degraded'] == ['one-leg']
    assert meta['message'] == 'degraded fixture'
    assert all(s.closed for s in sessions)


def test_pageindex_no_hit_or_failure_does_not_add_a_different_retrieval_route(searches):
    ns, modules, sessions = searches
    calls = []
    def retrieve(kid, query, top_k, *, db):
        calls.append(kid)
        if kid == 'fail': raise TimeoutError('failed source')
        return [], 1, {'message': 'No node selected'}
    modules['app.services.pageindex_engine'].retrieve = retrieve
    modules['app.services.auto_retrieval'].run_auto = lambda *a, **k: pytest.fail('Implicit auto fallback')
    hits, messages, errors = ns['_pageindex_search'](['empty', 'fail'], 'query', 5)
    assert hits == [] and messages == ['No node selected'] and len(errors) == 1
    assert set(calls) == {'empty', 'fail'}
    assert all(s.closed for s in sessions)


def test_single_source_preserves_engine_result_and_does_not_enumerate_more_sources(searches):
    ns, modules, sessions = searches
    calls = []
    def retrieve(db, kid, query, top_k, **kwargs):
        calls.append(kid)
        return {'hits': [{'chunk_id': 'one', 'score': 1}], 'route': 'pageindex', 'degraded': [], 'message': None}
    modules['app.services.auto_retrieval'].run_auto = retrieve
    hits, meta = ns['_auto_search'](['only-authorized'], 'q', 2)
    assert calls == ['only-authorized']
    assert hits == [{'chunk_id': 'one', 'score': 1}]
    assert meta == {'route': 'pageindex', 'degraded': [], 'message': None}
    assert len(sessions) == 1 and sessions[0].closed


def test_fanout_has_a_fixed_resource_bound_and_no_cross_request_state(searches):
    ns, modules, sessions = searches
    marker = ContextVar('actor', default='MISSING')
    lock = threading.Lock(); active = 0; peak = 0; seen = []
    def retrieve(db, kid, query, top_k, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1; peak = max(peak, active); seen.append(marker.get())
        try:
            time.sleep(0.01)
            return {'hits': [], 'route': 'none'}
        finally:
            with lock: active -= 1
    modules['app.services.auto_retrieval'].run_auto = retrieve
    for actor in ('actor-A', 'actor-B'):
        token = marker.set(actor)
        try: ns['_auto_search']([f'kb-{i}' for i in range(8)], 'q', 5)
        finally: marker.reset(token)
    assert 1 < peak <= 3
    assert seen[:8] == ['actor-A'] * 8 and seen[8:] == ['actor-B'] * 8
    assert len(sessions) == 16 and all(s.closed for s in sessions)
