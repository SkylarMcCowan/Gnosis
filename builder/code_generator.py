"""DESIGN + GENERATE: ask an injected coding-chat function to design and
write a new Skill addressing a real, observed capability gap.
`coding_chat_fn(system_prompt, user_prompt) -> str|None` matches
webagent.py's own `_selfimprove_coding_chat` shape - this module never
imports webagent.py.
"""
import re

_FILE_BLOCK_RE = re.compile(r"###\s*(\S+)\s*\n")


def parse_file_block(raw, expected_path):
    """Parse a `### {expected_path}` + fenced code block from a model
    response. Returns the block's content, or None. A small,
    self-contained copy of webagent.py's `_parse_single_file_block` - kept
    separate rather than shared, since this module must never import
    webagent.py."""
    if not raw:
        return None
    match = None
    for candidate in _FILE_BLOCK_RE.finditer(raw):
        if candidate.group(1) == expected_path:
            match = candidate
            break
    if not match:
        return None
    after_header = raw[match.end():]
    fence_start = after_header.find("```")
    if fence_start == -1:
        return None
    after_fence = after_header[fence_start + 3:]
    newline_idx = after_fence.find("\n")
    if newline_idx != -1 and after_fence[:newline_idx].strip().isalpha():
        after_fence = after_fence[newline_idx + 1:]
    fence_end = after_fence.find("```")
    if fence_end == -1:
        return None
    return after_fence[:fence_end]


def slug_for_gap(gap_description):
    """A short, filesystem/identifier-safe slug for a gap description -
    shared by the module filename, skill name, and class name so all three
    obviously belong to the same generated artifact."""
    return re.sub(r"[^a-z0-9]+", "_", gap_description.lower()).strip("_")[:40] or "gap"


def generate_skill_for_gap(finding, coding_chat_fn, available_tools):
    """`finding` is one of learning.critic's finding dicts. `available_tools`
    is a real, current list of (name, description) pairs - the generated
    skill is only ever told about tools that actually exist right now, never
    a guess. Returns (module_name, class_name, code, reason) - code is None
    with a reason on any failure to parse a usable response."""
    gap_description = finding.get("summary", str(finding))
    slug = slug_for_gap(gap_description)
    module_name = f"generated_{slug}"
    class_name = "".join(word.capitalize() for word in slug.split("_")) + "Skill"
    skill_name = f"generated.{slug}"
    tools_listing = "\n".join(f"- {name}: {desc}" for name, desc in available_tools)

    system_prompt = (
        "You are designing a new Gnosis Skill to address a real, observed capability gap. "
        "A Skill is a Python class (subclassing skills.base.Skill) with class attributes name, "
        "description, parameters (a dict of {arg_name: description}), and required_tools (a "
        "tuple of tool names it calls), plus an execute(self, **kwargs) method. It composes "
        "already-registered tools by calling tool_registry.execute(tool_name, **kwargs) - import "
        "it as `from tools.registry import registry as tool_registry`. It must NEVER import "
        "webagent, and must never do raw file I/O, subprocess calls, or network requests itself - "
        "only ever through tool_registry.execute(...).\n\n"
        f"Only these tools exist and may be named in required_tools or called:\n{tools_listing}\n\n"
        "Respond with ONE complete Python file's content (the whole file, not a snippet or a diff) "
        "formatted as:\n\n"
        f"### {module_name}.py\n```python\n<full file content>\n```\n\n"
        f"The file must define exactly one class named {class_name}, subclassing skills.base.Skill, "
        f"with name = {skill_name!r}. Output nothing else - no explanation before or after."
    )
    user_prompt = f"Observed capability gap:\n{gap_description}\n\nDesign and generate a skill to address this."
    raw = coding_chat_fn(system_prompt, user_prompt)
    code = parse_file_block(raw, f"{module_name}.py")
    if code is None:
        return None, None, None, "could not parse a valid skill file from the model's response"
    return module_name, class_name, code, None
