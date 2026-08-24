"""Generates an architecture map from each top-level package's own
docstring - the same docstrings written throughout this project specifically
to explain what belongs in a package and why, not new prose invented here.
"""

HEADER = "# Architecture\n\nGenerated from each package's own docstring - do not hand-edit; run `python3 scripts/generate_docs.py` instead.\n"


def generate_architecture_doc(package_docs):
    """`package_docs` is a real {package_name: docstring} dict, injected
    rather than gathered here via import - the caller (scripts/generate_docs.py)
    is the one place trusted to import every package just to read its
    __doc__."""
    lines = [HEADER]
    for package_name in sorted(package_docs):
        doc = (package_docs[package_name] or "").strip()
        first_paragraph = doc.split("\n\n")[0].strip() if doc else "(no module docstring)"
        # Collapse the docstring's own line-wrapping into one flowing paragraph.
        first_paragraph = " ".join(line.strip() for line in first_paragraph.splitlines())
        lines.append(f"\n## `{package_name}/`\n")
        lines.append(first_paragraph)
    return "\n".join(lines) + "\n"
