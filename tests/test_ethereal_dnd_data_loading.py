"""Tests for the Sprint 1.1/1.2/1.4/1.5 data loaders (races, classes,
skills, items, spells) - idempotency and a few spot-checks against the
sourced SRD values, not full data dumps.
"""
from ethereal_dnd.characters.class_definition import ClassDefinition, load_classes
from ethereal_dnd.characters.race import RaceDefinition, load_races
from ethereal_dnd.characters.skills import SkillDefinition, load_skills
from ethereal_dnd.core.registry import Registry
from ethereal_dnd.items.item import load_items
from ethereal_dnd.magic.spell import load_spells


def test_load_races_is_idempotent_and_complete():
    registry = Registry("race")
    load_races(target_registry=registry)
    load_races(target_registry=registry)
    assert len(registry) == 7
    assert {r.id for r in registry.all()} == {
        "human", "dwarf", "elf", "gnome", "half-elf", "half-orc", "halfling",
    }


def test_dwarf_race_data_matches_sourced_ability_modifiers():
    registry = Registry("race")
    load_races(target_registry=registry)
    dwarf = registry.get("dwarf")
    assert dwarf.ability_modifiers == {"CON": 2, "CHA": -2}
    assert dwarf.favored_class == "Fighter"


def test_gnome_and_halfling_races_are_small():
    registry = Registry("race")
    load_races(target_registry=registry)
    assert registry.get("gnome").size == "Small"
    assert registry.get("halfling").size == "Small"
    assert registry.get("human").size == "Medium"


def test_load_classes_is_idempotent_and_complete():
    registry = Registry("class")
    load_classes(target_registry=registry)
    load_classes(target_registry=registry)
    assert len(registry) == 15
    assert {c.id for c in registry.all()} == {
        "barbarian", "fighter", "rogue", "cleric", "wizard", "paladin", "druid", "monk",
        "adept", "aristocrat", "commoner", "expert", "warrior",  # NPC classes
        "animal", "undead",  # monster Hit Dice types
    }


def test_wizard_class_data_matches_sourced_progressions():
    registry = Registry("class")
    load_classes(target_registry=registry)
    wizard = registry.get("wizard")
    assert wizard.hit_die == 4
    assert wizard.base_attack_progression == "poor"
    assert wizard.save_progression == {"fortitude": "poor", "reflex": "poor", "will": "good"}
    assert wizard.armor_proficiencies == []


def test_rogue_class_data_has_good_reflex_only():
    registry = Registry("class")
    load_classes(target_registry=registry)
    rogue = registry.get("rogue")
    assert rogue.save_progression == {"fortitude": "poor", "reflex": "good", "will": "poor"}
    assert "short_sword" in rogue.weapon_proficiencies


def test_load_skills_is_idempotent_and_complete():
    registry = Registry("skill")
    load_skills(target_registry=registry)
    load_skills(target_registry=registry)
    assert len(registry) == 36


def test_speak_language_skill_has_no_key_ability():
    registry = Registry("skill")
    load_skills(target_registry=registry)
    assert registry.get("speak_language").key_ability is None
    assert registry.get("speak_language").trained_only is True


def test_swim_skill_is_armor_check_penalized_and_str_based():
    registry = Registry("skill")
    load_skills(target_registry=registry)
    swim = registry.get("swim")
    assert swim.key_ability == "STR"
    assert swim.armor_check_penalty is True


def test_load_items_is_idempotent_and_covers_weapons_and_armor():
    registry = Registry("item")
    load_items(target_registry=registry)
    load_items(target_registry=registry)
    assert len(registry) == 23  # 12 weapons + 1 natural weapon (wolf_bite) + 10 armor/shields
    longsword = registry.get("longsword")
    assert longsword.properties["damage_dice"] == "1d8"
    assert longsword.equipment_slot == "weapon"
    full_plate = registry.get("full_plate")
    assert full_plate.properties["armor_bonus"] == 8
    assert full_plate.equipment_slot == "armor"


def test_load_spells_is_idempotent_and_covers_starting_list():
    registry = Registry("spell")
    load_spells(target_registry=registry)
    load_spells(target_registry=registry)
    assert len(registry) == 4
    assert {s.id for s in registry.all()} == {
        "magic_missile", "cure_light_wounds", "bless", "detect_magic",
    }
