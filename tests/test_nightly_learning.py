import json
from datetime import datetime

import pytest

import nightly
from core.knowledge_maintenance import maintain_knowledge, learn_from_sources, read_json
from core.knowledge_retrieval import KnowledgeIndex


def test_normalizes_catalog_preserves_sources_and_loads_persistent_index(tmp_path, monkeypatch):
    kb = tmp_path / 'knowledge_base'
    kb.mkdir()
    source = kb / 'strangely.named.'
    source.write_bytes(b'Python programming teaches software design.\r\n')
    (kb / 'same.md').write_text('Python programming teaches software design.\n')
    (kb / '.DS_Store').write_bytes(b'\x00bad')
    result = maintain_knowledge(tmp_path)
    assert result['documents'] == 2
    assert result['duplicate_groups'] == 1
    assert source.read_bytes().endswith(b'\r\n')
    assert maintain_knowledge(tmp_path)['changed'] == 0
    index = KnowledgeIndex(kb)
    monkeypatch.setattr(index, '_read', lambda *a: pytest.fail('unchanged source was reparsed'))
    hit = index.search('python programming')[0][1]
    assert 'technology' in hit.metadata['topics']
    assert index.search('technology')


def test_study_notes_need_real_quotes_are_incremental_and_expire(tmp_path):
    kb = tmp_path / 'knowledge_base'
    kb.mkdir()
    source = kb / 'note.md'
    quote = 'Stoicism teaches that some things are outside our control.'
    source.write_text(quote)
    maintain_knowledge(tmp_path)
    bad = learn_from_sources(tmp_path, chat=lambda _: {'lesson': 'wrong', 'quotes': ['invented quote with enough characters']})
    assert bad['created'] == 0 and bad['failures']
    good = lambda _: {'lesson': 'Reflect on what can be controlled.', 'quotes': [quote]}
    assert learn_from_sources(tmp_path, chat=good)['created'] == 1
    assert learn_from_sources(tmp_path, chat=lambda _: pytest.fail('relearned'))['created'] == 0
    hits = KnowledgeIndex(kb).search('reflect controlled')
    assert hits[0][1].metadata['origin'] == 'derived-learning'
    source.write_text('New text about baking bread.')
    assert not KnowledgeIndex(kb).search('reflect controlled')
    maintain_knowledge(tmp_path)
    assert not any(name.startswith('learned_notes/') for name in read_json(tmp_path/'knowledge_state/catalog.json', {})['documents'])


def test_scheduler_idle_daily_gate_and_failed_stage_retry(tmp_path):
    calls = []
    def execute(name, timeout, root):
        calls.append(name)
        return {'status': 'error' if name == 'study' and calls.count('study') == 1 else 'success'}
    now = datetime(2026, 9, 19, 2, 0)
    assert 'Deferred' in nightly.run_due(tmp_path, now=now, idle=10, execute=execute)
    assert not calls
    nightly.run_due(tmp_path, now=now, idle=1000, execute=execute)
    assert calls == [name for name, _ in nightly.STAGES]
    assert 'Waiting' in nightly.run_due(tmp_path, now=now, idle=1000, execute=execute)
    nightly.run_due(tmp_path, now=now.replace(hour=3), idle=1000, execute=execute)
    assert calls[-2:] == ['study', 'index']
    assert 'Already completed' in nightly.run_due(tmp_path, now=now.replace(hour=4), idle=1000, execute=execute)


def test_scheduler_lock_and_midnight_catchup(tmp_path):
    assert nightly.due_date(datetime(2026, 9, 19, 1, 59)) == '2026-09-18'
    with nightly.cycle_lock(tmp_path):
        assert 'already running' in nightly.run_due(tmp_path, force=True)
    plist = nightly.launch_agent(tmp_path)
    assert plist['StartCalendarInterval'] == {'Hour': 2, 'Minute': 0}
    assert plist['StartInterval'] == 900
    assert str(tmp_path/'venv/bin/python') in plist['ProgramArguments']


