"""Single authoritative campaign clock (design doc Section 25) -
everything else (NPC availability, shop hours, random encounters, rest)
reads from a CampaignTime instance rather than keeping its own clock.
"""
import dataclasses

_MINUTES_PER_HOUR = 60
_HOURS_PER_DAY = 24

# Placeholder period boundaries (Section 26) - tunable later from actual
# playtesting, same as the alignment engine's thresholds; nothing else in
# the engine depends on these exact hours yet.
_PERIODS = (
    (0, "Midnight"),
    (5, "Dawn"),
    (7, "Morning"),
    (12, "Afternoon"),
    (17, "Evening"),
    (20, "Night"),
)


@dataclasses.dataclass
class CampaignTime:
    day: int = 1
    hour: int = 6
    minute: int = 0

    def advance(self, hours: float = 0, minutes: int = 0) -> None:
        total_minutes = self.minute + minutes + round(hours * _MINUTES_PER_HOUR)
        self.minute = total_minutes % _MINUTES_PER_HOUR
        total_hours = self.hour + total_minutes // _MINUTES_PER_HOUR
        self.hour = total_hours % _HOURS_PER_DAY
        self.day += total_hours // _HOURS_PER_DAY

    @property
    def period(self) -> str:
        current = _PERIODS[0][1]
        for start_hour, name in _PERIODS:
            if self.hour >= start_hour:
                current = name
        return current

    def __str__(self) -> str:
        return f"Day {self.day}, {self.hour:02d}:{self.minute:02d} ({self.period})"
