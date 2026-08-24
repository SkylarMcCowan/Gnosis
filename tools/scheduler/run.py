"""cron.run: run a Gnosis-managed cron task's action immediately, wrapped
as a Tool. RESTRICTED rather than REQUIRES_APPROVAL - unlike add/edit/
remove, this doesn't create or change any persistent crontab state, it just
executes a task that a human already approved when it was scheduled. Still
not SAFE, since running it can have real effects (a real model call, a real
alarm sound, a real historian pass).
"""
from tools.base import Permission, Tool


class CronRunTool(Tool):
    name = "cron.run"
    description = "Run a Gnosis-managed cron task's action right now, without waiting for its schedule."
    parameters = {"task_id": "string"}
    permission = Permission.RESTRICTED

    def __init__(self, run_fn):
        self._run_fn = run_fn

    def execute(self, task_id):
        return self._run_fn(task_id)
