"""test.run: run the project's test suite, wrapped as a Tool.

RESTRICTED rather than SAFE - it's read-only in the sense that it doesn't
change any files, but it does spawn a real subprocess and consume real
time/resources, and (via anything the tests themselves exercise) could have
side effects beyond the sandbox this call was made from.
"""
from tools.base import Permission, Tool


class TestRunTool(Tool):
    __test__ = False  # tell pytest this isn't a test class despite the name

    name = "test.run"
    description = "Run the project's test suite. Returns (passed: bool, output: str)."
    parameters = {}
    permission = Permission.RESTRICTED

    def __init__(self, run_fn):
        self._run_fn = run_fn

    def execute(self):
        return self._run_fn()
