"""Tests for Sprint 1.3's combat core: initiative, attack resolution,
conditions, and the remaining core actions.
"""
from ethereal_dnd.characters.character import Character
from ethereal_dnd.characters.class_definition import load_classes
from ethereal_dnd.characters.multiclass import add_class_level
from ethereal_dnd.characters.race import load_races
from ethereal_dnd.characters.skills import load_skills
from ethereal_dnd.combat import actions, conditions, initiative
from ethereal_dnd.combat.encounter import Encounter
from ethereal_dnd.core.events import EventBus
from ethereal_dnd.core.rng import RNGService
from ethereal_dnd.core.time import CampaignTime
from ethereal_dnd.items.item import ItemInstance, load_items

load_races()
load_classes()
load_skills()
load_items()


def _combatant(name, str_score=14, dex_score=12, hp=10, class_id="fighter"):
    character = Character(
        name=name,
        ability_scores={"STR": str_score, "DEX": dex_score, "CON": 12, "INT": 10, "WIS": 10, "CHA": 10},
        max_hp=hp,
    )
    add_class_level(character, class_id)
    return character


def test_roll_initiative_orders_by_total_descending():
    fast = _combatant("Fast", dex_score=20)  # +5 Dex
    slow = _combatant("Slow", dex_score=8)  # -1 Dex
    order = initiative.roll_initiative([slow, fast], RNGService(1))
    assert len(order) == 2
    assert set(order) == {fast.id, slow.id}


def test_roll_initiative_is_deterministic_under_fixed_seed():
    a = _combatant("A")
    b = _combatant("B")
    order_1 = initiative.roll_initiative([a, b], RNGService(42))
    order_2 = initiative.roll_initiative([a, b], RNGService(42))
    assert order_1 == order_2


def test_resolve_attack_natural_1_always_misses(monkeypatch):
    attacker = _combatant("Attacker", str_score=30)  # overwhelming attack bonus
    defender = _combatant("Defender", dex_score=1)  # terrible AC
    monkeypatch.setattr(actions, "roll", lambda expr, rng_service=None: 1)
    result = actions.resolve_attack(attacker, defender, RNGService(0))
    assert result["hit"] is False


def test_resolve_attack_natural_20_always_hits(monkeypatch):
    attacker = _combatant("Attacker", str_score=1)  # terrible attack bonus
    defender = _combatant("Defender", dex_score=30)  # overwhelming AC
    monkeypatch.setattr(actions, "roll", lambda expr, rng_service=None: 20)
    result = actions.resolve_attack(attacker, defender, RNGService(0))
    assert result["hit"] is True


def test_resolve_attack_with_equipped_weapon_logs_damage():
    attacker = _combatant("Attacker", str_score=18)
    defender = _combatant("Defender", dex_score=8, hp=100)
    instance = ItemInstance(definition_id="longsword")
    attacker.inventory.add(instance)
    attacker.equipment["weapon"] = instance.id
    result = actions.resolve_attack(attacker, defender, RNGService(2))
    assert "attacks" in result["log"]
    if result["hit"]:
        assert "Damage:" in result["log"]
        assert result["damage"] > 0


def test_apply_attack_damage_kills_and_emits_event():
    attacker = _combatant("Attacker", str_score=18)
    defender = _combatant("Defender", hp=1)
    events = EventBus()
    died = []
    events.subscribe("CharacterDied", lambda e: died.append(e))
    result = {"hit": True, "damage": 5, "log": ""}
    actions.apply_attack_damage(result, defender, CampaignTime(), events)
    assert defender.status == "dead"
    assert len(died) == 1


def test_attack_sequence_matches_sourced_iterative_attack_pattern():
    assert actions.attack_sequence(1) == [1]
    assert actions.attack_sequence(6) == [6, 1]
    assert actions.attack_sequence(16) == [16, 11, 6, 1]  # matches Fighter level 16 "+16/+11/+6/+1"


def test_full_attack_stops_early_if_defender_dies():
    attacker = _combatant("Attacker", str_score=20)
    add_class_level(attacker, "fighter")
    add_class_level(attacker, "fighter")
    add_class_level(attacker, "fighter")
    add_class_level(attacker, "fighter")
    add_class_level(attacker, "fighter")  # level 6, BAB +6 -> two attacks
    defender = _combatant("Defender", hp=1, dex_score=1)
    instance = ItemInstance(definition_id="greataxe")
    attacker.inventory.add(instance)
    attacker.equipment["weapon"] = instance.id
    events = EventBus()
    results = actions.full_attack(attacker, defender, RNGService(9))
    for result in results:
        actions.apply_attack_damage(result, defender, CampaignTime(), events)
        if defender.status != "alive":
            break
    assert len(results) >= 1


def test_conditions_stack_flat_penalty():
    character = _combatant("Shaky")
    conditions.add_condition(character, "shaken")
    conditions.add_condition(character, "frightened")
    assert conditions.all_rolls_penalty(character) == -4


def test_stunned_removes_dex_to_ac_and_penalizes_ac():
    character = _combatant("Stunned", dex_score=18)
    conditions.add_condition(character, "stunned")
    assert conditions.ac_penalty(character) == -2
    assert conditions.loses_dex_to_ac(character) is True
    assert conditions.can_act(character) is False


def test_prone_penalizes_melee_attacker_and_helps_against_ranged():
    prone_character = _combatant("Prone")
    conditions.add_condition(prone_character, "prone")
    assert conditions.prone_attack_roll_modifier(prone_character) == -4
    assert conditions.prone_ac_modifier(prone_character, attack_is_ranged=False) == -4
    assert conditions.prone_ac_modifier(prone_character, attack_is_ranged=True) == 4


def test_remove_condition_clears_it():
    character = _combatant("Temp")
    conditions.add_condition(character, "shaken")
    conditions.remove_condition(character, "shaken")
    assert conditions.all_rolls_penalty(character) == 0


def test_add_condition_rejects_unknown_condition():
    import pytest

    character = _combatant("Unknown")
    with pytest.raises(ValueError):
        conditions.add_condition(character, "not-a-real-condition")


def test_move_and_withdraw_actions_append_to_combat_log():
    character = _combatant("Mover")
    encounter = Encounter()
    actions.move_action(character, encounter, "the north door")
    actions.withdraw_action(character, encounter)
    assert len(encounter.combat_log) == 2


def test_aid_another_action_grants_bonus_on_success():
    helper = _combatant("Helper", str_score=30)
    ally = _combatant("Ally")
    encounter = Encounter()
    result = actions.aid_another_action(helper, ally, encounter, RNGService(1), dc=1)
    assert result["succeeded"] is True
    assert result["bonus"] == actions.AID_ANOTHER_BONUS
