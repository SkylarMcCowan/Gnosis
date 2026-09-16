"""Combat actions (design doc Section 18) - enough of the action list for
a real encounter (Phase 2's dungeon), not the full catalog. Each action
resolves purely against Character/Encounter state and returns a result +
Section 54-style log text; narration of the outcome is the narrator's
job (Section 2.1's rules-first boundary), not this module's.
"""
from ethereal_dnd.characters import death
from ethereal_dnd.combat import combat_log, conditions
from ethereal_dnd.core.dice import roll
from ethereal_dnd.core.events import EventBus

# A natural 1 always misses, a natural 20 always hits, regardless of the
# total - the standard SRD "automatic miss/hit" rule.
AUTOMATIC_MISS_ROLL = 1
AUTOMATIC_HIT_ROLL = 20


def attack_sequence(base_attack_bonus: int) -> list[int]:
    """The iterative-attack bonus sequence for a full attack (Section
    16/18): one extra attack at a cumulative -5 for every 5 points of
    base attack bonus at or above +6 (e.g. BAB +16 -> [16, 11, 6, 1] -
    matches the "+16/+11/+6/+1" notation in every sourced class table)."""
    bonuses = [base_attack_bonus]
    next_bonus = base_attack_bonus - 5
    while next_bonus >= 1:
        bonuses.append(next_bonus)
        next_bonus -= 5
    return bonuses


def resolve_attack(attacker, defender, rng_service, weapon_slot: str = "weapon", attack_bonus_override: int | None = None) -> dict:
    """One attack roll: attacker vs. defender's AC, then a damage roll if
    it hits. Returns {"hit": bool, "damage": int, "log": str}."""
    weapon_def = attacker.equipped_item_definition(weapon_slot)
    is_ranged = weapon_def is not None and weapon_def.properties.get("weapon_group") == "ranged"

    attack_bonus = attack_bonus_override if attack_bonus_override is not None else attacker.attack_bonus(weapon_slot)
    attack_bonus += conditions.all_rolls_penalty(attacker)
    attack_bonus += conditions.prone_attack_roll_modifier(attacker)

    target_ac = defender.armor_class()
    target_ac += conditions.ac_penalty(defender)
    target_ac += conditions.prone_ac_modifier(defender, attack_is_ranged=is_ranged)
    if conditions.loses_dex_to_ac(defender):
        target_ac -= defender.effective_dex_bonus_to_ac()

    d20 = roll("1d20", rng_service=rng_service)
    total = d20 + attack_bonus
    if d20 == AUTOMATIC_MISS_ROLL:
        hit = False
    elif d20 == AUTOMATIC_HIT_ROLL:
        hit = True
    else:
        hit = total >= target_ac

    log_lines = [combat_log.format_attack(
        attacker.name or attacker.id, defender.name or defender.id,
        d20, [("Attack bonus", attack_bonus)], total, target_ac, hit,
    )]

    damage = 0
    if hit:
        if weapon_def is not None:
            detail = attacker.melee_damage(weapon_def.id, rng_service)
        else:
            # Unarmed strike: 1d3 (SRD's unarmed damage for a Medium
            # attacker) + Str modifier, same shape as a light weapon.
            from ethereal_dnd.core.dice import roll_detailed
            detail = roll_detailed("1d3", rng_service=rng_service)
            detail["modifier"] += attacker.ability_modifier("STR")
            detail["total"] = max(0, sum(detail["kept"]) + detail["modifier"])
        damage = detail["total"]
        log_lines.append(combat_log.format_damage(detail, damage))

    return {"hit": hit, "damage": damage, "log": "\n".join(log_lines)}


def full_attack(attacker, defender, rng_service, weapon_slot: str = "weapon") -> list[dict]:
    """A full-round attack: one resolve_attack() per entry in this
    attacker's iterative-attack sequence (Section 18's FullAttackAction).
    Stops early if the defender dies partway through."""
    results = []
    for bonus in attack_sequence(attacker.attack_bonus(weapon_slot)):
        if defender.status != "alive":
            break
        results.append(resolve_attack(attacker, defender, rng_service, weapon_slot, attack_bonus_override=bonus))
    return results


def apply_attack_damage(result: dict, defender, campaign_time, events: EventBus, location_id: str | None = None) -> None:
    """Feed a resolve_attack()/full_attack() result's damage into the
    defender via characters/death.py's HP-and-death handling, so combat
    and any other damage source share one path to "does this kill them.\""""
    if result["hit"] and result["damage"] > 0:
        death.apply_damage(defender, result["damage"], campaign_time, events, location_id)


def move_action(character, encounter, destination) -> str:
    """MoveAction (Section 18) - Phase 1 doesn't have a battlefield grid
    yet (that's a later ticket), so this just records the intent in the
    combat log rather than computing actual movement/attacks of
    opportunity."""
    log_line = f"[COMBAT] {character.name or character.id} moves toward {destination}"
    encounter.combat_log.append(log_line)
    return log_line


def withdraw_action(character, encounter) -> str:
    """WithdrawAction (Section 18) - like move_action, records intent;
    the "no attacks of opportunity for the first square" rule needs the
    battlefield/positions model a later ticket adds."""
    log_line = f"[COMBAT] {character.name or character.id} withdraws from combat"
    encounter.combat_log.append(log_line)
    return log_line


AID_ANOTHER_BONUS = 2


def aid_another_action(character, ally, encounter, rng_service, dc: int = 10) -> dict:
    """AidAnotherAction (Section 18): an attack roll against DC 10. On a
    success the ally gets a +2 bonus to their next relevant roll -
    returned as `bonus` for the caller to apply (e.g. pass it as part of
    `attack_bonus_override` to the ally's next resolve_attack() call).
    Not modeled as a Condition: the bonus is scoped to one specific next
    roll, not an ongoing state with its own duration to track, so it
    doesn't fit conditions.py's always-on shape."""
    d20 = roll("1d20", rng_service=rng_service)
    attack_bonus = character.attack_bonus()
    total = d20 + attack_bonus
    succeeded = total >= dc
    log_line = (
        f"[COMBAT] {character.name or character.id} aids {ally.name or ally.id}: "
        f"d20 {d20} + attack bonus {attack_bonus:+d} = {total} vs DC {dc} -> "
        f"{'SUCCESS' if succeeded else 'FAILURE'}"
    )
    encounter.combat_log.append(log_line)
    return {"succeeded": succeeded, "bonus": AID_ANOTHER_BONUS if succeeded else 0, "log": log_line}
