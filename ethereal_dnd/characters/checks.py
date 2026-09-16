"""Generic skill check resolution (design doc Section 14), sourced
verbatim from docs/srd_reference/core/SkillsI.md's "Table: Difficulty
Class Examples" - the actual DC benchmarks the SRD gives, not arbitrary
numbers.
"""
from ethereal_dnd.core.dice import roll
from ethereal_dnd.core.rng import default as default_rng

DC_VERY_EASY = 0  # "Notice something large in plain sight (Spot)"
DC_EASY = 5  # "Climb a knotted rope (Climb)"
DC_AVERAGE = 10  # "Hear an approaching guard (Listen)"
DC_TOUGH = 15  # "Rig a wagon wheel to fall off (Disable Device)"
DC_CHALLENGING = 20  # "Swim in stormy water (Swim)"
DC_FORMIDABLE = 25  # "Open an average lock (Open Lock)"
DC_HEROIC = 30  # "Leap across a 30-foot chasm (Jump)"
DC_NEARLY_IMPOSSIBLE = 40  # "Track a squad of orcs... after 24 hours of rainfall (Survival)"

DEFAULT_DC = DC_AVERAGE


def perform_skill_check(character, skill_id: str, dc: int = DEFAULT_DC, rng_service=None) -> dict:
    service = rng_service or default_rng()
    bonus = character.skill_bonus(skill_id)
    d20 = roll("1d20", rng_service=service)
    total = d20 + bonus
    success = total >= dc
    return {
        "skill_id": skill_id, "d20": d20, "bonus": bonus, "total": total, "dc": dc,
        "success": success,
        "log": f"[CHECK] {character.name or character.id} attempts a {skill_id} check: "
               f"d20 {d20} + {bonus:+d} = {total} vs DC {dc} -> {'SUCCESS' if success else 'FAILURE'}",
    }
