from tools.base import Permission
from tools.planning.task_plan import TaskPlanTool


def test_task_plan_tool_forwards_goal_and_context():
    calls = []
    tool = TaskPlanTool(lambda goal, context="": calls.append((goal, context)) or {"steps": []})

    assert tool.execute("finish the project", context="tests first") == {"steps": []}
    assert calls == [("finish the project", "tests first")]
    assert tool.permission == Permission.SAFE
