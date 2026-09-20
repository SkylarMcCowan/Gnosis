from core.result_cache import ResultCache


def test_cache_expiry_copy_isolation_and_bounded_size():
    now = [0]
    cache = ResultCache(max_entries=2, clock=lambda: now[0])
    cache.put('a', [{'value': 1}], 10)
    value = cache.get('a'); value[0]['value'] = 9
    assert cache.get('a')[0]['value'] == 1
    cache.put('b', [2], 10); cache.put('c', [3], 10)
    assert cache.get('a') is None
    now[0] = 10
    assert cache.get('c') is None
    cache.put('failed', [], 10)
    assert cache.get('failed') is None


def test_subscription_cache_preserves_capture_date_and_verify_bypasses(isolated_data_dir, monkeypatch):
    import webagent
    record = webagent.add_topic_subscription('Astronomy')
    calls = []
    def handler(record, prompt):
        calls.append(prompt)
        return [{'content': 'A captured report', 'captured_at': '2020-01-01'}]
    monkeypatch.setitem(webagent._SUBSCRIPTION_HANDLERS, 'topic', handler)
    first = webagent._subscription_bypass('Astronomy news')
    again = webagent._subscription_bypass('Astronomy news')
    assert len(calls) == 1
    assert first == again and again[0]['captured_at'] == '2020-01-01'
    webagent._subscription_bypass('verify Astronomy news')
    webagent._subscription_bypass('verify Astronomy news')
    assert len(calls) == 3
