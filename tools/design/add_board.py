from tools.base import Permission, Tool


class DesignAddBoardTool(Tool):
    name = "design.add_board"
    description = "Add a board (artboard/frame) to a page in a Penpot file - a container to lay other shapes out on."
    parameters = {
        "file_id": "string",
        "name": "string",
        "x": "number, optional",
        "y": "number, optional",
        "width": "number, optional",
        "height": "number, optional",
        "page_id": "string, optional (defaults to the file's first page)",
        "fill_color": "string, optional (hex, e.g. '#FFFFFF')",
    }
    permission = Permission.RESTRICTED

    def __init__(self, add_board_fn):
        self._add_board_fn = add_board_fn

    def execute(self, file_id, name, x=0, y=0, width=1440, height=1024, page_id=None, fill_color=None):
        return self._add_board_fn(
            file_id, name, x=x, y=y, width=width, height=height, page_id=page_id, fill_color=fill_color,
        )
