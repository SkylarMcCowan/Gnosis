"""Generates a skill reference from real Skill instances - same pattern as
docgen/tools_doc.py.
"""

HEADER = "# Skills\n\nGenerated from the real skill registry - do not hand-edit; run `python3 scripts/generate_docs.py` instead.\n"


def generate_skills_doc(skills):
    """`skills` is a real list of Skill instances (e.g. skill_registry.list()),
    injected rather than imported."""
    lines = [HEADER]
    for skill in sorted(skills, key=lambda s: s.name):
        lines.append(f"\n## `{skill.name}`\n")
        lines.append(f"{skill.description}\n")
        lines.append(f"- Permission: `{skill.resolved_permission()}`")
        if skill.required_tools:
            lines.append(f"- Composes: {', '.join(f'`{name}`' for name in skill.required_tools)}")
        if skill.parameters:
            lines.append("- Parameters:")
            for name, description in skill.parameters.items():
                lines.append(f"  - `{name}`: {description}")
    return "\n".join(lines) + "\n"
