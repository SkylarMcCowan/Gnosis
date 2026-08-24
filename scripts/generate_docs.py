"""Regenerates docs/tools.md, docs/skills.md, docs/architecture.md, and
docs/commands.md from real, current state - the registries, each
package's own docstring, and /help's real output. Run this after adding a
tool/skill or changing a package's docstring; tests/test_docgen_freshness.py
fails if these files fall out of sync with what this script would produce.

    python3 scripts/generate_docs.py
"""
import importlib
import io
import os
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from docgen.architecture_doc import generate_architecture_doc
from docgen.commands_doc import generate_commands_doc
from docgen.skills_doc import generate_skills_doc
from docgen.tools_doc import generate_tools_doc

_ARCHITECTURE_PACKAGES = [
    "core", "tools", "skills", "memory", "learning", "planning",
    "sandbox", "builder", "reviewers", "observability", "docgen", "governance",
]


def main():
    import webagent  # noqa: E402  (deliberately deferred - only this script may import webagent.py)

    docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

    tools_doc = generate_tools_doc(webagent.tool_registry.list())
    skills_doc = generate_skills_doc(webagent.skill_registry.list())

    package_docs = {name: importlib.import_module(name).__doc__ for name in _ARCHITECTURE_PACKAGES}
    architecture_doc = generate_architecture_doc(package_docs)

    help_output = io.StringIO()
    with redirect_stdout(help_output):
        webagent._cmd_help("/help")
    commands_doc = generate_commands_doc(help_output.getvalue())

    for filename, content in (
        ("tools.md", tools_doc), ("skills.md", skills_doc),
        ("architecture.md", architecture_doc), ("commands.md", commands_doc),
    ):
        with open(os.path.join(docs_dir, filename), "w", encoding="utf-8") as f:
            f.write(content)
    print(f"Regenerated tools.md, skills.md, architecture.md, commands.md in {docs_dir}")


if __name__ == "__main__":
    main()
