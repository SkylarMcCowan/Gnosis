"""Generic content registry (design doc Section 7) - one implementation
shared by every registry in the engine (class_registry, race_registry,
deity_registry, etc.) rather than a bespoke register/get/all per content
type.
"""


class DuplicateRegistrationError(KeyError):
    pass


class Registry:
    def __init__(self, kind: str):
        self._kind = kind
        self._items = {}

    def register(self, item_id: str, item) -> None:
        if item_id in self._items:
            raise DuplicateRegistrationError(
                f"{self._kind} {item_id!r} is already registered"
            )
        self._items[item_id] = item

    def get(self, item_id: str):
        try:
            return self._items[item_id]
        except KeyError:
            raise KeyError(f"No {self._kind} registered with id {item_id!r}") from None

    def all(self) -> list:
        return list(self._items.values())

    def __contains__(self, item_id: str) -> bool:
        return item_id in self._items

    def __len__(self) -> int:
        return len(self._items)
