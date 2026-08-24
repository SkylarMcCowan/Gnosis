"""cron.add: create a new Gnosis-managed cron task, wrapped as a Tool.

REQUIRES_APPROVAL rather than SAFE/RESTRICTED - this mutates the real
system crontab, persistent state outside the app's own sandbox that
outlives the current session. Nothing enforces `permission` yet (Phase 15's
job), but this is exactly the kind of action that should require a human
nod once something does.
"""
from tools.base import Permission, Tool


class CronAddTool(Tool):
    name = "cron.add"
    description = "Create a new scheduled task (prompt, feature, or alarm) in the real system crontab."
    parameters = {
        "schedule_fields": "list[str] (5 cron fields: minute hour day month weekday)",
        "action_type": "string ('prompt' | 'feature' | 'alarm')",
        "action_payload": "string",
        "description": "string, optional",
        "one_shot": "bool, optional",
    }
    permission = Permission.REQUIRES_APPROVAL

    def __init__(self, add_fn):
        self._add_fn = add_fn

    def execute(self, schedule_fields, action_type, action_payload, description=None, one_shot=False):
        return self._add_fn(schedule_fields, action_type, action_payload, description=description, one_shot=one_shot)
