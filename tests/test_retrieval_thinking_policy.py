"""Candidate selection can use a lighter generation policy without changing evidence checks."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.utils.ai_client import LLMClient
from app.services import pageindex_engine as engine
from test_pageindex_auto_candidates import document, db_for


def captured_client(first_error=None):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        if first_error is not None and len(calls) == 1:
            raise first_error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"selected":[]}'))])
    client = LLMClient()
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, calls


@pytest.mark.parametrize('model,thinking,expected', [
    ('deepseek-flash', False, {'thinking': {'type': 'disabled'}}),
    ('deepseek-v4-pro', True, {'thinking': {'type': 'enabled'}}),
    ('deepseek-flash', None, None),
    ('unverified-endpoint-model', False, None),
])
def test_mode_is_explicit_and_only_mapped_for_known_model_contracts(model, thinking, expected):
    client, calls = captured_client()
    messages = [{'role': 'user', 'content': 'Return JSON candidates from the supplied outline.'}]
    client.chat(messages, model=model, thinking=thinking, json_mode=True)
    assert len(calls) == 1
    assert calls[0].get('extra_body') == expected
    assert calls[0]['messages'] == messages
    assert calls[0]['model'] == model
    assert calls[0]['response_format'] == {'type': 'json_object'}


def test_original_callers_do_not_change_their_reasoning_policy():
    client, calls = captured_client()
    client.chat([{'role': 'user', 'content': 'Build the original index.'}], model='deepseek-flash')
    assert 'extra_body' not in calls[0]


def test_json_compatibility_retry_keeps_the_same_explicit_mode():
    payload = {'error': {'code': 'unsupported_parameter', 'param': 'response_format'}}
    error = APIStatusError('fixture', response=httpx.Response(400,
        request=httpx.Request('POST', 'https://fixture.invalid/chat/completions'), json=payload), body=payload)
    client, calls = captured_client(error)
    client.chat([{'role': 'user', 'content': 'JSON candidates'}], model='deepseek-flash', thinking=False, json_mode=True)
    assert len(calls) == 2
    assert all(call['extra_body'] == {'thinking': {'type': 'disabled'}} for call in calls)
    assert 'response_format' not in calls[1]


@pytest.mark.parametrize('disable', [True, False])
def test_original_tree_engine_applies_only_the_candidate_selection_mode(monkeypatch, disable):
    monkeypatch.setattr(engine.settings, 'pageindex_retrieve_disable_thinking', disable)
    seen = []
    def select(messages, **kwargs):
        seen.append((messages, kwargs))
        return json.dumps({'selected': [{'doc_id': 'source-a', 'node_id': 'n1', 'relevance': 0.9}]})
    monkeypatch.setattr(engine.llm_client, 'chat', select)
    monkeypatch.setattr(engine, '_build_result', lambda doc, tree, node, score, **kw: {
        'document_id': doc.id, 'content': doc.full_text[node['start']:node['end']], 'score': score})
    hits, _, extra = engine.retrieve('authorized-kb', 'unseen conceptual question', 3,
        db=db_for([document()]), prefer_lexical=True)
    assert len(seen) == 1
    assert seen[0][1]['thinking'] == (False if disable else None)
    assert seen[0][1]['json_mode'] is True
    assert 'unseen conceptual question' in str(seen[0][0])
    assert hits[0]['document_id'] == 'source-a'
    assert hits[0]['content'] == document().full_text
    assert extra['attempts'] == 1


def test_strong_literal_candidate_path_still_does_not_call_a_model(monkeypatch):
    monkeypatch.setattr(engine.settings, 'pageindex_retrieve_disable_thinking', True)
    def forbidden(*_args, **_kwargs):
        raise AssertionError('A literal candidate does not need another model')
    monkeypatch.setattr(engine.llm_client, 'chat', forbidden)
    monkeypatch.setattr(engine, '_build_result', lambda doc, tree, node, score, **kw: {
        'document_id': doc.id, 'content': doc.full_text[node['start']:node['end']], 'score': score,
        'metadata': kw})
    hits, _, extra = engine.retrieve('authorized-kb', 'alpha beta gamma', 3,
        db=db_for([document()]), prefer_lexical=True)
    assert hits and extra['attempts'] == 0 and extra['semantic_selection'] is False
    assert 'checked' not in json.dumps(hits)
