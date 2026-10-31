import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.knowledge import models


class _Response:
    def __init__(self, supported, source_text_ok, finish_reason='stop'):
        self._payload = {'choices': [{'finish_reason': finish_reason, 'message': {'content':
            __import__('json').dumps({'supported': supported, 'source_text_ok': source_text_ok,
                                      'reason': 'fixture reason'})}}]}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, *_args, **_kwargs):
        return self.response


def _run(monkeypatch, supported, source_text_ok):
    monkeypatch.setattr(models, 'backend', lambda: ('fixture', {'base_url': 'http://fixture', 'api_key': 'key'}))
    monkeypatch.setattr(models.httpx, 'Client', lambda **_kwargs: _Client(_Response(supported, source_text_ok)))
    return models.support_check({'ocr_pages': []}, 0, 'source', [], 'claim')


def test_support_checker_returns_stable_reason_codes(monkeypatch):
    assert _run(monkeypatch, True, True) == {
        'supported': True, 'reason_code': 'checked', 'reason': 'fixture reason'}
    assert _run(monkeypatch, False, True) == {
        'supported': False, 'reason_code': 'claim_not_supported', 'reason': 'fixture reason'}
    assert _run(monkeypatch, True, False) == {
        'supported': False, 'reason_code': 'source_text_mismatch', 'reason': 'fixture reason'}


def test_truncated_verifier_output_cannot_be_treated_as_semantic_support(monkeypatch):
    monkeypatch.setattr(models, 'backend', lambda: ('fixture', {'base_url': 'http://fixture', 'api_key': 'key'}))
    monkeypatch.setattr(models, 'CHECK_TOKEN_BUDGETS', (1,))
    monkeypatch.setattr(models.httpx, 'Client', lambda **_kwargs: _Client(_Response(True, True, 'length')))
    result = models.support_check({'ocr_pages': []}, 0, 'source', [], 'claim')
    assert result['supported'] is False
    assert result['reason_code'] == 'verifier_truncated'


def test_pageindex_and_spreadsheet_verifiers_publish_reason_codes_to_the_evidence_ledger():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    pageindex = (root / 'backend/app/knowledge/service.py').read_text()
    spreadsheet = (root / 'backend/app/knowledge/spreadsheet_service.py').read_text()
    assert "check.get('reason_code'" in pageindex
    assert "'reason_code': 'verifier_unavailable'" in pageindex
    assert "check.get('reason_code'" in spreadsheet
    assert "'reason_code': reason_code" in spreadsheet
    assert "'verifier_unavailable'" in spreadsheet
