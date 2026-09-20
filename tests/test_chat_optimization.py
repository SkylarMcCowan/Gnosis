import json

import pytest

import webagent
from core import models
from core.chat_optimization import budget_messages, estimated_tokens, is_direct_chat
from observability import model_metrics


@pytest.mark.parametrize('prompt', ['hello', 'Thanks!', '2+2', 'calculate (3 * 9)', 'tell me a joke', 'hello what is two plus two', 'what is three times four'])
def test_casual_chat_needs_one_model_call(prompt, fake_ollama_chat, monkeypatch):
    webagent.context.web_search_mode = True
    monkeypatch.setattr(webagent.context, 'selected_model', None)
    def unexpected(*args):
        pytest.fail('Direct chat called a planner')
    monkeypatch.setattr(webagent, 'model_directed_web_research', unexpected)
    monkeypatch.setattr(webagent, '_select_tool_action', unexpected)
    assert webagent.chat_response(prompt)
    assert len(fake_ollama_chat.calls) == 1
    assert fake_ollama_chat.calls[0]['think'] is False


@pytest.mark.parametrize('prompt', ["what's the weather today?", 'hello, check my git status',
                                    'tell me a joke about the latest news', 'are you sure?',
                                    'what was the last fixture?', 'search for a joke', 'what is the overview effect?'])
def test_ambiguous_or_current_requests_keep_planning(prompt):
    assert not is_direct_chat(prompt)


def test_deep_think_keeps_research_for_greeting(fake_ollama_chat, monkeypatch):
    monkeypatch.setattr(webagent.context, 'deep_think_mode', True)
    monkeypatch.setattr(webagent.context, 'selected_model', None)
    calls = []
    monkeypatch.setattr(webagent, 'model_directed_web_research', lambda prompt: calls.append(prompt) or [])
    monkeypatch.setattr(webagent, '_select_tool_action', lambda prompt: {'tool': None})
    webagent.chat_response('hello')
    assert calls == ['hello']
    assert next(c for c in fake_ollama_chat.calls if c['stream'])['think'] is True


def test_retry_followup_reuses_previous_request_for_research(fake_ollama_chat, monkeypatch):
    monkeypatch.setattr(webagent.context, 'selected_model', None)
    webagent.context.web_search_mode = True
    webagent.context.assistant_convo += [
        {'role': 'user', 'content': 'give me a list of 100 books to read before i die'},
        {'role': 'assistant', 'content': 'Here are some recommendations.'},
    ]
    research_prompts = []
    monkeypatch.setattr(
        webagent, 'model_directed_web_research',
        lambda prompt: research_prompts.append(prompt) or [],
    )
    monkeypatch.setattr(webagent, '_select_tool_action', lambda prompt: {'tool': None})

    webagent.chat_response('try again')

    assert research_prompts == ['give me a list of 100 books to read before i die']
    assert webagent.context.assistant_convo[-2]['role'] == 'user'
    assert webagent.context.assistant_convo[-2]['content'] == 'try again'


def test_refresh_context_preserves_history_and_seed(fake_ollama_chat, monkeypatch):
    monkeypatch.setattr(webagent.context, 'selected_model', None)
    monkeypatch.setattr(webagent, 'get_persona_system_prompt', lambda: 'Be concise')
    monkeypatch.setattr(webagent, 'get_relevant_agent_memory', lambda *args: 'Relevant memory')
    for _ in range(4):
        webagent.chat_response('hello')
    convo = webagent.context.assistant_convo
    assert len([m for m in convo if m.get('_turn_context')]) == 3
    assert len([m for m in convo if m['role'] == 'user']) == 4
    assert convo[0]['content'] == webagent.sys_msgs.assistant_msg['content']
    payload = fake_ollama_chat.calls[-1]['messages']
    assert all(not any(k.startswith('_') for k in m) for m in payload)
    assert sum(m['content'] == 'Be concise' for m in payload) == 1


def test_terminal_shortcut_and_refresh(fake_ollama_chat, monkeypatch):
    monkeypatch.setattr(webagent.context, 'selected_model', None)
    monkeypatch.setattr(webagent.context, 'web_search_mode', True)
    monkeypatch.setattr(webagent, 'model_directed_web_research', lambda prompt: pytest.fail('Unexpected research'))
    for _ in range(3):
        webagent._handle_unmatched_prompt('hello')
    assert len(fake_ollama_chat.calls) == 3
    assert len([m for m in webagent.context.assistant_convo if m.get('_turn_context')]) == 1


def test_budget_preserves_latest_complete_turn_and_excerpts():
    messages = [{'role': 'system', 'content': 'Instructions'}]
    for i in range(9):
        messages += [{'role': 'user', 'content': f'Question {i} ' + 'x' * 260},
                     {'role': 'assistant', 'content': f'Answer {i} ' + 'y' * 260}]
    messages += [{'role': 'user', 'content': 'Newest request'}]
    result = budget_messages(messages, 1024)
    assert result[0] == messages[0]
    assert result[-1] == messages[-1]
    assert sum(map(estimated_tokens, result)) <= 768
    assert any(m.get('_history_excerpt') for m in result)
    turns = [m for m in result if m['role'] != 'system']
    assert turns[0]['role'] == 'user'
    for i, m in enumerate(turns):
        if m['role'] == 'assistant':
            assert turns[i-1]['role'] == 'user'


