"""Phase 14's "CI check for stale docs" / "Documentation tests": regenerates
docs/tools.md, docs/skills.md, docs/architecture.md, and docs/commands.md
using the exact same generators scripts/generate_docs.py uses, and fails if
the committed files don't match - the real, current registry/package
state is the source of truth; a stale doc means someone added a tool/skill
or changed a package docstring and forgot to re-run the script.
"""
import importlib
import io
import os
from contextlib import redirect_stdout

import webagent
from docgen.architecture_doc import generate_architecture_doc
from docgen.commands_doc import generate_commands_doc
from docgen.skills_doc import generate_skills_doc
from docgen.tools_doc import generate_tools_doc

_DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
_ARCHITECTURE_PACKAGES = [
    "core", "tools", "skills", "memory", "learning", "planning",
    "sandbox", "builder", "reviewers", "observability", "docgen", "governance",
]


def _committed(filename):
    with open(os.path.join(_DOCS_DIR, filename), "r", encoding="utf-8") as f:
        return f.read()


def test_tools_doc_is_up_to_date():
    generated = generate_tools_doc(webagent.tool_registry.list())
    assert generated == _committed("tools.md"), "docs/tools.md is stale - run `python3 scripts/generate_docs.py`"


def test_skills_doc_is_up_to_date():
    generated = generate_skills_doc(webagent.skill_registry.list())
    assert generated == _committed("skills.md"), "docs/skills.md is stale - run `python3 scripts/generate_docs.py`"


def test_architecture_doc_is_up_to_date():
    package_docs = {name: importlib.import_module(name).__doc__ for name in _ARCHITECTURE_PACKAGES}
    generated = generate_architecture_doc(package_docs)
    assert generated == _committed("architecture.md"), "docs/architecture.md is stale - run `python3 scripts/generate_docs.py`"


def test_commands_doc_is_up_to_date():
    help_output = io.StringIO()
    with redirect_stdout(help_output):
        webagent._cmd_help("/help")
    generated = generate_commands_doc(help_output.getvalue())
    assert generated == _committed("commands.md"), "docs/commands.md is stale - run `python3 scripts/generate_docs.py`"
