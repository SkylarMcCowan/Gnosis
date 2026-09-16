"""Inventory (design doc Section 22) - a character's carried
ItemInstances. Weight/encumbrance math is a later ticket; Phase 0 only
holds the items.
"""
import dataclasses

from ethereal_dnd.items.item import ItemInstance


@dataclasses.dataclass
class Inventory:
    items: list[ItemInstance] = dataclasses.field(default_factory=list)
    gold: int = 0

    def add(self, item: ItemInstance) -> None:
        self.items.append(item)

    def remove(self, item_id: str) -> ItemInstance:
        for index, item in enumerate(self.items):
            if item.id == item_id:
                return self.items.pop(index)
        raise KeyError(f"No item instance with id {item_id!r} in this inventory")
