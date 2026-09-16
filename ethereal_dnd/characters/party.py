"""Party (design doc Section 48) - up to 3 characters, all directly
controlled by the player (no AI-controlled companions - the player
chooses every action for every party member, combat or otherwise).
"""
import dataclasses

from ethereal_dnd.characters.character import Character

MAX_PARTY_SIZE = 3


class PartyFullError(ValueError):
    pass


@dataclasses.dataclass
class Party:
    members: list[Character] = dataclasses.field(default_factory=list)

    def add(self, character: Character) -> None:
        if len(self.members) >= MAX_PARTY_SIZE:
            raise PartyFullError(f"Party already has the maximum of {MAX_PARTY_SIZE} members")
        self.members.append(character)

    def living_members(self) -> list[Character]:
        return [member for member in self.members if member.status == "alive"]
