"""Average hit points per level - the common non-random shortcut for
NPCs/monsters (max HP at 1st level, then (hit_die/2 + 1) per level after,
plus Constitution modifier per level): a GM doesn't roll HP for every
townsperson, and neither does this engine for NPCs/monsters it generates.
Player characters still roll (a later ticket, once character creation
exists) - this helper is for content built by data (world/npc.py,
encounters/monster_factory.py), not for the player's own party.
"""


def average_max_hp(hit_die: int, level: int, con_modifier: int = 0) -> int:
    if level < 1:
        raise ValueError(f"Level must be at least 1, got {level}")
    first_level_hp = hit_die + con_modifier
    per_level_after = (hit_die // 2 + 1) + con_modifier
    return max(1, first_level_hp + per_level_after * (level - 1))


def average_monster_hp(hit_die: int, hit_dice_count: int, con_modifier: int = 0) -> int:
    """Monster Manual convention (every stat block's "Hit Dice: NdX+Y
    (avg hp)" line) - the average roll *per Hit Die*, summed across all
    of them, with no "max HP on the first die" bump (that's the PC/NPC-
    class convention average_max_hp() above uses instead). Verified
    against the sourced Wolf stat block (2d8+4 (13 hp)):
    average_monster_hp(8, 2, 2) == 13."""
    if hit_dice_count < 1:
        raise ValueError(f"Hit dice count must be at least 1, got {hit_dice_count}")
    average_per_die = hit_die / 2 + 0.5
    return max(1, round(hit_dice_count * average_per_die) + hit_dice_count * con_modifier)
