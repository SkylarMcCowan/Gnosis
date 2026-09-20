"""Bounded in-memory Ollama timing records; optional JSONL, never prompt text."""
from collections import deque
from datetime import datetime, timezone
import json
import os
import threading

from core import config

recent_calls = deque(maxlen=100)
_lock = threading.Lock()


def record(model, response, elapsed, first_content):
    def value(name):
        return response.get(name) if isinstance(response, dict) else getattr(response, name, None)
    item = {'timestamp': datetime.now(timezone.utc).isoformat(), 'model': model,
            'elapsed_seconds': round(elapsed, 4), 'first_content_seconds': first_content}
    for name in ('total_duration', 'load_duration', 'prompt_eval_count', 'prompt_eval_duration', 'eval_count', 'eval_duration'):
        data = value(name)
        if data is not None:
            item[name] = data
    duration = item.get('eval_duration', 0)
    if duration:
        item['tokens_per_second'] = round(item.get('eval_count', 0) * 1e9 / duration, 2)
    with _lock:
        recent_calls.append(item)
        if os.getenv('GNOSIS_MODEL_METRICS') == '1':
            try:
                path = config.path('activity', 'model_metrics.jsonl')
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'a', encoding='utf-8') as handle:
                    handle.write(json.dumps(item) + '\n')
            except OSError:
                pass
