"""Builds a fresh Character from a data/monsters/*.json template
(design doc Section 8's definition/instance split - the JSON is the
definition, each spawned Character is a fresh instance). Monsters use
the same class/ability/combat math as PCs and NPCs (Character.
base_attack_bonus()/armor_class()/saves), backed by the monster
Hit-Dice-type "classes" (animal, undead) or NPC classes (warrior, etc.)
registered in characters/class_definition.py - see that module's data
files for why this reproduces real Monster Manual numbers without a
separate stat-block resolver.
"""
import json
import os

from ethereal_dnd.characters.character import Character
from ethereal_dnd.characters.hit_points import average_monster_hp
from ethereal_dnd.characters.multiclass import add_class_level
from ethereal_dnd.items.item import ItemInstance

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "monsters")


def _load_template(monster_id: str) -> dict:
    path = os.path.join(_DATA_DIR, f"{monster_id}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def spawn_monster(monster_id: str, name: str | None = None) -> Character:
    """A fresh Character built from data/monsters/{monster_id}.json,
    ready to fight - equips its natural or mundane weapon/armor and sets
    HP via the Monster-Manual average-per-Hit-Die convention (not the
    PC/NPC-class max-at-first-level one - see hit_points.py)."""
    template = _load_template(monster_id)
    ability_scores = template["ability_scores"]
    con_modifier = (ability_scores.get("CON", 10) - 10) // 2

    character = Character(
        name=name or template["name"],
        ability_scores=dict(ability_scores),
        natural_armor_bonus=template.get("natural_armor_bonus", 0),
        max_hp=average_monster_hp(
            hit_die=_hit_die_for(template["npc_class"]), hit_dice_count=template["hit_dice"],
            con_modifier=con_modifier,
        ),
    )
    for _ in range(template["hit_dice"]):
        add_class_level(character, template["npc_class"])

    weapon_id = template.get("natural_weapon_id") or template.get("weapon_id")
    if weapon_id is not None:
        instance = ItemInstance(definition_id=weapon_id)
        character.inventory.add(instance)
        character.equipment["weapon"] = instance.id

    armor_id = template.get("armor_id")
    if armor_id is not None:
        instance = ItemInstance(definition_id=armor_id)
        character.inventory.add(instance)
        character.equipment["armor"] = instance.id

    return character


def _hit_die_for(class_id: str) -> int:
    from ethereal_dnd.characters.class_definition import class_registry

    return class_registry.get(class_id).hit_die
