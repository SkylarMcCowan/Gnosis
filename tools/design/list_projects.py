from tools.base import Permission, Tool


class DesignListProjectsTool(Tool):
    name = "design.list_projects"
    description = "List the Penpot projects in the connected instance's default team."
    parameters = {}
    permission = Permission.SAFE

    def __init__(self, list_projects_fn):
        self._list_projects_fn = list_projects_fn

    def execute(self):
        return self._list_projects_fn()
