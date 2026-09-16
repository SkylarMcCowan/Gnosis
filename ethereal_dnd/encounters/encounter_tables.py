"""Encounter tables (design doc Section 28) - keyed by a Route's terrain
(sourced from ethereal_dnd/data/encounters/*.json), a single weighted
pool per terrain where "nothing happens" is itself a normal-weight entry
rather than a separate roll, so a route's overall encounter *chance* and
*content* both come from one table instead of two independent rolls.
Entries below a route's current danger_level are filtered out before
weighting, so `min_danger` reads as "this doesn't happen on quiet roads."
"""
import json
import os

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "encounters")

_cache: dict[str, list[dict]] = {}


def entries_for_terrain(terrain: str) -> list[dict]:
    if terrain not in _cache:
        path = os.path.join(_DATA_DIR, f"{terrain}.json")
        if not os.path.isfile(path):
            raise ValueError(f"No encounter table for terrain {terrain!r}")
        with open(path, "r", encoding="utf-8") as f:
            _cache[terrain] = json.load(f)["entries"]
    return _cache[terrain]


def eligible_entries(terrain: str, danger_level: int) -> list[dict]:
    return [entry for entry in entries_for_terrain(terrain) if entry.get("min_danger", 0) <= danger_level]
