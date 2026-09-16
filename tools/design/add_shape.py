from tools.base import Permission, Tool


class DesignAddShapeTool(Tool):
    name = "design.add_shape"
    description = "Add a rectangle, circle, or text shape to a Penpot file's page (or inside a specific board)."
    parameters = {
        "file_id": "string",
        "shape_type": "string ('rect' | 'circle' | 'text')",
        "page_id": "string, optional (defaults to the file's first page)",
        "board_id": "string, optional (nest inside this board's shape id rather than the page root)",
        "x": "number, optional",
        "y": "number, optional",
        "width": "number, optional",
        "height": "number, optional",
        "fill_color": "string, optional (hex, e.g. '#FF0000')",
        "text": "string, optional (only used when shape_type is 'text')",
        "font_size": "number, optional",
        "name": "string, optional",
    }
    permission = Permission.RESTRICTED

    def __init__(self, add_shape_fn):
        self._add_shape_fn = add_shape_fn

    def execute(self, file_id, shape_type, page_id=None, board_id=None, x=0, y=0, width=100, height=100,
                fill_color=None, text=None, font_size=16, name=None):
        return self._add_shape_fn(
            file_id, shape_type, page_id=page_id, board_id=board_id, x=x, y=y, width=width, height=height,
            fill_color=fill_color, text=text, font_size=font_size, name=name,
        )
