"""AlignmentVector (design doc Section 39; full mechanic in
docs/gnosis_crawler_alignment.md §3) - behavior tracked as vectors rather
than a single good/evil boolean, with a 9-alignment grid derived from the
two core axes for anything that needs a single label (class/deity
contracts, Turn Undead, etc.).
"""
import dataclasses

# Placeholder threshold - tunable from real playtesting, per the alignment
# doc's non-goals. +/- this many points on an axis counts as "Neutral".
_NEUTRAL_BAND = 15.0


def _axis_label(value: float, positive: str, negative: str) -> str:
    if value > _NEUTRAL_BAND:
        return positive
    if value < -_NEUTRAL_BAND:
        return negative
    return "neutral"


@dataclasses.dataclass
class AlignmentVector:
    law_chaos: float = 0.0  # -100 (chaotic) .. +100 (lawful)
    good_evil: float = 0.0  # -100 (evil) .. +100 (good)
    honor: float = 0.0
    mercy: float = 0.0
    cruelty: float = 0.0
    greed: float = 0.0
    selflessness: float = 0.0

    def law_chaos_label(self) -> str:
        """"lawful" | "neutral" | "chaotic" - lowercase, for programmatic
        comparison (the alignment/deity compliance engine's rule checks).
        See derived_alignment() for the title-case display string."""
        return _axis_label(self.law_chaos, "lawful", "chaotic")

    def good_evil_label(self) -> str:
        """"good" | "neutral" | "evil" - see law_chaos_label()."""
        return _axis_label(self.good_evil, "good", "evil")

    def derived_alignment(self) -> str:
        law_chaos_label = self.law_chaos_label().capitalize()
        good_evil_label = self.good_evil_label().capitalize()
        if law_chaos_label == "Neutral" and good_evil_label == "Neutral":
            return "True Neutral"
        if law_chaos_label == "Neutral":
            return f"Neutral {good_evil_label}"
        if good_evil_label == "Neutral":
            return f"{law_chaos_label} Neutral"
        return f"{law_chaos_label} {good_evil_label}"
