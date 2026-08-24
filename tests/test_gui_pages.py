"""Headless tests for the nav-rail pages added when webagent_gui.py became a
full local app (left nav + QStackedWidget) instead of only a chat window:
Self-Improve/Overnight control, the Report dashboard, generated-skill
Proposals, and the Knowledge/Experience/Activity browser. Same
offscreen/no-real-event-loop discipline as test_gui_context.py - runs with
QT_QPA_PLATFORM=offscreen, never calls app.exec().
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication

import webagent_gui
from core import config as core_config
from core.activity_log import record_activity
from memory.experience import build_experience, record_experience


@pytest.fixture(scope="module")
def qapp():
    """Skip (rather than error the whole suite) if the Qt platform plugin
    itself can't initialize headlessly - see test_gui_context.py."""
    try:
        return QApplication.instance() or QApplication([])
    except Exception as exc:
        pytest.skip(f"Qt platform plugin could not initialize headlessly: {exc}")


@pytest.fixture
def gui(qapp, isolated_data_dir):
    window = webagent_gui.WebAgentGUI()
    yield window
    window.close()
    window.deleteLater()


def test_nav_has_five_pages(gui):
    assert gui.pages.count() == 5
    assert gui.nav_list.count() == 5


def test_nav_switches_pages(gui):
    for i in range(5):
        gui.nav_list.setCurrentRow(i)
        assert gui.pages.currentIndex() == i


def test_report_page_runs_with_no_data(gui):
    gui._refresh_report()
    text = gui.report_output.toPlainText()
    assert "Task completion" in text
    assert "Tool usage" in text
    assert "None recorded yet" in text or "No " in text


def test_proposals_page_shows_no_items_with_nothing_generated_yet(gui):
    gui._refresh_proposals()
    assert gui.proposals_list.count() == 0


def test_proposals_page_lists_and_loads_a_real_proposal(gui):
    proposals_dir = core_config.path("gnosis_workspace", "proposals", "20260101_000000_example")
    os.makedirs(proposals_dir, exist_ok=True)
    with open(os.path.join(proposals_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("# a proposal\nSecurity: OK")
    with open(os.path.join(proposals_dir, "example.py"), "w", encoding="utf-8") as f:
        f.write("class Example:\n    pass\n")

    gui._refresh_proposals()
    assert gui.proposals_list.count() == 1
    item = gui.proposals_list.item(0)
    assert item.text() == "20260101_000000_example"

    gui._load_proposal(item)
    detail = gui.proposals_detail.toPlainText()
    assert "a proposal" in detail
    assert "class Example" in detail


def test_knowledge_page_lists_and_loads_a_real_file(gui):
    kb_dir = core_config.path("knowledge_base")
    os.makedirs(kb_dir, exist_ok=True)
    with open(os.path.join(kb_dir, "example.txt"), "w", encoding="utf-8") as f:
        f.write("hello knowledge base")

    gui._refresh_kb_list()
    items = [gui.kb_list.item(i).text() for i in range(gui.kb_list.count())]
    assert "example.txt" in items

    gui._load_kb_file(gui.kb_list.item(items.index("example.txt")))
    assert gui.kb_detail.toPlainText() == "hello knowledge base"


def test_experience_tab_shows_a_real_record(gui):
    experience = build_experience(
        goal="test goal", result="ok", success=True, agent="self-improve",
    )
    record_experience(experience)
    gui._refresh_experience_log()
    assert "test goal" in gui.experience_output.toPlainText()


def test_activity_tab_shows_a_real_record(gui):
    record_activity("TEST_EVENT", foo="bar")
    gui._refresh_activity_log()
    text = gui.activity_output.toPlainText()
    assert "TEST_EVENT" in text
    assert "bar" in text


def test_run_cycle_wires_a_successful_worker_result_into_the_output(gui, qapp):
    gui._run_cycle("Test", lambda: "a fake report")
    gui._si_worker.wait(2000)
    qapp.processEvents()
    assert "a fake report" in gui.si_output.toPlainText()
    assert gui.si_preview_button.isEnabled()


def test_run_cycle_wires_a_selfimprove_style_tuple_result_into_the_output(gui, qapp):
    gui._run_cycle("Test", lambda: (True, "diff applied"))
    gui._si_worker.wait(2000)
    qapp.processEvents()
    assert "diff applied" in gui.si_output.toPlainText()
    assert "succeeded" in gui.si_status_label.text()


def test_run_cycle_wires_a_worker_error_into_the_output(gui, qapp):
    def boom():
        raise RuntimeError("kaboom")

    gui._run_cycle("Test", boom)
    gui._si_worker.wait(2000)
    qapp.processEvents()
    assert "kaboom" in gui.si_output.toPlainText()
    assert gui.si_preview_button.isEnabled()
