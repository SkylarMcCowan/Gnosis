"""Generic stacking-modifier container - lets a later derived-stat method
(AC, attack bonus, skill totals) show *why* a number is what it is
(design doc Section 54's combat-log discipline) instead of returning a
bare int with no breakdown.
"""
import dataclasses


@dataclasses.dataclass(frozen=True)
class Modifier:
    source: str
    value: int
    # e.g. "enhancement", "morale", "dodge" - same-category bonuses don't
    # stack in D&D 3.5 (the higher one applies); "untyped" and any
    # negative value (penalties) always stack. That rule lives in
    # ModifierSet.total(), not here.
    category: str = "untyped"


class ModifierSet:
    """A collection of named Modifiers on one derived stat."""

    def __init__(self):
        self._modifiers: list[Modifier] = []

    def add(self, source: str, value: int, category: str = "untyped") -> None:
        self._modifiers.append(Modifier(source=source, value=value, category=category))

    def total(self) -> int:
        best_by_category: dict[str, int] = {}
        untyped_total = 0
        for mod in self._modifiers:
            if mod.category == "untyped" or mod.value < 0:
                untyped_total += mod.value
            else:
                best_by_category[mod.category] = max(
                    best_by_category.get(mod.category, mod.value), mod.value
                )
        return untyped_total + sum(best_by_category.values())

    def breakdown(self) -> list[Modifier]:
        return list(self._modifiers)
