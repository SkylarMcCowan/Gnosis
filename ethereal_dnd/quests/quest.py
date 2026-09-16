"""Quest (design doc Section 40) - field shape only; the state machine
and quest hooks are later tickets. Phase 0 fixes what a Quest holds.
"""
import dataclasses

from ethereal_dnd.core.ids import new_id


@dataclasses.dataclass
class Quest:
    id: str = dataclasses.field(default_factory=new_id)
    title: str = ""
    description: str = ""
    giver_id: str | None = None
    objectives: list[dict] = dataclasses.field(default_factory=list)
    requirements: list[str] = dataclasses.field(default_factory=list)
    rewards: dict = dataclasses.field(default_factory=dict)
    failure_conditions: list[str] = dataclasses.field(default_factory=list)
    expiration: str | None = None
    state: str = "not_started"  # "not_started" | "active" | "completed" | "failed"
    consequences: list[str] = dataclasses.field(default_factory=list)
