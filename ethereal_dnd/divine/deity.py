"""Deity (alignment doc §3) - registered by id, loaded from
data/deities/*.json. `code_of_conduct` is deliberately empty on the
starting campaign's deities for now (see the module docstring in
compliance.py's ALIGNMENT_CODES section) - it's real, structured, and
evaluated the same way a class's `alignment_restriction` is, but writing
deity-specific dogma-violation content is Phase 2 campaign-content work,
not part of proving the compliance *engine* works.
"""
import dataclasses
import json
import os

from ethereal_dnd.core.registry import Registry

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "deities")

# The 9-alignment two-letter/one-letter codes used by Deity.alignment and
# Character.divine_standing lookups - "N" alone means True Neutral (both
# axes neutral), matching how the SRD itself abbreviates it.
ALIGNMENT_CODES = {
    "LG": ("lawful", "good"), "NG": ("neutral", "good"), "CG": ("chaotic", "good"),
    "LN": ("lawful", "neutral"), "N": ("neutral", "neutral"), "CN": ("chaotic", "neutral"),
    "LE": ("lawful", "evil"), "NE": ("neutral", "evil"), "CE": ("chaotic", "evil"),
}


def decode_alignment_code(code: str) -> tuple[str, str]:
    try:
        return ALIGNMENT_CODES[code]
    except KeyError:
        raise ValueError(f"Not a valid alignment code: {code!r}") from None


@dataclasses.dataclass
class Deity:
    id: str
    name: str
    alignment: str  # one of ALIGNMENT_CODES's keys
    domains: list[str] = dataclasses.field(default_factory=list)
    dogma: str = ""
    code_of_conduct: list[dict] = dataclasses.field(default_factory=list)  # ComplianceRule dicts, scope="deity"
    favored_weapon: str | None = None
    symbol: str = ""


deity_registry = Registry("deity")


def load_deities(target_registry: Registry | None = None, data_dir: str | None = None) -> None:
    """Load every data/deities/*.json definition into `target_registry`
    (default: the module-level deity_registry). Idempotent - see
    characters/skills.py's load_skills() for why."""
    registry_to_use = target_registry if target_registry is not None else deity_registry
    directory = data_dir or _DATA_DIR
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(directory, filename), "r", encoding="utf-8") as f:
            data = json.load(f)
        if data["id"] in registry_to_use:
            continue
        registry_to_use.register(data["id"], Deity(**data))
