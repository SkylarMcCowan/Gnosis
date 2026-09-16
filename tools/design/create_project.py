from tools.base import Permission, Tool


class DesignCreateProjectTool(Tool):
    name = "design.create_project"
    description = "Create a new Penpot project in the connected instance's default team."
    parameters = {"name": "string"}
    permission = Permission.RESTRICTED

    def __init__(self, create_project_fn):
        self._create_project_fn = create_project_fn

    def execute(self, name):
        return self._create_project_fn(name)
