"""Generates a command reference from /help's own real output - the
single source of truth users already see, not a second, separately
maintained list that could drift from it.
"""

HEADER = "# Commands\n\nGenerated from `/help`'s real output - do not hand-edit; run `python3 scripts/generate_docs.py` instead.\n\n"


def generate_commands_doc(help_text):
    """`help_text` is /help's real captured stdout, injected - this module
    never calls into webagent.py itself."""
    return HEADER + "```text\n" + help_text.strip() + "\n```\n"
