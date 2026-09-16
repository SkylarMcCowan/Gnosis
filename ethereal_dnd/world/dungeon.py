"""Dungeon (design doc Section 46) - a small room graph nested inside a
Location, tying together combat, conditions, and a quest (Sprint 2.5).
Traps use the same "roll a save, apply damage on failure" shape as any
other saving throw in the engine (Section 12), sourced verbatim from
docs/srd_reference/extra/Traps.md.
"""
import dataclasses
import json
import os

from ethereal_dnd.core.dice import roll

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "dungeons")


@dataclasses.dataclass
class Trap:
    id: str
    name: str
    reflex_save_dc: int
    damage_dice: str
    search_dc: int
    disable_device_dc: int
    triggered: bool = False


@dataclasses.dataclass
class DungeonRoom:
    id: str
    name: str
    description: str
    exits: dict[str, str] = dataclasses.field(default_factory=dict)  # label -> room_id
    monster_ids: list[str] = dataclasses.field(default_factory=list)
    trap: Trap | None = None
    cleared: bool = False


@dataclasses.dataclass
class Dungeon:
    id: str
    location_id: str
    entry_room_id: str
    rooms: dict[str, DungeonRoom] = dataclasses.field(default_factory=dict)


def load_dungeon(dungeon_id: str) -> Dungeon:
    """Fresh Dungeon instance from data/dungeons/{dungeon_id}.json - a
    new instance per call (not cached/idempotent like the shared
    registries) since a dungeon's rooms carry live per-campaign state
    (cleared, trap.triggered) that must not leak between campaigns."""
    path = os.path.join(_DATA_DIR, f"{dungeon_id}.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    rooms = {}
    for room_data in data["rooms"]:
        trap_data = room_data.get("trap")
        rooms[room_data["id"]] = DungeonRoom(
            id=room_data["id"], name=room_data["name"], description=room_data["description"],
            exits=dict(room_data.get("exits", {})), monster_ids=list(room_data.get("monster_ids", [])),
            trap=Trap(**trap_data) if trap_data else None,
        )
    return Dungeon(id=data["id"], location_id=data["location_id"], entry_room_id=data["entry_room_id"], rooms=rooms)


def trigger_trap(character, trap: Trap, rng_service) -> dict:
    """One saving-throw resolution for `trap` against `character`. Not
    re-triggerable once sprung (`trap.triggered`) - matches "manual
    reset" traps needing someone to reset them, which nothing in this
    vertical slice does."""
    if trap.triggered:
        return {"triggered": False, "log": f"The {trap.name} has already been sprung."}

    trap.triggered = True
    save_roll = roll("1d20", rng_service=rng_service) + character.reflex_save()
    avoided = save_roll >= trap.reflex_save_dc
    damage = 0
    if not avoided:
        damage = roll(trap.damage_dice, rng_service=rng_service)
        character.damage += damage

    log = (
        f"[TRAP] {character.name or character.id} triggers the {trap.name}! "
        f"Reflex save {save_roll} vs DC {trap.reflex_save_dc} -> "
        f"{'avoided' if avoided else f'FAILED, {damage} damage'}"
    )
    return {"triggered": True, "avoided": avoided, "damage": damage, "log": log}
