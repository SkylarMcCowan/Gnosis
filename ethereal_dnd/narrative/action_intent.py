"""ActionIntent (design doc Section 32) - the structured shape freeform
player text gets turned into, before anything mechanical happens. This
is data only; deciding what it's allowed to do is action_resolver.py's
job, not this module's.
"""
import dataclasses

# The action types action_resolver.py actually knows how to handle
# (Section 65's exit criteria doesn't require the *full* Section 31
# catalog - Sections 61/62 are explicit that a vertical slice covers "at
# minimum the Section 31 example actions," not everything imaginable).
# "unsupported" is a real, first-class outcome: the parser choosing it
# for something outside this list is not an error, it's the honest
# answer for what the engine can't yet resolve mechanically - the
# narrator describes that limitation instead of inventing an outcome.
KNOWN_ACTION_TYPES = (
    "attack", "skill_check", "talk", "travel", "rest", "cast_spell", "wait", "look", "unsupported",
)


@dataclasses.dataclass
class ActionIntent:
    action_type: str
    actor_id: str = "player"
    target_id: str | None = None
    skill_id: str | None = None
    spell_id: str | None = None
    destination_id: str | None = None
    duration_hours: float | None = None
    description: str = ""
    raw_text: str = ""
