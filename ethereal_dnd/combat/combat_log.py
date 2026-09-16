"""Combat log formatting (design doc Section 54) - renders a resolved
attack/damage roll in the human-readable breakdown format the design doc
specifies, e.g.:

    [COMBAT] Sky attacks Goblin
    d20 = 17
    Attack bonus = +2
    Attack total = 19
    Goblin AC = 16
    RESULT: HIT
"""


def format_attack(attacker_name, defender_name, d20, bonus_breakdown, total, target_ac, hit) -> str:
    lines = [f"[COMBAT] {attacker_name} attacks {defender_name}", f"d20 = {d20}"]
    for label, value in bonus_breakdown:
        lines.append(f"{label} = {value:+d}")
    lines.append(f"Attack total = {total}")
    lines.append(f"{defender_name} AC = {target_ac}")
    lines.append(f"RESULT: {'HIT' if hit else 'MISS'}")
    return "\n".join(lines)


def format_damage(detail: dict, total: int) -> str:
    lines = ["Damage:", f"{detail['expr']} = {sum(detail['kept'])}"]
    if detail["modifier"]:
        lines.append(f"modifier = {detail['modifier']:+d}")
    lines.append(f"TOTAL = {total}")
    return "\n".join(lines)
