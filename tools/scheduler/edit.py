"""cron.edit: update an existing Gnosis-managed cron task in place, wrapped
as a Tool. REQUIRES_APPROVAL for the same reason as cron.add - see that
file's docstring.
"""
from tools.base import Permission, Tool


class CronEditTool(Tool):
    name = "cron.edit"
    description = "Update an existing Gnosis-managed crontab entry's schedule/action in place."
    parameters = {
        "task_id": "string",
        "schedule_fields": "list[str], optional",
        "action_type": "string, optional",
        "action_payload": "string, optional",
        "description": "string, optional",
        "one_shot": "bool, optional",
    }
    permission = Permission.REQUIRES_APPROVAL

    def __init__(self, edit_fn):
        self._edit_fn = edit_fn

    def execute(self, task_id, schedule_fields=None, action_type=None, action_payload=None, description=None, one_shot=None):
        return self._edit_fn(
            task_id,
            schedule_fields=schedule_fields,
            action_type=action_type,
            action_payload=action_payload,
            description=description,
            one_shot=one_shot,
        )
