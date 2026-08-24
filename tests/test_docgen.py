"""Regression tests for docgen/*.py's generators - all pure functions over
injected data, no real registry/webagent dependency needed.
"""
from docgen.architecture_doc import generate_architecture_doc
from docgen.commands_doc import generate_commands_doc
from docgen.skills_doc import generate_skills_doc
from docgen.tools_doc import generate_tools_doc


class _FakeTool:
    def __init__(self, name, description, permission, parameters=None):
        self.name = name
        self.description = description
        self.permission = permission
        self.parameters = parameters or {}


class _FakeSkill:
    def __init__(self, name, description, permission, required_tools=(), parameters=None):
        self.name = name
        self.description = description
        self.required_tools = required_tools
        self.parameters = parameters or {}
        self._permission = permission

    def resolved_permission(self):
        return self._permission


def test_generate_tools_doc_includes_every_tool_sorted_by_name():
    tools = [
        _FakeTool("web.search", "Search the web.", "SAFE", {"query": "string"}),
        _FakeTool("cron.add", "Add a cron task.", "REQUIRES_APPROVAL"),
    ]
    doc = generate_tools_doc(tools)
    assert doc.index("## `cron.add`") < doc.index("## `web.search`")
    assert "Search the web." in doc
    assert "REQUIRES_APPROVAL" in doc
    assert "`query`: string" in doc


def test_generate_tools_doc_with_no_tools():
    doc = generate_tools_doc([])
    assert "# Tools" in doc
    assert "##" not in doc


def test_generate_skills_doc_includes_composed_tools():
    skills = [_FakeSkill("research.topic", "Research a topic.", "SAFE", required_tools=("web.search", "web.fetch"))]
    doc = generate_skills_doc(skills)
    assert "## `research.topic`" in doc
    assert "`web.search`" in doc
    assert "`web.fetch`" in doc


def test_generate_architecture_doc_uses_the_first_paragraph_of_each_docstring():
    package_docs = {
        "tools": "First paragraph about tools.\n\nSecond paragraph, not included.",
        "skills": "Only one paragraph about skills.",
    }
    doc = generate_architecture_doc(package_docs)
    assert "First paragraph about tools." in doc
    assert "Second paragraph, not included." not in doc
    assert "Only one paragraph about skills." in doc


def test_generate_architecture_doc_handles_a_missing_docstring():
    doc = generate_architecture_doc({"mystery": None})
    assert "(no module docstring)" in doc


def test_generate_architecture_doc_sorts_packages_alphabetically():
    doc = generate_architecture_doc({"zeta": "z doc", "alpha": "a doc"})
    assert doc.index("## `alpha/`") < doc.index("## `zeta/`")


def test_generate_commands_doc_wraps_the_real_help_text():
    doc = generate_commands_doc("/help - show this message\n/exit - quit")
    assert "/help - show this message" in doc
    assert "/exit - quit" in doc
    assert "```text" in doc
