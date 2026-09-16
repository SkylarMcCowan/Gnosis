"""Tests for GC-063's campaign history log."""
from ethereal_dnd.campaign.history import format_event
from ethereal_dnd.cli import debug_cli
from ethereal_dnd.core.events import CharacterDied, QuestStarted
from ethereal_dnd.world.travel import travel


def test_new_campaign_starts_with_empty_history():
    campaign = debug_cli.new_campaign(seed=1)
    assert campaign.history == []


def test_travel_appends_timestamped_entries():
    campaign = debug_cli.new_ravenhollow_campaign(seed=1)
    travel(campaign, "farmstead")
    assert any("set out from ravenhollow" in entry for entry in campaign.history)
    assert any("arrived at farmstead" in entry for entry in campaign.history)
    assert all(entry.startswith("Day ") for entry in campaign.history)


def test_quest_events_are_logged():
    campaign = debug_cli.new_ravenhollow_campaign(seed=1)
    debug_cli.accept_quest(campaign, "wolves_of_blackwood")
    assert any("Quest started: wolves_of_blackwood" in entry for entry in campaign.history)


def test_format_event_has_a_readable_fallback_for_unknown_types():
    class FakeEvent:
        type = "SomethingNobodyWroteAFormatterFor"

    assert format_event(FakeEvent()) == "SomethingNobodyWroteAFormatterFor occurred."


def test_format_event_handles_a_death_without_a_location():
    assert format_event(CharacterDied(character_id="abc123")) == "abc123 died."


def test_format_event_handles_a_death_with_a_location():
    event = CharacterDied(character_id="abc123", location_id="old_ruins")
    assert format_event(event) == "abc123 died at old_ruins."


def test_history_reflects_the_time_at_the_moment_the_event_fired():
    campaign = debug_cli.new_ravenhollow_campaign(seed=1)
    campaign.events.emit(QuestStarted(quest_id="test_quest"))
    assert campaign.history[-1].startswith(f"Day {campaign.current_time.day}, "
                                            f"{campaign.current_time.hour:02d}:{campaign.current_time.minute:02d}")
