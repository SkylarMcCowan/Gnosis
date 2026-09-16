"""Tests for Sprint 1.6: experience/leveling, death, and rest.
"""
import pytest

from ethereal_dnd.characters import death
from ethereal_dnd.characters.character import Character
from ethereal_dnd.characters.class_definition import load_classes
from ethereal_dnd.characters.leveling import award_experience, level_for_xp, xp_required_for_level
from ethereal_dnd.characters.multiclass import add_class_level
from ethereal_dnd.characters.party import Party
from ethereal_dnd.campaign.rest import rest
from ethereal_dnd.core.events import EventBus
from ethereal_dnd.core.time import CampaignTime

load_classes()


@pytest.mark.parametrize(
    "level,expected_xp",
    [(1, 0), (2, 1000), (3, 3000), (4, 6000), (5, 10000), (20, 190000)],
)
def test_xp_required_for_level_matches_standard_table(level, expected_xp):
    assert xp_required_for_level(level) == expected_xp


def test_level_for_xp_is_the_highest_qualifying_level():
    assert level_for_xp(0) == 1
    assert level_for_xp(999) == 1
    assert level_for_xp(1000) == 2
    assert level_for_xp(2999) == 2
    assert level_for_xp(3000) == 3


def test_award_experience_levels_up_and_emits_once_per_level():
    character = Character(name="Sky")
    add_class_level(character, "fighter")
    events = EventBus()
    leveled = []
    events.subscribe("CharacterLeveled", lambda e: leveled.append(e))

    award_experience(character, 3000, "fighter", events)  # 0 -> 3000 XP = level 1 -> 3

    assert character.level == 3
    assert len(leveled) == 2
    assert [e.new_level for e in leveled] == [2, 3]


def test_award_experience_no_event_if_no_level_gained():
    character = Character(name="Sky")
    add_class_level(character, "fighter")
    events = EventBus()
    leveled = []
    events.subscribe("CharacterLeveled", lambda e: leveled.append(e))

    award_experience(character, 50, "fighter", events)

    assert character.level == 1
    assert leveled == []


def test_apply_damage_kills_at_zero_hp_and_emits_once():
    character = Character(name="Dying", max_hp=10, damage=9)
    events = EventBus()
    died = []
    events.subscribe("CharacterDied", lambda e: died.append(e))

    death.apply_damage(character, 5, CampaignTime(day=2, hour=6), events, location_id="ravenhollow")
    death.apply_damage(character, 5, CampaignTime(day=2, hour=6), events, location_id="ravenhollow")  # already dead

    assert character.status == "dead"
    assert character.location_of_death == "ravenhollow"
    assert len(died) == 1  # not re-triggered on a corpse


def test_apply_damage_survivable_hit_does_not_kill():
    character = Character(name="Tough", max_hp=20, damage=0)
    events = EventBus()
    death.apply_damage(character, 5, CampaignTime(), events)
    assert character.status == "alive"
    assert character.damage == 5


def test_rest_heals_one_hp_per_level_and_advances_time():
    character = Character(name="Sky", max_hp=20, damage=15)
    add_class_level(character, "fighter")
    add_class_level(character, "fighter")
    add_class_level(character, "fighter")  # level 3
    party = Party()
    party.add(character)
    campaign_time = CampaignTime(day=1, hour=20, minute=0)
    events = EventBus()

    rest(party, campaign_time, events)

    assert character.damage == 12  # 15 - (1 hp/level * 3)
    assert (campaign_time.day, campaign_time.hour) == (2, 4)


def test_complete_bed_rest_heals_double():
    character = Character(name="Sky", max_hp=20, damage=15)
    add_class_level(character, "fighter")
    add_class_level(character, "fighter")
    add_class_level(character, "fighter")
    party = Party()
    party.add(character)
    campaign_time = CampaignTime(day=1, hour=8, minute=0)
    events = EventBus()

    rest(party, campaign_time, events, complete_bed_rest=True)

    assert character.damage == 9  # 15 - (2 hp/level * 3)
    assert campaign_time.day == 2  # advanced a full 24 hours


def test_rest_clears_conditions_and_skips_dead_members():
    from ethereal_dnd.combat import conditions

    alive = Character(name="Alive", max_hp=10, damage=0)
    add_class_level(alive, "fighter")
    conditions.add_condition(alive, "shaken")
    dead = Character(name="Dead", max_hp=10, damage=10, status="dead")
    party = Party()
    party.add(alive)
    party.add(dead)
    events = EventBus()

    rest(party, CampaignTime(), events)

    assert alive.conditions == []
    assert dead.damage == 10  # untouched


def test_rest_emits_started_and_completed_events():
    character = Character(name="Sky", max_hp=10, damage=0)
    add_class_level(character, "fighter")
    party = Party()
    party.add(character)
    events = EventBus()
    seen = []
    events.subscribe("RestStarted", lambda e: seen.append("started"))
    events.subscribe("RestCompleted", lambda e: seen.append("completed"))

    rest(party, CampaignTime(), events)

    assert seen == ["started", "completed"]
