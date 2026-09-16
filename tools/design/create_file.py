from tools.base import Permission, Tool


class DesignCreateFileTool(Tool):
    name = "design.create_file"
    description = "Create a new (empty, single-page) Penpot file inside a project."
    parameters = {"project_id": "string", "name": "string"}
    permission = Permission.RESTRICTED

    def __init__(self, create_file_fn):
        self._create_file_fn = create_file_fn

    def execute(self, project_id, name):
        return self._create_file_fn(project_id, name)
