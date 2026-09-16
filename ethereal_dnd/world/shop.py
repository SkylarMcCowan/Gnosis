"""Shop/economy stub (design doc Section 34's gold field) - buy from an
NPC's stock at full list price, sell at half (the standard SRD assumption
that secondhand goods fetch half value). No dynamic pricing yet - a
later ticket (Phase 11, "Economy") can layer supply/demand on top of
this without changing the shape here.
"""
from ethereal_dnd.core.events import EventBus, ItemPurchased
from ethereal_dnd.items.item import ItemInstance, item_registry

SELL_PRICE_FRACTION = 0.5


class ShopError(ValueError):
    pass


def buy_from_npc(character, npc, item_id: str, events: EventBus) -> None:
    if item_id not in npc.stock:
        raise ShopError(f"{npc.name} doesn't sell {item_id!r}")
    item_def = item_registry.get(item_id)
    if character.gold < item_def.value_gp:
        raise ShopError(
            f"{character.name or character.id} has {character.gold} gp but "
            f"{item_def.name} costs {item_def.value_gp} gp"
        )
    character.gold -= item_def.value_gp
    character.inventory.add(ItemInstance(definition_id=item_id))
    events.emit(ItemPurchased(character_id=character.id, item_id=item_id, price=item_def.value_gp))


def sell_item(character, instance_id: str) -> int:
    """Sells one of `character`'s own item instances for half its list
    price, regardless of which NPC is buying it (no per-NPC buyback
    list needed for a stub this simple - any merchant will buy your
    old gear). Returns the gold received."""
    instance = next((item for item in character.inventory.items if item.id == instance_id), None)
    if instance is None:
        raise ShopError(f"No item instance {instance_id!r} in {character.name or character.id}'s inventory")
    item_def = item_registry.get(instance.definition_id)
    price = int(item_def.value_gp * SELL_PRICE_FRACTION)
    character.inventory.remove(instance_id)
    character.gold += price
    return price
