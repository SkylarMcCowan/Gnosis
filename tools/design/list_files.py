from tools.base import Permission, Tool


class DesignListFilesTool(Tool):
    name = "design.list_files"
    description = "List the files inside a Penpot project."
    parameters = {"project_id": "string"}
    permission = Permission.SAFE

    def __init__(self, list_files_fn):
        self._list_files_fn = list_files_fn

    def execute(self, project_id):
        return self._list_files_fn(project_id)
