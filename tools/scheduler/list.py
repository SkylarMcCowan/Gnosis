"""cron.list: list every addressable crontab entry, wrapped as a Tool.

Same dependency-injection pattern as tools/web/search.py - see
tools/base.py's "HOW TO ADD A NEW TOOL" for the full walkthrough.
"""
from tools.base import Permission, Tool


class CronListTool(Tool):
    name = "cron.list"
    description = "List every addressable crontab entry, numbered."
    parameters = {}
    permission = Permission.SAFE

    def __init__(self, list_fn):
        self._list_fn = list_fn

    def execute(self):
        return self._list_fn()
