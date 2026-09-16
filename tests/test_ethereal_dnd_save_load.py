"""Tests for Sprint 2.6's save/load (design doc Section 44): a full
Campaign round trip through JSON, covering every model touched by
Phases 0-2.
"""
import os

from ethereal_dnd.campaign.save_manager import campaign_from_dict, campaign_to_dict, load_campaign, save_campaign
from ethereal_dnd.cli import debug_cli
from ethereal_dnd.core.events import CommittedEvilAct
from ethereal_dnd.world.travel import travel


def _rich_campaign(seed=99):
    campaign = debug_cli.new_ravenhollow_campaign(name="Round Trip Test", seed=seed)
    sky = debug_cli.create_test_character(
        "Sky", "paladin", {"STR": 16, "DEX": 12, "CON": 14, "INT": 10, "WIS": 12, "CHA": 16},
        race_id="human", weapon_id="longsword", armor_id="chain_shirt", max_hp=13,
    )
    sky.alignment.law_chaos = 60
    sky.alignment.good_evil = 60
    sky.gold = 42
    campaign.party.add(sky)
    debug_cli.accept_quest(campaign, "wolves_of_blackwood")
    campaign.events.emit(CommittedEvilAct(character_id=sky.id, description="murder"))
    travel(campaign, "farmstead")
    return campaign, sky


def test_round_trip_preserves_character_state(tmp_path):
    campaign, sky = _rich_campaign()
    save_campaign(campaign, saves_root=str(tmp_path))
    loaded = load_campaign(campaign.id, saves_root=str(tmp_path))
    loaded_sky = loaded.party.members[0]

    assert loaded_sky.name == sky.name
    assert loaded_sky.gold == sky.gold
    assert loaded_sky.equipment == sky.equipment
    assert loaded_sky.alignment.derived_alignment() == sky.alignment.derived_alignment()
    assert loaded_sky.inventory.items[0].definition_id == sky.inventory.items[0].definition_id


def test_round_trip_preserves_divine_standing():
    campaign, sky = _rich_campaign()
    data = campaign_to_dict(campaign)
    loaded = campaign_from_dict(data)
    loaded_sky = loaded.party.members[0]

    assert loaded_sky.divine_standing.fallen is True
    assert loaded_sky.divine_standing.powers_revoked == ["paladin"]
    assert loaded_sky.divine_standing.fallen_reason == sky.divine_standing.fallen_reason


def test_round_trip_preserves_world_and_npcs():
    campaign, _ = _rich_campaign()
    loaded = campaign_from_dict(campaign_to_dict(campaign))

    assert set(loaded.world.locations) == set(campaign.world.locations)
    assert len(loaded.world.routes) == len(campaign.world.routes)
    assert set(loaded.world.npcs) == set(campaign.world.npcs)
    assert loaded.current_location_id == campaign.current_location_id
    assert loaded.world.locations["farmstead"].discovered is True


def test_round_trip_preserves_quest_state():
    campaign, _ = _rich_campaign()
    loaded = campaign_from_dict(campaign_to_dict(campaign))
    assert loaded.state.quest_state["wolves_of_blackwood"].state == "active"
    assert loaded.state.quest_state["wolves_of_blackwood"].title == "Wolves of Blackwood"


def test_round_trip_preserves_time_and_history():
    campaign, _ = _rich_campaign()
    loaded = campaign_from_dict(campaign_to_dict(campaign))
    assert str(loaded.current_time) == str(campaign.current_time)
    assert loaded.history == campaign.history
    assert loaded.history  # not empty - travel/quest events were logged


def test_loaded_campaign_gets_a_fresh_rng_and_event_bus():
    campaign, _ = _rich_campaign()
    loaded = campaign_from_dict(campaign_to_dict(campaign))
    assert loaded.rng() is not campaign.rng()
    assert loaded.events is not campaign.events
    assert loaded.events._subscribers == {}  # nothing re-subscribed yet - caller's job


def test_save_campaign_writes_to_the_expected_path(tmp_path):
    campaign, _ = _rich_campaign()
    path = save_campaign(campaign, saves_root=str(tmp_path))
    assert path == os.path.join(str(tmp_path), campaign.id, "campaign.json")
    assert os.path.isfile(path)


def test_reattaching_compliance_after_load_makes_the_pipeline_live_again(tmp_path):
    """A freshly loaded Campaign's event bus starts empty (save_manager's
    documented limitation) - re-attaching (what debug_cli.load_saved_campaign()
    does automatically) must make it live again, not silently inert."""
    campaign, sky = _rich_campaign()
    save_campaign(campaign, saves_root=str(tmp_path))
    loaded = load_campaign(campaign.id, saves_root=str(tmp_path))

    from ethereal_dnd.divine.setup import attach_alignment_and_compliance
    from ethereal_dnd.quests.quest_hooks import attach_quest_hooks

    attach_alignment_and_compliance(loaded)
    attach_quest_hooks(loaded)

    loaded_sky = loaded.party.members[0]
    fresh_character = debug_cli.create_test_character(
        "Newcomer", "paladin", {"STR": 14, "DEX": 12, "CON": 14, "INT": 10, "WIS": 12, "CHA": 14}, max_hp=10,
    )
    fresh_character.alignment.law_chaos = 60
    fresh_character.alignment.good_evil = 60
    loaded.party.add(fresh_character)

    assert fresh_character.can_use_class_powers("paladin") is True
    loaded.events.emit(CommittedEvilAct(character_id=fresh_character.id, description="a fresh crime"))
    assert fresh_character.can_use_class_powers("paladin") is False
    assert loaded_sky.divine_standing.fallen is True  # the saved state also survived intact
