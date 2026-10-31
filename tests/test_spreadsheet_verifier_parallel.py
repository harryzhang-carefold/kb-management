"""Isolated tests of the real SpreadsheetService.call verification branch.

No network, database or uploaded source mutation. The authority/store adapters
are fixtures; the implementation under test is compiled verbatim from its file
so these tests can run without the production PostgreSQL/MinIO deployment.
"""
import ast
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import sys
import threading
import time
from types import ModuleType, SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'backend/app/knowledge/spreadsheet_service.py'


@pytest.fixture
def service_factory(monkeypatch):
    tree = ast.parse(SOURCE.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'SpreadsheetService')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'call')
    module = ast.Module(body=[method], type_ignores=[])
    namespace = {'__name__': '_t09_verifier_fixture.service', '__package__': '_t09_verifier_fixture',
                 'time': time}
    parent = ModuleType('_t09_verifier_fixture'); parent.__path__ = []
    models = ModuleType('_t09_verifier_fixture.models')
    models.support_check = lambda *args: {'supported': True, 'reason': 'fixture support'}
    monkeypatch.setitem(sys.modules, parent.__name__, parent)
    monkeypatch.setitem(sys.modules, models.__name__, models)
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), 'exec'), namespace)

    def create(count=3, incomplete=None, revoke=False):
        entries = {f'e{i}': {'id': f'e{i}', 'text': f'fixture exact cells {i}',
                   'locator': {'kind': 'cells', 'range': f'A{i+1}:C{i+1}'}} for i in range(count)}
        source_calls = []
        @contextmanager
        def database():
            yield SimpleNamespace(execute=lambda sql, args: [] if args[3] == incomplete else [(0, len(entries[args[3]]['text']))])
        def source(*args):
            source_calls.append(args)
            if revoke and len(source_calls) > 1:
                raise PermissionError('Source or access changed after verification')
            return {'document_id': 'doc', 'version': 'v1'}
        reader = SimpleNamespace(
            authorize=lambda *args: ({'invocationId': 'current'}, ['allowed']),
            source=source, metadata=lambda *args: {'document_id': 'doc', 'version': 'v1', 'source_id': 'source'},
            authority=SimpleNamespace(fingerprint=lambda scope: 'scope-fingerprint'),
        )
        namespace['OPERATIONS'] = {'spreadsheet_verify_citations': SimpleNamespace(model_validate=lambda values: values)}
        namespace['store'] = SimpleNamespace(database=database)
        namespace['spreadsheet'] = SimpleNamespace(select=lambda record, sheet, location: ({}, list(entries.values())))
        namespace['fully_read'] = lambda parts, total: parts == [(0, total)]
        args = SimpleNamespace(document_id='doc', version='v1', citations=[SimpleNamespace(
            sheet_id='sheet', cell_range=f'A{i+1}:C{i+1}', evidence_id=f'e{i}', claim=f'claim-{i}') for i in range(count)])
        return lambda: namespace['call'](reader, 'spreadsheet_verify_citations', args, 'fixture-header'), models, source_calls
    return create


def test_checks_overlap_but_preserve_exact_order_and_request_context(service_factory):
    invoke, models, source_calls = service_factory()
    marker = ContextVar('request_identity', default='MISSING')
    token = marker.set('current-authorized-request')
    barrier = threading.Barrier(3)
    lock = threading.Lock()
    active = 0
    peak = 0
    observed = []
    def check(doc, page, quote, boxes, claim):
        nonlocal active, peak
        with lock:
            active += 1; peak = max(peak, active)
            observed.append((claim, quote, marker.get()))
        try:
            barrier.wait(timeout=3)
            # Results deliberately finish in reverse order.
            time.sleep((2-int(claim.rsplit('-', 1)[1])) * 0.01)
            return {'supported': True, 'reason': claim}
        finally:
            with lock: active -= 1
    models.support_check = check
    try: result = invoke()
    finally: marker.reset(token)
    assert peak == 3
    assert [c['claim'] for c in result['citations']] == ['claim-0', 'claim-1', 'claim-2']
    assert all(c['support_status'] == 'checked' for c in result['citations'])
    assert all(identity == 'current-authorized-request' for _, _, identity in observed)
    assert all(quote.endswith(claim.rsplit('-', 1)[1]) for claim, quote, _ in observed)
    assert len(source_calls) == 2  # before work and after all remote checks


def test_unread_later_claim_prevents_all_model_checks(service_factory):
    invoke, models, _ = service_factory(incomplete='e2')
    calls = []
    models.support_check = lambda *args: calls.append(args) or {'supported': True, 'reason': 'fixture'}
    with pytest.raises(PermissionError): invoke()
    assert calls == []


def test_independent_failure_never_promotes_other_claims_or_reorders_them(service_factory):
    invoke, models, _ = service_factory()
    def check(doc, page, quote, boxes, claim):
        if claim == 'claim-1': raise TimeoutError('synthetic verifier failure')
        return {'supported': claim == 'claim-0', 'reason': 'exact per-claim result'}
    models.support_check = check
    result = invoke()['citations']
    assert [c['claim'] for c in result] == ['claim-0', 'claim-1', 'claim-2']
    assert [c['support_status'] for c in result] == ['checked', 'needs_review', 'needs_review']
    assert all(c['invocation_id'] == 'current' for c in result)


def test_final_authority_check_still_blocks_revoked_or_changed_source(service_factory):
    invoke, _, source_calls = service_factory(revoke=True)
    with pytest.raises(PermissionError, match='Source or access changed'):
        invoke()
    assert len(source_calls) == 2


def test_verifier_fanout_stays_at_existing_three_worker_bound(service_factory):
    invoke, models, _ = service_factory(count=8)
    lock = threading.Lock(); active = 0; peak = 0
    def check(*args):
        nonlocal active, peak
        with lock: active += 1; peak = max(peak, active)
        try:
            time.sleep(0.01)
            return {'supported': True, 'reason': 'fixture'}
        finally:
            with lock: active -= 1
    models.support_check = check
    result = invoke()
    assert len(result['citations']) == 8
    assert 1 < peak <= 3
