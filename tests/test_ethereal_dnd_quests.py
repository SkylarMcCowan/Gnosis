"""Tests for Sprint 2.4: the quest state machine, hooks, and the two
real Ravenhollow quests.
"""
import pytest

from ethereal_dnd.cli import debug_cli
from ethereal_dnd.core.events import LocationDiscovered
from ethereal_dnd.quests.quest_hooks import attach_quest_hooks, register_locked_quest
from ethereal_dnd.quests.quest_manager import QuestError, complete_objective, fail_quest, start_quest


def _campaign_with_party():
    campaign = debug_cli.new_ravenhollow_campaign(seed=1)
    sky = debug_cli.create_test_character(
        "Sky", "fighter", {"STR": 16, "DEX": 14, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8}, max_hp=13,
    )
    campaign.party.add(sky)
    return campaign, sky


def test_start_quest_loads_the_real_template():
    campaign, _ = _campaign_with_party()
    quest = start_quest(campaign, "wolves_of_blackwood")
    assert quest.title == "Wolves of Blackwood"
    assert quest.state == "active"
    assert len(quest.objectives) == 1


def test_start_quest_twice_raises():
    campaign, _ = _campaign_with_party()
    start_quest(campaign, "wolves_of_blackwood")
    with pytest.raises(QuestError):
        start_quest(campaign, "wolves_of_blackwood")


def test_completing_all_objectives_completes_the_quest_and_grants_rewards():
    campaign, sky = _campaign_with_party()
    start_quest(campaign, "wolves_of_blackwood")
    complete_objective(campaign, "wolves_of_blackwood", 0)
    quest = campaign.state.quest_state["wolves_of_blackwood"]
    assert quest.state == "completed"
    assert sky.gold == 50
    assert sky.experience == 100


def test_multi_objective_quest_only_completes_when_all_are_done():
    campaign, _ = _campaign_with_party()
    start_quest(campaign, "missing_miners")
    complete_objective(campaign, "missing_miners", 0)
    quest = campaign.state.quest_state["missing_miners"]
    assert quest.state == "active"
    complete_objective(campaign, "missing_miners", 1)
    assert campaign.state.quest_state["missing_miners"].state == "completed"


def test_reward_gold_splits_evenly_across_the_living_party():
    campaign, sky = _campaign_with_party()
    rowan = debug_cli.create_test_character(
        "Rowan", "cleric", {"STR": 10, "DEX": 10, "CON": 12, "INT": 10, "WIS": 14, "CHA": 10}, max_hp=8,
    )
    campaign.party.add(rowan)
    start_quest(campaign, "wolves_of_blackwood")
    complete_objective(campaign, "wolves_of_blackwood", 0)
    assert sky.gold + rowan.gold == 50
    assert sky.gold == rowan.gold == 25


def test_fail_quest_sets_state_and_emits_event():
    campaign, _ = _campaign_with_party()
    start_quest(campaign, "missing_miners")
    failed = []
    campaign.events.subscribe("QuestFailed", lambda e: failed.append(e))
    fail_quest(campaign, "missing_miners", "the mayor died")
    assert campaign.state.quest_state["missing_miners"].state == "failed"
    assert failed[0].reason == "the mayor died"


def test_npc_dying_fails_a_quest_that_requires_them_alive():
    from ethereal_dnd.characters import death

    campaign, _ = _campaign_with_party()
    start_quest(campaign, "missing_miners")  # requires npc_alive:mayor_voss
    mayor = campaign.world.npcs["mayor_voss"].character
    death.apply_damage(mayor, 9999, campaign.current_time, campaign.events)
    assert campaign.state.quest_state["missing_miners"].state == "failed"


def test_npc_dying_does_not_fail_unrelated_quests():
    from ethereal_dnd.characters import death

    campaign, _ = _campaign_with_party()
    start_quest(campaign, "wolves_of_blackwood")  # no requirements
    tam = campaign.world.npcs["tam_trader"].character
    death.apply_damage(tam, 9999, campaign.current_time, campaign.events)
    assert campaign.state.quest_state["wolves_of_blackwood"].state == "active"


def test_pc_or_monster_death_does_not_touch_quest_state():
    campaign, sky = _campaign_with_party()
    from ethereal_dnd.characters import death

    start_quest(campaign, "missing_miners")
    death.apply_damage(sky, 9999, campaign.current_time, campaign.events)  # PC, not an NPC
    assert campaign.state.quest_state["missing_miners"].state == "active"


def test_location_discovery_unlocks_a_registered_locked_quest():
    campaign, _ = _campaign_with_party()
    register_locked_quest(campaign, "wolves_of_blackwood", ["location_discovered:old_ruins"])
    assert "wolves_of_blackwood" not in campaign.state.quest_state

    campaign.events.emit(LocationDiscovered(location_id="old_ruins"))

    assert campaign.state.quest_state["wolves_of_blackwood"].state == "active"


def test_attach_quest_hooks_is_safe_to_call_alongside_new_ravenhollow_campaign():
    # new_ravenhollow_campaign() already calls attach_quest_hooks() once;
    # calling it again should not raise or double-fail quests.
    campaign, _ = _campaign_with_party()
    attach_quest_hooks(campaign)
    start_quest(campaign, "wolves_of_blackwood")
    complete_objective(campaign, "wolves_of_blackwood", 0)
    assert campaign.state.quest_state["wolves_of_blackwood"].state == "completed"
