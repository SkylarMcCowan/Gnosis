"""Regression tests for core/config.py, the second Phase 1 extraction: the
single, overridable project root every webagent.py data path now resolves
through instead of computing os.path.dirname(__file__) locally 21 times.
"""
from core import config as core_config


def test_project_root_defaults_to_the_real_checkout(monkeypatch):
    """isolated_data_dir is autouse (see tests/conftest.py) so every test
    gets an overridden root by default - this test explicitly undoes that
    to check the real, unpatched default."""
    monkeypatch.setattr(core_config, "_root_override", None)
    assert core_config.project_root().endswith("Gnosis")
    assert core_config.path("knowledge_base") == core_config.project_root() + "/knowledge_base"


def test_project_root_honors_an_override(monkeypatch, tmp_path):
    monkeypatch.setattr(core_config, "_root_override", str(tmp_path))
    assert core_config.project_root() == str(tmp_path)
    assert core_config.path("cron", "tasks.json") == str(tmp_path / "cron" / "tasks.json")


def test_webagent_data_paths_honor_the_isolated_root(isolated_data_dir):
    import webagent
    assert webagent.load_agent_memory("ethics") == []
    webagent.save_agent_memory("ethics", "a test memory")
    assert (isolated_data_dir / "agent_memory" / "ethics_memory.json").exists()
