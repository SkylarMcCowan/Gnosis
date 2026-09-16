"""Dice notation parser and roller (design doc Section 43). Every roll in
the engine goes through here and, transitively, through core/rng.py's
seeded RNG service - nothing calls Python's random module directly, so a
campaign stays reproducible under a fixed seed.
"""
import re

from ethereal_dnd.core import rng

_DICE_RE = re.compile(
    r"^(?P<count>\d+)d(?P<sides>\d+)"
    r"(?:k(?P<keep_mode>[hl])(?P<keep_count>\d+))?"
    r"(?P<modifier>[+-]\d+)?$"
)


class DiceExpressionError(ValueError):
    pass


def _rolls_for(expr: str, rng_service: rng.RNGService):
    match = _DICE_RE.match(expr.strip().replace(" ", ""))
    if not match:
        raise DiceExpressionError(f"Not a valid dice expression: {expr!r}")

    count = int(match.group("count"))
    sides = int(match.group("sides"))
    rolls = [rng_service.randint(1, sides) for _ in range(count)]

    keep_mode = match.group("keep_mode")
    kept = rolls
    if keep_mode:
        keep_count = int(match.group("keep_count"))
        kept = sorted(rolls, reverse=(keep_mode == "h"))[:keep_count]

    modifier = int(match.group("modifier")) if match.group("modifier") else 0
    return rolls, kept, modifier


def roll(expr: str, rng_service: rng.RNGService | None = None) -> int:
    """Roll a dice expression like "1d20+3", "2d6", or "4d6kh3" (keep the
    highest 3 of 4d6, standard ability-score-generation notation) and
    return the total."""
    _, kept, modifier = _rolls_for(expr, rng_service or rng.default())
    return sum(kept) + modifier


def roll_detailed(expr: str, rng_service: rng.RNGService | None = None) -> dict:
    """Same as roll(), but returns the individual die results alongside
    the total - feeds the Section 54 combat-log format ("d20 = 17,
    BAB = +2, ... Attack total = 23")."""
    rolls, kept, modifier = _rolls_for(expr, rng_service or rng.default())
    return {
        "expr": expr,
        "rolls": rolls,
        "kept": kept,
        "modifier": modifier,
        "total": sum(kept) + modifier,
    }
