"""web.fetch: fetch and extract a web page's content, wrapped as a Tool.

Same dependency-injection pattern as tools/web/search.py - see
tools/base.py's "HOW TO ADD A NEW TOOL" for the full walkthrough.
"""
from tools.base import Permission, Tool


class WebFetchTool(Tool):
    name = "web.fetch"
    description = "Fetch a URL and return its extracted page content."
    parameters = {"url": "string"}
    permission = Permission.SAFE

    def __init__(self, fetch_fn):
        self._fetch_fn = fetch_fn

    def execute(self, url):
        return self._fetch_fn(url)
