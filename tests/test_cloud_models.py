import json

import pytest

from core import cloud_models, models


@pytest.fixture(autouse=True)
def connections(monkeypatch):
    monkeypatch.setattr(cloud_models, "_connections", {})
    for provider in cloud_models.PROVIDERS.values():
        monkeypatch.delenv(provider[1], raising=False)
        monkeypatch.delenv(provider[2], raising=False)


class Response:
    ok = True
    closed = False

    def __init__(self, data=None, events=()):
        self.data = data
        self.events = events

    def json(self):
        return self.data

    def iter_lines(self, **kwargs):
        yield ': heartbeat'
        for event in self.events:
            yield 'data: ' + json.dumps(event)
        yield 'data: [DONE]'

    def close(self):
        self.closed = True


@pytest.mark.parametrize('provider', ['openai', 'anthropic'])
def test_cloud_dispatch_and_payload(monkeypatch, provider):
    cloud_models.configure(provider, 'secret', 'test-model')
    monkeypatch.setattr(models, 'ollama', None)
    response = Response({'choices': [{'message': {'content': 'hello'}}]} if provider == 'openai'
                        else {'content': [{'type': 'text', 'text': 'hello'}]})
    calls = []
    monkeypatch.setattr(cloud_models.requests, 'post', lambda url, **kw: calls.append((url, kw)) or response)
    result = models.chat(f'{provider}:test-model', [
        {'role': 'system', 'content': 'persona'},
        {'role': 'user', 'content': 'hi', 'sources': ['private annotation']},
    ], options={'num_ctx': 4096})
    assert result['message']['content'] == 'hello'
    body = calls[0][1]['json']
    assert all('sources' not in m for m in body['messages'])
    assert 'options' not in body
    if provider == 'anthropic':
        assert body['system'] == 'persona'
        assert body['messages'] == [{'role': 'user', 'content': 'hi'}]
        assert body['max_tokens'] == 4096
    assert response.closed


@pytest.mark.parametrize('provider,event', [
    ('openai', {'choices': [{'delta': {'content': 'héllo'}}]}),
    ('anthropic', {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'héllo'}}),
])
def test_streaming_and_close(monkeypatch, provider, event):
    cloud_models.configure(provider, 'secret', 'model')
    response = Response(events=[event])
    monkeypatch.setattr(cloud_models.requests, 'post', lambda *a, **kw: response)
    chunks = list(models.chat(f'{provider}:model', [{'role': 'user', 'content': 'hi'}], stream=True))
    assert chunks == [{'message': {'role': 'assistant', 'content': 'héllo'}}]
    assert response.closed


def test_credentials_and_env(monkeypatch):
    with pytest.raises(ValueError):
        cloud_models.configure('openai', '', 'model')
    with pytest.raises(RuntimeError, match='Configure OpenAI'):
        models.chat('openai:model', [])
    monkeypatch.setenv('OPENAI_API_KEY', 'secret')
    monkeypatch.setenv('OPENAI_MODEL', 'model')
    assert cloud_models.configured_models() == ['openai:model']


def test_api_errors_do_not_expose_credentials(monkeypatch):
    cloud_models.configure('openai', 'secret', 'model')
    response = Response()
    response.ok, response.status_code = False, 401
    monkeypatch.setattr(cloud_models.requests, 'post', lambda *a, **kw: response)
    with pytest.raises(RuntimeError, match='Check your API key') as exc:
        models.chat('openai:model', [])
    assert 'secret' not in str(exc.value)
    assert response.closed


def test_stream_error_closes_response(monkeypatch):
    cloud_models.configure('anthropic', 'secret', 'model')
    response = Response(events=[{'type': 'error', 'error': {'message': 'secret'}}])
    monkeypatch.setattr(cloud_models.requests, 'post', lambda *a, **kw: response)
    with pytest.raises(RuntimeError, match='interrupted'):
        list(models.chat('anthropic:model', [], stream=True))
    assert response.closed
