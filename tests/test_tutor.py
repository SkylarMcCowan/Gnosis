"""Regression tests for /tutor learning paths (webagent.py:4425-4450)."""
import pytest

import webagent


@pytest.fixture(autouse=True)
def clean_learning_paths():
    """learning_paths is a module-level dict mutated in place (not redirected
    by isolated_data_dir) - restore it after each test so these tests can't
    leak state into each other or into other test files."""
    before = dict(webagent.learning_paths)
    yield
    webagent.learning_paths.clear()
    webagent.learning_paths.update(before)


def test_create_and_show_learning_path(isolated_data_dir, capsys):
    webagent.create_learning_path("stoicism", ["Meditations", "Letters from a Stoic"])
    assert webagent.learning_paths["stoicism"] == ["Meditations", "Letters from a Stoic"]

    capsys.readouterr()
    webagent.show_learning_path("stoicism")
    out = capsys.readouterr().out
    assert "Meditations" in out


def test_delete_learning_path(isolated_data_dir, capsys):
    webagent.create_learning_path("stoicism", ["Meditations"])
    webagent.delete_learning_path("stoicism")
    assert "stoicism" not in webagent.learning_paths

    capsys.readouterr()
    webagent.show_learning_path("stoicism")
    out = capsys.readouterr().out
    assert "No learning path found" in out


def test_delete_unknown_learning_path_reports_not_found(isolated_data_dir, capsys):
    webagent.delete_learning_path("not_a_real_topic")
    out = capsys.readouterr().out
    assert "No learning path found" in out
