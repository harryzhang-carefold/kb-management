"""Only explicit unsupported-format errors justify a second model request."""
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
from openai import APIStatusError
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.utils.ai_client import LLMClient


def status_error(status, param=None, code='invalid_request_error'):
    body = {'error': {'code': code, 'param': param, 'message': 'fixture error'}}
    response = httpx.Response(status, request=httpx.Request('POST', 'https://fixture.invalid/chat/completions'), json=body)
    return APIStatusError('fixture error', response=response, body=body)


def client_with(error):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"selected":[]}'))])
    client = LLMClient()
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, calls


@pytest.mark.parametrize('error', [TimeoutError('fixture timeout'), status_error(401), status_error(429),
                                 status_error(500), status_error(400, 'temperature')])
def test_transport_auth_rate_limit_and_unrelated_bad_input_do_not_retry_without_json(error):
    client, calls = client_with(error)
    with pytest.raises(type(error)):
        client.chat([{'role': 'user', 'content': 'fixture'}], model='fixture', json_mode=True)
    assert len(calls) == 1
    assert calls[0]['response_format'] == {'type': 'json_object'}


def test_explicit_unsupported_response_format_retries_once_without_that_parameter():
    client, calls = client_with(status_error(400, 'response_format', 'unsupported_parameter'))
    result = client.chat([{'role': 'user', 'content': 'fixture'}], model='fixture', json_mode=True)
    assert result == '{"selected":[]}'
    assert len(calls) == 2
    assert calls[0]['response_format'] == {'type': 'json_object'}
    assert 'response_format' not in calls[1]
    assert calls[0]['messages'] == calls[1]['messages']
    assert calls[0]['model'] == calls[1]['model']
