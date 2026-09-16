"""Tests for Sprint 2.6's resurrection flow (design doc Section 23),
sourced verbatim from the *Raise Dead* spell.
"""
import pytest

from ethereal_dnd.characters import death, resurrection
from ethereal_dnd.cli import debug_cli


def _make_character(**overrides):
    scores = {"STR": 16, "DEX": 14, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8}
    scores.update(overrides.pop("ability_scores", {}))
    character = debug_cli.create_test_character("Sky", "fighter", scores, max_hp=overrides.pop("max_hp", 13))
    return character


def test_is_eligible_false_for_a_living_character():
    campaign = debug_cli.new_campaign(seed=1)
    character = _make_character()
    assert resurrection.is_eligible(character, campaign.current_time) is False


def test_is_eligible_within_the_day_per_caster_level_window():
    campaign = debug_cli.new_campaign(seed=1)
    character = _make_character()
    death.apply_damage(character, 9999, campaign.current_time, campaign.events)
    campaign.current_time.advance(hours=24 * 9)  # exactly 9 days, caster level 9
    assert resurrection.is_eligible(character, campaign.current_time, caster_level=9) is True
    campaign.current_time.advance(hours=24)  # now 10 days
    assert resurrection.is_eligible(character, campaign.current_time, caster_level=9) is False


def test_resurrect_costs_the_real_5000_gp_diamond_price():
    campaign = debug_cli.new_campaign(seed=1)
    character = _make_character()
    character.gold = 5000
    campaign.party.add(character)
    death.apply_damage(character, 9999, campaign.current_time, campaign.events)

    resurrection.resurrect(character, campaign.party, campaign.current_time, campaign.events)

    assert character.status == "alive"
    assert character.gold == 0


def test_resurrect_raises_if_party_cannot_afford_it():
    campaign = debug_cli.new_campaign(seed=1)
    character = _make_character()
    character.gold = 100
    campaign.party.add(character)
    death.apply_damage(character, 9999, campaign.current_time, campaign.events)

    with pytest.raises(resurrection.ResurrectionError):
        resurrection.resurrect(character, campaign.party, campaign.current_time, campaign.events)
    assert character.status == "dead"  # no partial state change on failure


def test_resurrect_uses_the_whole_partys_gold_including_the_corpses_own():
    campaign = debug_cli.new_campaign(seed=1)
    dead = _make_character()
    dead.gold = 3000
    ally = debug_cli.create_test_character(
        "Ally", "cleric", {"STR": 10, "DEX": 10, "CON": 12, "INT": 10, "WIS": 14, "CHA": 10}, max_hp=8,
    )
    ally.gold = 2000
    campaign.party.add(dead)
    campaign.party.add(ally)
    death.apply_damage(dead, 9999, campaign.current_time, campaign.events)

    resurrection.resurrect(dead, campaign.party, campaign.current_time, campaign.events)

    assert dead.gold + ally.gold == 0


def test_first_level_character_loses_constitution_instead_of_a_level():
    campaign = debug_cli.new_campaign(seed=1)
    character = _make_character(ability_scores={"CON": 14})
    character.gold = 5000
    campaign.party.add(character)
    death.apply_damage(character, 9999, campaign.current_time, campaign.events)
    level_before = character.level

    resurrection.resurrect(character, campaign.party, campaign.current_time, campaign.events)

    assert character.level == level_before
    assert character.ability_scores["CON"] == 12


def test_resurrection_refused_if_constitution_would_drop_to_zero():
    campaign = debug_cli.new_campaign(seed=1)
    character = _make_character(ability_scores={"CON": 2})
    character.gold = 5000
    campaign.party.add(character)
    death.apply_damage(character, 9999, campaign.current_time, campaign.events)

    with pytest.raises(resurrection.ResurrectionError):
        resurrection.resurrect(character, campaign.party, campaign.current_time, campaign.events)


def test_multiclass_character_loses_a_level_from_their_heaviest_class():
    from ethereal_dnd.characters.multiclass import add_class_level

    campaign = debug_cli.new_campaign(seed=1)
    character = _make_character()
    add_class_level(character, "fighter")  # fighter 2 now
    add_class_level(character, "rogue")  # + rogue 1
    character.gold = 5000
    campaign.party.add(character)
    death.apply_damage(character, 9999, campaign.current_time, campaign.events)

    resurrection.resurrect(character, campaign.party, campaign.current_time, campaign.events)

    levels = {cl.class_id: cl.levels for cl in character.class_levels}
    assert levels["fighter"] == 1  # lost a level from the heaviest class
    assert levels["rogue"] == 1


def test_resurrect_returns_with_hp_equal_to_hit_dice_not_full_health():
    campaign = debug_cli.new_campaign(seed=1)
    character = _make_character()
    character.gold = 5000
    campaign.party.add(character)
    death.apply_damage(character, 9999, campaign.current_time, campaign.events)

    resurrection.resurrect(character, campaign.party, campaign.current_time, campaign.events)

    assert character.max_hp - character.damage == character.level


def test_resurrect_emits_character_resurrected_event():
    campaign = debug_cli.new_campaign(seed=1)
    character = _make_character()
    character.gold = 5000
    campaign.party.add(character)
    death.apply_damage(character, 9999, campaign.current_time, campaign.events)
    resurrected = []
    campaign.events.subscribe("CharacterResurrected", lambda e: resurrected.append(e))

    resurrection.resurrect(character, campaign.party, campaign.current_time, campaign.events)

    assert len(resurrected) == 1
    assert resurrected[0].character_id == character.id
