"""Random encounters (design doc Section 28) - rolled once per Route
traveled (world/travel.py). Not every encounter is combat: "none",
"traveler", and "discovery" outcomes are real, not just documented (see
docs/gnosis_crawler_backlog.md's GC-056).
"""
from ethereal_dnd.encounters.encounter_tables import eligible_entries
from ethereal_dnd.encounters.monster_factory import spawn_monster


def roll_encounter(route, rng_service) -> dict | None:
    """Returns None if the roll landed on a "none" entry, otherwise a
    dict: {"type": ..., "log": str, "monsters": [Character, ...] | None}.
    `monsters` is populated only for `type == "combat"` - the caller
    (CLI/GUI) decides whether/how to actually run that fight."""
    entries = eligible_entries(route.terrain, route.danger_level)
    total_weight = sum(entry["weight"] for entry in entries)
    roll = rng_service.randint(1, total_weight)

    running_total = 0
    chosen = entries[-1]
    for entry in entries:
        running_total += entry["weight"]
        if roll <= running_total:
            chosen = entry
            break

    if chosen["type"] == "none":
        return None

    if chosen["type"] == "combat":
        monsters = [spawn_monster(monster_id) for monster_id in chosen["monster_ids"]]
        names = ", ".join(m.name for m in monsters)
        return {
            "type": "combat",
            "log": f"[ENCOUNTER] Combat: {names}!",
            "monsters": monsters,
        }

    return {
        "type": chosen["type"],
        "log": f"[ENCOUNTER] {chosen['description']}",
        "monsters": None,
    }
