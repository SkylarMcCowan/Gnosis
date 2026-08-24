"""cron.remove: remove a crontab entry by its 1-based /cron list index,
wrapped as a Tool. REQUIRES_APPROVAL for the same reason as cron.add - see
that file's docstring.
"""
from tools.base import Permission, Tool


class CronRemoveTool(Tool):
    name = "cron.remove"
    description = "Remove the crontab entry at a given 1-based index (as numbered by cron.list)."
    parameters = {"index": "int"}
    permission = Permission.REQUIRES_APPROVAL

    def __init__(self, remove_fn):
        self._remove_fn = remove_fn

    def execute(self, index):
        return self._remove_fn(index)
