"""FeatDefinition (design doc Section 15) - registered by id, loaded from
real SRD feat data (docs/srd_reference/core/Feats.md) once a later ticket
picks this up. Phase 0 only fixes the shape.
"""
import dataclasses

from ethereal_dnd.core.registry import Registry


@dataclasses.dataclass
class FeatDefinition:
    id: str
    name: str
    prerequisites: list[str] = dataclasses.field(default_factory=list)
    bonuses: dict = dataclasses.field(default_factory=dict)
    actions: list[str] = dataclasses.field(default_factory=list)
    passive_effects: list[str] = dataclasses.field(default_factory=list)


feat_registry = Registry("feat")
