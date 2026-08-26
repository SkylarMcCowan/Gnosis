"""subscriptions.list: the user's current subscriptions
(core/subscriptions.py), wrapped as a Tool.
"""
from tools.base import Permission, Tool


class SubscriptionsListTool(Tool):
    name = "subscriptions.list"
    description = (
        "List the user's current subscriptions - teams, topics, websites, and weather locations "
        "that Gnosis prioritizes in answers over guessing/searching."
    )
    parameters = {}
    permission = Permission.SAFE

    def __init__(self, list_fn):
        self._list_fn = list_fn

    def execute(self):
        return self._list_fn()
