"""live.soccer_result: a soccer team's last result and next fixture,
wrapped as a Tool.

Same dependency-injection pattern as tools/web/search.py - see
tools/base.py's "HOW TO ADD A NEW TOOL" for the full walkthrough.
"""
from tools.base import Permission, Tool


class LiveSoccerResultTool(Tool):
    name = "live.soccer_result"
    description = (
        "Get a soccer team's most recent match result (opponent, score, competition, date) and "
        "next scheduled fixture if any, covering that team's domestic league plus UEFA Champions "
        "League/Europa League. Use for any question about a soccer team's last/next match, score, "
        "or fixture."
    )
    parameters = {"team": "string - a soccer team name (e.g. \"Manchester United\")"}
    permission = Permission.SAFE

    def __init__(self, lookup_fn):
        self._lookup_fn = lookup_fn

    def execute(self, team):
        return self._lookup_fn(team)