def test_overflow_does_not_drop_current_request():
    messages = [{'role': 'system', 'content': 'instructions'}, {'role': 'user', 'content': 'x' * 4000}]
    with pytest.raises(ValueError, match='current request'):
        budget_messages(messages, 1024)
    assert len(messages[-1]['content']) == 4000


def test_seed_is_included_in_budget():
    with pytest.raises(ValueError):
        budget_messages([{'role': 'system', 'content': 'x' * 2200}, {'role': 'user', 'content': 'y' * 300}], 1024)


@pytest.mark.parametrize('model,enabled,expected', [
    ('qwen3.5:4b', False, {'think': False}), ('qwen3.5:4b', True, {'think': True}),
    ('gpt-oss:20b', False, {'think': 'low'}), ('gpt-oss:20b', True, {'think': 'high'}),
    ('yi:6b', True, {}), ('openai:some-model', True, {}),
])
def test_thinking_is_model_specific(model, enabled, expected):
    assert models.thinking_options(model, enabled) == expected


def test_timing_final_chunk_and_opt_in_log(fake_ollama_chat, monkeypatch, isolated_data_dir):
    monkeypatch.setattr(model_metrics, 'recent_calls', __import__('collections').deque(maxlen=100))
    monkeypatch.setenv('GNOSIS_MODEL_METRICS', '1')
    monkeypatch.setenv('GNOSIS_OLLAMA_KEEP_ALIVE', '10m')
    final = {'done': True, 'eval_count': 20, 'eval_duration': 1000000000, 'load_duration': 100000000}
    def stream(**kwargs):
        assert kwargs['keep_alive'] == '10m'
        return iter([{'message': {'content': 'private answer'}}, final])
    monkeypatch.setattr(models.ollama, 'chat', stream)
    result = list(models.chat('qwen3.5:4b', [{'role': 'user', 'content': 'private prompt'}], stream=True))
    assert result[-1] == final
    timing = model_metrics.recent_calls[-1]
    assert timing['tokens_per_second'] == 20
    assert timing['first_content_seconds'] is not None
    log = (isolated_data_dir / 'activity' / 'model_metrics.jsonl').read_text()
    assert 'private' not in log
    assert json.loads(log)['load_duration'] == 100000000


def test_timing_closes_cancelled_stream(fake_ollama_chat, monkeypatch):
    closed = []
    def backend():
        try:
            yield {'message': {'content': 'part'}}
            yield {'done': True}
        finally:
            closed.append(True)
    monkeypatch.setattr(models.ollama, 'chat', lambda **kw: backend())
    stream = models.chat('yi:6b', [], stream=True)
    next(stream)
    stream.close()
    assert closed == [True]


def test_trimming_uses_selected_models_context(monkeypatch):
    messages = [{'role': 'system', 'content': 'instructions'}]
    for i in range(8):
        messages += [{'role': 'user', 'content': str(i) + 'x' * 900},
                     {'role': 'assistant', 'content': 'y' * 900}]
    messages += [{'role': 'user', 'content': 'Latest question'}]
    monkeypatch.setattr(webagent.context, 'selected_model', 'yi:6b')
    webagent.context.assistant_convo = messages[:]
    webagent.trim_conversation()
    small = len([m for m in webagent.context.assistant_convo if m['role'] == 'user'])
    monkeypatch.setattr(webagent.context, 'selected_model', 'qwen3.5:4b')
    webagent.context.assistant_convo = messages[:]
    webagent.trim_conversation()
    large = len([m for m in webagent.context.assistant_convo if m['role'] == 'user'])
    assert large > small
    assert webagent.context.assistant_convo[-1]['content'] == 'Latest question'


def test_utf8_budget_and_system_only_overflow():
    assert estimated_tokens({'content': '界' * 10}) > estimated_tokens({'content': 'x' * 10})
    with pytest.raises(ValueError, match='System instructions'):
        budget_messages([{'role': 'system', 'content': 'x' * 4000}], 1024)


def test_report_includes_model_timings(monkeypatch, capsys):
    from collections import deque
    monkeypatch.setattr(model_metrics, 'recent_calls', deque([
        {'model': 'qwen3.5:4b', 'elapsed_seconds': 1.3, 'first_content_seconds': 0.8, 'tokens_per_second': 35.2}
    ]))
    webagent._cmd_report('/report')
    output = capsys.readouterr().out
    assert 'qwen3.5:4b: 1.30s, first text 0.80s, 35.2 tokens/s' in output


def test_cancel_during_silent_thinking_closes_stream(fake_ollama_chat, monkeypatch):
    from core import models
    from core.exceptions import ChatCancelled
    cancelled = [False]
    closed = []
    def backend():
        try:
            yield {'message': {'thinking': 'reasoning', 'content': ''}}
            cancelled[0] = True
            yield {'message': {'thinking': 'more reasoning', 'content': ''}}
        finally:
            closed.append(True)
    monkeypatch.setattr(models.ollama, 'chat', lambda **kwargs: backend())
    def check():
        if cancelled[0]:
            raise ChatCancelled()
    with models.request_control(check):
        stream = models.chat('local-model', [], stream=True)
        next(stream)
        with pytest.raises(ChatCancelled):
            next(stream)
    assert closed == [True]
    # A later request must not inherit the cancellation check.
    assert models.chat('local-model', [], stream=True)
