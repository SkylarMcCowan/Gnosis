"""Tests for the Phase 0.2 minimal domain models - just the shapes
(Party/Inventory/World) that Phase 1 didn't need to change. Character's
derived-stat math itself is covered in test_ethereal_dnd_character_math.py
now that Phase 1 has actually implemented it.
"""
import pytest

from ethereal_dnd.characters.alignment import AlignmentVector
from ethereal_dnd.characters.character import Character
from ethereal_dnd.characters.class_level import ClassLevel
from ethereal_dnd.characters.multiclass import add_class_level
from ethereal_dnd.characters.party import MAX_PARTY_SIZE, Party, PartyFullError
from ethereal_dnd.items.inventory import Inventory
from ethereal_dnd.items.item import ItemInstance
from ethereal_dnd.world.location import Location
from ethereal_dnd.world.route import Route
from ethereal_dnd.world.world import World


def test_character_level_sums_across_class_levels():
    character = Character(class_levels=[ClassLevel("fighter", 3), ClassLevel("rogue", 2)])
    assert character.level == 5


def test_add_class_level_creates_and_increments():
    character = Character()
    add_class_level(character, "fighter")
    add_class_level(character, "fighter")
    add_class_level(character, "rogue")
    levels = {cl.class_id: cl.levels for cl in character.class_levels}
    assert levels == {"fighter": 2, "rogue": 1}


def test_party_enforces_max_size():
    party = Party()
    for i in range(MAX_PARTY_SIZE):
        party.add(Character(name=f"member-{i}"))
    with pytest.raises(PartyFullError):
        party.add(Character(name="one-too-many"))


def test_party_living_members_excludes_dead():
    party = Party()
    party.add(Character(name="alive", status="alive"))
    party.add(Character(name="dead", status="dead"))
    assert [m.name for m in party.living_members()] == ["alive"]


def test_alignment_vector_derives_true_neutral_at_zero():
    assert AlignmentVector().derived_alignment() == "True Neutral"


def test_alignment_vector_derives_lawful_good():
    assert AlignmentVector(law_chaos=50, good_evil=50).derived_alignment() == "Lawful Good"


def test_alignment_vector_derives_neutral_evil():
    assert AlignmentVector(law_chaos=0, good_evil=-50).derived_alignment() == "Neutral Evil"


def test_inventory_add_and_remove():
    inventory = Inventory()
    item = ItemInstance(definition_id="longsword")
    inventory.add(item)
    removed = inventory.remove(item.id)
    assert removed is item
    assert inventory.items == []


def test_inventory_remove_missing_item_raises():
    with pytest.raises(KeyError):
        Inventory().remove("nonexistent")


def test_world_tracks_locations_and_routes_from():
    world = World()
    world.add_location(Location(id="ravenhollow", name="Ravenhollow"))
    world.add_location(Location(id="blackwood", name="Blackwood"))
    world.add_route(Route(origin_id="ravenhollow", destination_id="blackwood"))
    assert [route.destination_id for route in world.routes_from("ravenhollow")] == ["blackwood"]
    assert world.routes_from("blackwood") == []
