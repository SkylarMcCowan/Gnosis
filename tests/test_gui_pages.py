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


def test_nav_has_eighteen_pages(gui):
    assert gui.pages.count() == 18
    assert gui.nav_list.count() == 18
    assert gui.pages.widget(17) is gui.paranormal_lab_widget
    assert "Investigation Lab" in gui.nav_list.item(17).text()
    assert gui.pages.widget(16) is gui.hermetic_study_widget
    assert "Tarot Study" in gui.nav_list.item(16).text()


def test_nav_switches_pages(gui):
    for i in range(gui.pages.count()):
        gui.nav_list.setCurrentRow(i)
        assert gui.pages.currentIndex() == i


def test_report_page_runs_with_no_data(gui):
    gui._refresh_report()
    text = gui.report_output.toPlainText()
    assert "Task completion" in text
    assert "Tool usage" in text
    assert "None recorded yet" in text or "No " in text


def test_learning_controls_replace_proposals(gui):
    assert all("Proposals" not in gui.nav_list.item(i).text() for i in range(gui.nav_list.count()))
    assert gui.si_learning_button.isCheckable()
    assert not gui.si_learning_button.isChecked()


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


def test_clear_activity_log_button_clears_the_log_after_confirmation(gui, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    record_activity("TEST_EVENT", foo="bar")
    gui._refresh_activity_log()
    assert "TEST_EVENT" in gui.activity_output.toPlainText()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    gui._clear_activity_log()

    assert gui.activity_output.toPlainText() == "No activity recorded yet."


def test_clear_activity_log_does_nothing_without_confirmation(gui, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    record_activity("TEST_EVENT", foo="bar")
    gui._refresh_activity_log()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

    gui._clear_activity_log()

    assert "TEST_EVENT" in gui.activity_output.toPlainText()


def test_run_cycle_wires_a_successful_worker_result_into_the_output(gui, qapp):
    gui._run_cycle("Test", lambda: "a fake report")
    gui._si_worker.wait(2000)
    qapp.processEvents()
    assert "a fake report" in gui.si_output.toPlainText()
    assert gui.si_run_button.isEnabled()


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
    assert gui.si_run_button.isEnabled()


def test_subscriptions_page_has_a_button_for_every_catalog_item(gui):
    expected = sum(len(items) for items in webagent_gui.SUBSCRIPTION_CATALOG.values())
    assert len(gui.subscription_catalog_buttons) == expected


def test_catalog_buttons_start_unchecked_with_nothing_subscribed(gui):
    assert all(not button.isChecked() for button in gui.subscription_catalog_buttons.values())


def test_refresh_checks_the_button_for_an_existing_subscription(gui):
    from core import subscriptions
    subscriptions.add_subscription("team", "Manchester United", metadata={"team_id": "360", "league_slug": "eng.1"})

    gui._refresh_subscription_buttons()

    assert gui.subscription_catalog_buttons[("team", "Manchester United")].isChecked()
    assert not gui.subscription_catalog_buttons[("website", "BBC News")].isChecked()


def test_checking_a_team_button_subscribes_in_the_background(gui, qapp, monkeypatch):
    import webagent
    from core import subscriptions
    monkeypatch.setattr(webagent, "_resolve_soccer_team", lambda name: ("360", "Manchester United", "eng.1"))
    button = gui.subscription_catalog_buttons[("team", "Manchester United")]

    button.setChecked(True)
    gui._subscription_worker.wait(2000)
    qapp.processEvents()

    assert button.isChecked()
    assert button.isEnabled()
    assert button.property("subState") == "on"
    assert [r["name"] for r in subscriptions.list_subscriptions()] == ["Manchester United"]


def test_checking_a_team_button_reverts_on_failure(gui, qapp, monkeypatch):
    import webagent
    from core import subscriptions
    monkeypatch.setattr(webagent, "_resolve_soccer_team", lambda name: None)
    button = gui.subscription_catalog_buttons[("team", "Manchester United")]

    button.setChecked(True)
    gui._subscription_worker.wait(2000)
    qapp.processEvents()

    assert not button.isChecked()
    assert button.isEnabled()
    assert button.property("subState") == "off"  # reverts to grey, not a distinct error color
    assert subscriptions.list_subscriptions() == []


def test_checking_a_website_button_subscribes_in_the_background(gui, qapp, monkeypatch):
    import webagent
    from core import subscriptions
    monkeypatch.setattr(webagent, "fetch_page_content", lambda url: "page text")
    button = gui.subscription_catalog_buttons[("website", "BBC News")]

    button.setChecked(True)
    gui._subscription_worker.wait(2000)
    qapp.processEvents()

    assert button.isChecked()
    assert button.property("subState") == "on"
    assert [r["name"] for r in subscriptions.list_subscriptions()] == ["BBC News"]


def test_unchecking_a_subscribed_button_removes_it_immediately(gui):
    """Removal is a local file write, no network - no worker/wait needed."""
    from core import subscriptions
    subscriptions.add_subscription("team", "Manchester United", metadata={"team_id": "360", "league_slug": "eng.1"})
    gui._refresh_subscription_buttons()
    button = gui.subscription_catalog_buttons[("team", "Manchester United")]
    assert button.isChecked()
    assert button.property("subState") == "on"

    button.setChecked(False)

    assert button.property("subState") == "off"
    assert subscriptions.list_subscriptions() == []


def test_catalog_buttons_default_to_the_grey_off_state(gui):
    assert all(button.property("subState") == "off" for button in gui.subscription_catalog_buttons.values())


def test_weather_chips_are_always_rendered_in_the_green_on_state(gui):
    from core import subscriptions
    subscriptions.add_subscription("weather", "Tucson, Arizona, United States", metadata={"location": "Tucson, Arizona, United States"})

    gui._refresh_weather_subscriptions()

    chip = gui.weather_grid.itemAt(0).widget()
    assert chip.property("subState") == "on"


def test_category_sections_start_expanded_and_can_be_collapsed(gui):
    section = gui._build_subscription_category_section("Test Category", [{"name": "X", "type": "website", "url": "https://x.example.com"}])
    toggle, content = section.layout().itemAt(0).widget(), section.layout().itemAt(1).widget()

    assert toggle.isChecked()
    assert content.isVisibleTo(section)
    assert toggle.text().startswith("▼")

    toggle.setChecked(False)

    assert not content.isVisibleTo(section)
    assert toggle.text().startswith("▶")

    toggle.setChecked(True)

    assert content.isVisibleTo(section)
    assert toggle.text().startswith("▼")


def test_weather_section_has_no_preset_buttons_initially(gui):
    assert gui.weather_grid.count() == 0


def test_adding_a_weather_location_validates_and_normalizes(gui, qapp, monkeypatch):
    import webagent
    from core import subscriptions
    monkeypatch.setattr(
        webagent, "fetch_current_weather",
        lambda location: {"place": "Tucson, Arizona, United States", "temp_f": 100},
    )
    gui.weather_location_input.setText("tucson")

    gui._add_weather_subscription_clicked()
    gui._subscription_worker.wait(2000)
    qapp.processEvents()

    assert gui.weather_grid.count() == 1
    records = subscriptions.list_subscriptions(sub_type="weather")
    assert records[0]["name"] == "Tucson, Arizona, United States"
    assert gui.weather_location_input.text() == ""


def test_adding_a_weather_location_shows_an_error_on_failure(gui, qapp, monkeypatch):
    import webagent
    from core import subscriptions
    monkeypatch.setattr(webagent, "fetch_current_weather", lambda location: None)
    gui.weather_location_input.setText("nowhere at all")

    gui._add_weather_subscription_clicked()
    gui._subscription_worker.wait(2000)
    qapp.processEvents()

    assert gui.weather_grid.count() == 0
    assert "nowhere at all" in gui.subscription_status_label.text()
    assert subscriptions.list_subscriptions() == []


def test_adding_a_weather_location_without_text_shows_a_message(gui):
    gui._add_weather_subscription_clicked()
    assert "location" in gui.subscription_status_label.text().lower()


def test_removing_a_weather_subscription(gui):
    from core import subscriptions
    record = subscriptions.add_subscription("weather", "Tucson, Arizona, United States", metadata={"location": "Tucson, Arizona, United States"})
    gui._refresh_weather_subscriptions()
    assert gui.weather_grid.count() == 1

    gui._remove_weather_subscription_clicked(record)

    assert gui.weather_grid.count() == 0
    assert subscriptions.list_subscriptions() == []


def test_selfimprove_has_one_live_output(gui):
    from PyQt6.QtWidgets import QTextEdit
    assert len(gui.si_output.parentWidget().findChildren(QTextEdit)) == 1
    gui._append_si_output('Code improvement result')
    gui._learning.emit('Searching: coral reefs')
    gui._tick_learning()
    text = gui.si_output.toPlainText()
    assert 'Code improvement result' in text
    assert 'Searching: coral reefs' in text
    gui._tick_learning()
    assert gui.si_output.toPlainText() == text
