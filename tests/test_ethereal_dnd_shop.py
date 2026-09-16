"""Tests for GC-051's shop/economy stub."""
import pytest

from ethereal_dnd.cli import debug_cli
from ethereal_dnd.world.shop import ShopError, buy_from_npc, sell_item


def _campaign_and_buyer(gold=100):
    campaign = debug_cli.new_ravenhollow_campaign(seed=1)
    character = debug_cli.create_test_character(
        "Sky", "fighter", {"STR": 16, "DEX": 14, "CON": 14, "INT": 10, "WIS": 12, "CHA": 8}, max_hp=13,
    )
    character.gold = gold
    campaign.party.add(character)
    return campaign, character


def test_buy_from_npc_deducts_gold_and_adds_the_item():
    campaign, character = _campaign_and_buyer(gold=100)
    npc = campaign.world.npcs["boran_blacksmith"]

    buy_from_npc(character, npc, "longsword", campaign.events)

    assert character.gold == 85  # longsword is 15 gp
    assert character.inventory.items[0].definition_id == "longsword"


def test_buy_from_npc_rejects_an_item_not_in_stock():
    campaign, character = _campaign_and_buyer(gold=10000)
    npc = campaign.world.npcs["boran_blacksmith"]
    with pytest.raises(ShopError):
        buy_from_npc(character, npc, "full_plate", campaign.events)


def test_buy_from_a_non_shop_npc_always_fails():
    """An NPC with an empty stock list (the default - Section 51's
    "not every NPC is a shop") must refuse every item, not sell
    everything unrestricted."""
    campaign, character = _campaign_and_buyer(gold=10000)
    npc = campaign.world.npcs["mabel_innkeeper"]
    with pytest.raises(ShopError):
        buy_from_npc(character, npc, "longsword", campaign.events)


def test_buy_from_npc_rejects_insufficient_gold():
    campaign, character = _campaign_and_buyer(gold=5)
    npc = campaign.world.npcs["boran_blacksmith"]
    with pytest.raises(ShopError):
        buy_from_npc(character, npc, "longsword", campaign.events)
    assert character.gold == 5  # unchanged on failure
    assert character.inventory.items == []


def test_buy_from_npc_emits_item_purchased_event():
    campaign, character = _campaign_and_buyer(gold=100)
    npc = campaign.world.npcs["boran_blacksmith"]
    purchased = []
    campaign.events.subscribe("ItemPurchased", lambda e: purchased.append(e))

    buy_from_npc(character, npc, "longsword", campaign.events)

    assert purchased[0].item_id == "longsword"
    assert purchased[0].price == 15


def test_sell_item_returns_half_list_price():
    campaign, character = _campaign_and_buyer(gold=100)
    npc = campaign.world.npcs["boran_blacksmith"]
    buy_from_npc(character, npc, "longsword", campaign.events)
    instance_id = character.inventory.items[0].id

    price = sell_item(character, instance_id)

    assert price == 7  # floor(15 * 0.5)
    assert character.gold == 85 + 7
    assert character.inventory.items == []


def test_sell_item_raises_for_an_instance_not_owned():
    _, character = _campaign_and_buyer()
    with pytest.raises(ShopError):
        sell_item(character, "not-a-real-instance-id")


def test_debug_cli_buy_and_sell_wrappers_work():
    campaign, character = _campaign_and_buyer(gold=100)
    result = debug_cli.buy_item(campaign, character, "boran_blacksmith", "short_sword")
    assert "Bought" in result
    instance_id = character.inventory.items[0].id
    result = debug_cli.sell_item(character, instance_id)
    assert "Sold" in result
