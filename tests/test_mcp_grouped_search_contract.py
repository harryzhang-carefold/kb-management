"""Actual MCP entry chooses the bounded joint source engine, or its original legs."""
import ast
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Optional

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'backend/mcp_server.py'


@pytest.mark.parametrize('joint_status', ['success', 'unavailable', 'error', 'subset'])
def test_actual_mcp_joint_path_keeps_query_scope_and_fallback(monkeypatch, joint_status):
    node = next(n for n in ast.parse(SOURCE.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == '_auto_search')
    sessions = []
    class Session:
        def __init__(self): self.closed = False; sessions.append(self)
        def close(self): self.closed = True
    ns = {'Optional': Optional, 'SessionLocal': Session, 'logger': SimpleNamespace(error=lambda *a, **k: None)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(SOURCE), 'exec'), ns)
    module = ModuleType('app.services.auto_retrieval')
    seen = []
    def grouped(db, ids, query, top_k):
        seen.append(('joint', tuple(ids), query, top_k))
        if joint_status == 'error': raise TimeoutError('fixture')
        if joint_status == 'unavailable': return None
        return {'hits': [{'document_id': 'source-b', 'score': 1}], 'route': 'multi', 'degraded': [], 'message': None,
                **({'pending_kb_ids': ['source-c']} if joint_status == 'subset' else {})}
    def individual(db, kid, query, top_k, **kwargs):
        seen.append(('individual', kid, query, top_k))
        return {'hits': [{'document_id': kid, 'score': 0.5}], 'route': 'pageindex', 'degraded': [], 'message': None}
    module.try_grouped_pageindex = grouped
    module.run_auto = individual
    monkeypatch.setitem(sys.modules, module.__name__, module)
    ids = ['source-a', 'source-b', 'source-c'] if joint_status == 'subset' else ['source-a', 'source-b']
    hits, meta = ns['_auto_search'](ids, 'unmodified query', 3)
    assert seen[0] == ('joint', tuple(ids), 'unmodified query', 3)
    if joint_status == 'subset':
        assert seen[1:] == [('individual', 'source-c', 'unmodified query', 3)]
        assert [hit['document_id'] for hit in hits] == ['source-b', 'source-c']
        assert len(sessions) == 2
    elif joint_status == 'success':
        assert len(seen) == 1 and len(sessions) == 1
        assert [h['document_id'] for h in hits] == ['source-b']
    else:
        assert sorted(seen[1:]) == [('individual', 'source-a', 'unmodified query', 3),
                                  ('individual', 'source-b', 'unmodified query', 3)]
        assert [h['document_id'] for h in hits] == ['source-a', 'source-b']
        assert len(sessions) == 3
    assert all(s.closed for s in sessions)
    assert meta == {'route': 'multi', 'degraded': [], 'message': None}
