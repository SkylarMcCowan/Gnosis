"""Regression tests for tools/design/*.py in isolation - construct each
Tool with a fake callable and assert execute() forwards correctly. Real
Penpot-wiring tests live in tests/test_tools_wiring.py.
"""
from tools.base import Permission
from tools.design.list_projects import DesignListProjectsTool
from tools.design.create_project import DesignCreateProjectTool
from tools.design.list_files import DesignListFilesTool
from tools.design.create_file import DesignCreateFileTool
from tools.design.get_file import DesignGetFileTool
from tools.design.add_board import DesignAddBoardTool
from tools.design.add_shape import DesignAddShapeTool


def test_list_projects_tool():
    tool = DesignListProjectsTool(lambda: [{"id": "p1", "name": "Website"}])
    assert tool.name == "design.list_projects"
    assert tool.permission == Permission.SAFE
    assert tool.execute() == [{"id": "p1", "name": "Website"}]


def test_create_project_tool_forwards_name():
    calls = []
    tool = DesignCreateProjectTool(lambda name: calls.append(name) or {"id": "p1", "name": name})
    assert tool.permission == Permission.RESTRICTED
    result = tool.execute(name="Website")
    assert calls == ["Website"]
    assert result == {"id": "p1", "name": "Website"}


def test_list_files_tool_forwards_project_id():
    calls = []
    tool = DesignListFilesTool(lambda project_id: calls.append(project_id) or [])
    tool.execute(project_id="p1")
    assert calls == ["p1"]


def test_create_file_tool_forwards_args():
    calls = []
    tool = DesignCreateFileTool(lambda project_id, name: calls.append((project_id, name)))
    tool.execute(project_id="p1", name="Landing page")
    assert calls == [("p1", "Landing page")]


def test_get_file_tool_forwards_file_id():
    calls = []
    tool = DesignGetFileTool(lambda file_id: calls.append(file_id) or {"id": file_id, "pages": []})
    result = tool.execute(file_id="f1")
    assert calls == ["f1"]
    assert result == {"id": "f1", "pages": []}


def test_add_board_tool_forwards_all_args_with_defaults():
    calls = []

    def fake_add_board(file_id, name, x=0, y=0, width=1440, height=1024, page_id=None, fill_color=None):
        calls.append((file_id, name, x, y, width, height, page_id, fill_color))
        return {"id": "b1"}

    tool = DesignAddBoardTool(fake_add_board)
    assert tool.permission == Permission.RESTRICTED
    result = tool.execute(file_id="f1", name="Home")
    assert calls == [("f1", "Home", 0, 0, 1440, 1024, None, None)]
    assert result == {"id": "b1"}

    tool.execute(file_id="f1", name="Home", x=10, y=20, width=300, height=200, page_id="pg1", fill_color="#FFFFFF")
    assert calls[1] == ("f1", "Home", 10, 20, 300, 200, "pg1", "#FFFFFF")


def test_add_shape_tool_forwards_all_args_with_defaults():
    calls = []

    def fake_add_shape(file_id, shape_type, page_id=None, board_id=None, x=0, y=0, width=100, height=100,
                        fill_color=None, text=None, font_size=16, name=None):
        calls.append((file_id, shape_type, page_id, board_id, x, y, width, height, fill_color, text, font_size, name))
        return {"id": "s1"}

    tool = DesignAddShapeTool(fake_add_shape)
    assert tool.permission == Permission.RESTRICTED
    result = tool.execute(file_id="f1", shape_type="rect")
    assert calls == [("f1", "rect", None, None, 0, 0, 100, 100, None, None, 16, None)]
    assert result == {"id": "s1"}

    tool.execute(
        file_id="f1", shape_type="text", page_id="pg1", board_id="b1", x=5, y=6, width=200, height=40,
        fill_color="#000000", text="Hello", font_size=24, name="Headline",
    )
    assert calls[1] == ("f1", "text", "pg1", "b1", 5, 6, 200, 40, "#000000", "Hello", 24, "Headline")
