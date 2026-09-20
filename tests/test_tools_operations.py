from tools.base import Permission
from tools.models.status import ModelStatusTool
from tools.repository.inspect import RepoInspectTool


def test_repo_inspect_tool_forwards_to_inspector():
    tool = RepoInspectTool(lambda: {"basic_audit": "ok"})

    assert tool.permission == Permission.SAFE
    assert tool.execute() == {"basic_audit": "ok"}


def test_model_status_tool_forwards_to_status_provider():
    tool = ModelStatusTool(lambda: {"available": True})

    assert tool.permission == Permission.SAFE
    assert tool.execute() == {"available": True}
