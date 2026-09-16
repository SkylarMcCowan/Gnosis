"""CharacterDivineStanding (alignment doc §3) - runtime state tracking
whether a character has fallen from grace for one or more classes, and
why.
"""
import dataclasses

from ethereal_dnd.core.time import CampaignTime


@dataclasses.dataclass
class CharacterDivineStanding:
    deity_id: str | None = None
    fallen: bool = False
    fallen_reason: str | None = None
    fallen_at: CampaignTime | None = None
    powers_revoked: list[str] = dataclasses.field(default_factory=list)  # class_ids with revoked powers
    advancement_blocked_for: list[str] = dataclasses.field(default_factory=list)  # class_ids capped, not stripped

    def is_class_usable(self, class_id: str) -> bool:
        return class_id not in self.powers_revoked

    def can_advance(self, class_id: str) -> bool:
        return class_id not in self.advancement_blocked_for