def test_overnight_continues_after_failure(isolated_data_dir, monkeypatch):
    import webagent
    monkeypatch.setattr(webagent, 'historian', lambda **kw: (_ for _ in ()).throw(RuntimeError('bad historian')))
    monkeypatch.setattr(webagent, 'run_self_improve_cycle', lambda: (True, 'skipped'))
    monkeypatch.setattr(webagent, 'run_tool_generation_cycle', lambda *a, **kw: 'no gap')
    report = webagent.run_overnight_cycle()
    assert 'ERROR RuntimeError: bad historian' in report
    assert 'Retrieval refresh:' in report and 'Self-improve:\nskipped' in report
    assert 'Status: partial failure:' in report


def test_historian_preserves_distinct_url_versions_and_archives_duplicates(isolated_data_dir, monkeypatch):
    import webagent
    kb = isolated_data_dir/'knowledge_base/web_evidence'
    kb.mkdir(parents=True)
    for name, content in [('old', 'Original report'), ('new', 'Changed report'), ('duplicate', 'Changed report')]:
        (kb/f'{name}.json').write_text(json.dumps({'url': 'https://example.test/article', 'content': content, 'captured_at': name}))
    stats = webagent.historian_clean_knowledge_base()
    assert stats['web_evidence_duplicates_removed'] == 1
    assert len(list(kb.glob('*.json'))) == 2
    assert len(list((isolated_data_dir/'knowledge_state/archive').rglob('*.json'))) == 1


def test_installer_keeps_unrelated_cron_entries():
    from scripts.install_nightly import remove_overnight_entries
    source = '# env\nMAILTO=a\n# gnosis:12345678 Nightly\n0 2 * * * python --cron-task 12345678\n# gnosis:87654321 Alarm\n0 9 * * * alarm\n'
    assert remove_overnight_entries(source, {'12345678'}) == '# env\nMAILTO=a\n# gnosis:87654321 Alarm\n0 9 * * * alarm\n'


def test_stage_timeout_kills_process_group(tmp_path, monkeypatch):
    import subprocess
    calls = []
    class Process:
        pid = 12345
        def wait(self, timeout=None):
            if timeout:
                raise subprocess.TimeoutExpired('stage', timeout)
            calls.append('reaped')
    monkeypatch.setattr(nightly.subprocess, 'Popen', lambda *a, **kw: Process())
    monkeypatch.setattr(nightly.os, 'killpg', lambda pid, sig: calls.append(pid))
    assert nightly.execute_stage('study', 1, tmp_path)['status'] == 'timeout'
    assert calls == [12345, 'reaped']


def test_sort_handles_bucket_file_collision_without_staging(isolated_data_dir, monkeypatch):
    import webagent
    kb = isolated_data_dir/'knowledge_base'
    kb.mkdir()
    (kb/'science').write_text('Astronomy observations')
    (kb/'note.md').write_text('Physics observations')
    monkeypatch.setattr(webagent, '_historian_classify_topics', lambda titles, **kw: ['science'] * len(titles))
    webagent.historian_clean_knowledge_base()
    assert sorted(p.read_text() for p in kb.rglob('*') if p.is_file()) == ['Astronomy observations', 'Physics observations']
    assert not (kb/'.historian_staging').exists()


def test_study_can_select_exact_excerpts_by_id(tmp_path):
    kb = tmp_path/'knowledge_base'
    kb.mkdir()
    quote = 'Python programming uses functions to organize reusable software.'
    (kb/'note.md').write_text(quote)
    maintain_knowledge(tmp_path)
    result = learn_from_sources(tmp_path, chat=lambda _: {'lesson': 'Functions organize code.', 'quote_ids': [0]})
    assert result['created'] == 1
    note = read_json(next((kb/'learned_notes').glob('*.json')), {})
    assert quote in note['content']
