"""ClassLevel (design doc Section 13) - one entry per class a character
has taken levels in. A Character's class_levels is a list of these, never
a single class/level pair, so a multiclass character (Fighter 3 / Rogue 2
/ Wizard 1) is representable from Phase 0 onward.
"""
import dataclasses


@dataclasses.dataclass
class ClassLevel:
    class_id: str
    levels: int
