"""Saved overnight cron entries now dispatch one isolated learning task."""
import webagent


def test_legacy_alias_dispatches_learning(monkeypatch):
    monkeypatch.setattr(webagent, 'run_unsupervised_learning_task', lambda: {'task': 'test'})
    assert webagent.run_overnight_cycle() == {'task': 'test'}


def test_cron_reports_research_failure(monkeypatch):
    monkeypatch.setattr(webagent, 'run_unsupervised_learning_task',
                        lambda: {'research': {'errors': ['offline']}})
    success, output = webagent._execute_cron_task({'action_type': 'feature', 'action_payload': 'overnight'})
    assert not success
    assert 'offline' in output
