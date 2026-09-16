"""Tests for Character's Phase 1 derived-stat math (Sprint 1.1-1.4):
ability scores, skills, base attack bonus/saves, armor class, attack
bonus, and equipment-driven encumbrance/armor-check-penalty wiring.
"""
import pytest

from ethereal_dnd.characters.character import Character, MissingAbilityScoreError, UntrainedSkillError
from ethereal_dnd.characters.class_definition import load_classes
from ethereal_dnd.characters.multiclass import add_class_level
from ethereal_dnd.characters.race import load_races
from ethereal_dnd.characters.skills import load_skills
from ethereal_dnd.core.rng import RNGService
from ethereal_dnd.items.item import ItemInstance, load_items, item_registry

load_races()
load_classes()
load_skills()
load_items()


def _fighter(**ability_overrides):
    scores = {"STR": 16, "DEX": 14, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8}
    scores.update(ability_overrides)
    character = Character(name="Sky", race_id="human", ability_scores=scores)
    add_class_level(character, "fighter")
    character.max_hp = 12
    return character


def test_get_ability_score_raises_if_unset():
    character = Character()
    with pytest.raises(MissingAbilityScoreError):
        character.get_ability_score("STR")


def test_ability_modifier_reads_through_get_ability_score():
    character = _fighter()
    assert character.ability_modifier("STR") == 3
    assert character.ability_modifier("CHA") == -1


def test_size_modifier_defaults_to_medium_with_no_race():
    assert Character().size_modifier() == 0


def test_size_modifier_for_small_race():
    character = Character(race_id="halfling")
    assert character.size_category() == "Small"
    assert character.size_modifier() == 1


def test_skill_bonus_combines_ranks_and_ability_modifier():
    character = _fighter()
    character.skill_ranks["jump"] = 4
    assert character.skill_bonus("jump") == 4 + 3  # ranks + STR mod


def test_skill_bonus_raises_untrained_for_trained_only_skill():
    character = _fighter()
    with pytest.raises(UntrainedSkillError):
        character.skill_bonus("spellcraft")


def test_skill_bonus_allows_trained_only_skill_with_ranks():
    character = _fighter()
    character.skill_ranks["spellcraft"] = 2
    assert character.skill_bonus("spellcraft") == 2 + character.ability_modifier("INT")


def test_base_attack_bonus_single_class():
    character = _fighter()
    add_class_level(character, "fighter")  # now level 2
    assert character.level == 2
    assert character.base_attack_bonus() == 2  # good progression: BAB == level


def test_base_attack_bonus_multiclass_sums_each_class_progression():
    character = _fighter()  # fighter 1 (good, BAB 1)
    add_class_level(character, "wizard")  # + wizard 1 (poor, BAB 0)
    assert character.level == 2
    assert character.base_attack_bonus() == 1 + 0


def test_saving_throws_use_correct_class_progression_and_ability():
    character = _fighter()
    # Fighter: Fort good (2 + CON mod), Ref poor (0 + DEX mod), Will poor (0 + WIS mod)
    assert character.fortitude_save() == 2 + character.ability_modifier("CON")
    assert character.reflex_save() == 0 + character.ability_modifier("DEX")
    assert character.will_save() == 0 + character.ability_modifier("WIS")


def test_armor_class_with_no_equipment():
    character = _fighter()
    assert character.armor_class() == 10 + character.ability_modifier("DEX")


def _equip(character, slot, item_id):
    instance = ItemInstance(definition_id=item_id)
    character.inventory.add(instance)
    character.equipment[slot] = instance.id
    return instance


def test_armor_class_applies_armor_bonus_and_max_dex_cap():
    character = _fighter(DEX=20)  # +5 Dex mod, but chain shirt caps at +4
    _equip(character, "armor", "chain_shirt")
    assert character.armor_class() == 10 + 4 + 4 + 0  # armor 4, capped dex 4, size 0


def test_armor_class_stacks_shield():
    character = _fighter()
    _equip(character, "armor", "leather")
    _equip(character, "shield", "heavy_steel_shield")
    assert character.armor_class() == 10 + 2 + 2 + character.ability_modifier("DEX")


def test_equipped_item_definition_raises_on_dangling_reference():
    character = _fighter()
    character.equipment["armor"] = "does-not-exist"
    with pytest.raises(KeyError):
        character.equipped_item_definition("armor")


def test_armor_check_penalty_applies_to_flagged_skills():
    character = _fighter()
    character.skill_ranks["jump"] = 0
    _equip(character, "armor", "chain_shirt")  # -2 ACP
    assert character.skill_bonus("jump") == 0 + character.ability_modifier("STR") - 2


def test_swim_skill_doubles_armor_check_penalty():
    character = _fighter()
    _equip(character, "armor", "chain_shirt")  # -2 ACP
    assert character.skill_bonus("swim") == character.ability_modifier("STR") - 4


def test_attack_bonus_uses_strength_for_melee_weapon():
    character = _fighter()
    _equip(character, "weapon", "longsword")
    assert character.attack_bonus() == character.base_attack_bonus() + character.ability_modifier("STR")


def test_attack_bonus_uses_dexterity_for_ranged_weapon():
    character = _fighter()
    _equip(character, "weapon", "light_crossbow")
    assert character.attack_bonus() == character.base_attack_bonus() + character.ability_modifier("DEX")


def test_melee_damage_rolls_weapon_dice_plus_strength():
    character = _fighter()
    rng = RNGService(3)
    detail = character.melee_damage("dagger", rng)
    assert detail["total"] == sum(detail["kept"]) + character.ability_modifier("STR")


def test_initiative_is_dex_modifier():
    character = _fighter()
    assert character.initiative() == character.ability_modifier("DEX")


def test_die_records_time_and_location():
    from ethereal_dnd.core.time import CampaignTime

    character = _fighter()
    when = CampaignTime(day=3, hour=14, minute=0)
    character.die(when, location_id="old_mine")
    assert character.status == "dead"
    assert character.time_of_death == when
    assert character.time_of_death is not when  # a copy, not the live shared clock
    assert character.location_of_death == "old_mine"
