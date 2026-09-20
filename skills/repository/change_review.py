"""repo.change_review: inspect a repository and optionally run its tests."""
from skills.base import Skill
from tools.registry import registry as tool_registry


class RepositoryChangeReviewSkill(Skill):
    name = "repo.change_review"
    description = "Inspect repository health and optionally run the restricted project test tool."
    parameters = {"run_tests": "boolean, optional"}
    required_tools = ("repo.inspect", "test.run")

    def execute(self, run_tests=False):
        result = {"inspection": tool_registry.execute("repo.inspect")}
        if run_tests:
            result["tests"] = tool_registry.execute("test.run")
        return result
