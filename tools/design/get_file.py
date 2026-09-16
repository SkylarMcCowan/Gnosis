from tools.base import Permission, Tool


class DesignGetFileTool(Tool):
    name = "design.get_file"
    description = (
        "Get a Penpot file's pages (id, name, shape count) - use this to find a "
        "page_id (or a board's shape id) before calling design.add_board/add_shape."
    )
    parameters = {"file_id": "string"}
    permission = Permission.SAFE

    def __init__(self, get_file_fn):
        self._get_file_fn = get_file_fn

    def execute(self, file_id):
        return self._get_file_fn(file_id)
