"""Tests for ethereal_dnd's dev CLI functions - proves the Phase 0
scaffolding boots end-to-end: create a campaign, inspect it, advance
time, roll a check. These are the same functions ethereal_dnd_widget.py
calls from the GUI.
"""
from ethereal_dnd.characters.character import Character
from ethereal_dnd.cli import debug_cli
from ethereal_dnd.world.location import Location


def test_new_campaign_has_empty_party_and_world():
    campaign = debug_cli.new_campaign(seed=1)
    assert campaign.party.members == []
    assert campaign.world.locations == {}


def test_show_party_reports_empty_party():
    campaign = debug_cli.new_campaign(seed=1)
    assert "empty" in debug_cli.show_party(campaign).lower()


def test_show_party_reports_member_summary():
    campaign = debug_cli.new_campaign(seed=1)
    campaign.party.add(Character(name="Sky", max_hp=10))
    output = debug_cli.show_party(campaign)
    assert "Sky" in output
    assert "10/10" in output


def test_show_world_reports_locations():
    campaign = debug_cli.new_campaign(seed=1)
    campaign.world.add_location(Location(id="ravenhollow", name="Ravenhollow"))
    assert "Ravenhollow" in debug_cli.show_world(campaign)


def test_advance_time_updates_and_returns_current_time():
    campaign = debug_cli.new_campaign(seed=1)
    before = str(campaign.current_time)
    result = debug_cli.advance_time(campaign, hours=2)
    assert result != before
    assert result == str(campaign.current_time)


def test_roll_check_is_deterministic_per_campaign_seed():
    campaign_a = debug_cli.new_campaign(seed=99)
    campaign_b = debug_cli.new_campaign(seed=99)
    assert debug_cli.roll_check(campaign_a, "1d20") == debug_cli.roll_check(campaign_b, "1d20")
