"""research.topic: the roadmap's own Phase 3 example skill -
`web.search -> web.fetch -> knowledge.search -> knowledge.write` composed
into one named, reusable capability.

Checks the knowledge base first so a topic already researched doesn't
trigger a redundant web search. Only on a miss does it search the web,
fetch the top result's full page content (falling back to the search
result's own snippet if the fetch comes back empty - a fetch failure
shouldn't blank out a perfectly usable result), and write that content to
the knowledge base under a stable filename derived from the topic, so the
next call to research.topic (or a plain /archives lookup) finds it.
"""
import string

from skills.base import Skill
from tools.registry import registry as tool_registry

_VALID_FILENAME_CHARS = f"-_.() {string.ascii_letters}{string.digits}"


def _filename_for_topic(topic):
    cleaned = "".join(c for c in topic if c in _VALID_FILENAME_CHARS).replace(" ", "_")
    return f"research_{cleaned}.txt"


class ResearchTopicSkill(Skill):
    name = "research.topic"
    description = "Research a topic: reuse existing knowledge if present, otherwise search the web and record findings."
    parameters = {"topic": "string"}
    required_tools = ("web.search", "web.fetch", "knowledge.search", "knowledge.write")

    def execute(self, topic):
        existing = tool_registry.execute("knowledge.search", topic=topic)
        if existing:
            return {"topic": topic, "source": "knowledge_base", "results": existing, "saved": False}

        search_results = tool_registry.execute("web.search", query=topic)
        if not search_results:
            return {"topic": topic, "source": "web", "results": [], "saved": False}

        top_result = search_results[0]
        content = None
        if top_result.get("url"):
            content = tool_registry.execute("web.fetch", url=top_result["url"])
        content = content or top_result.get("content", "")

        filename = _filename_for_topic(topic)
        saved = tool_registry.execute("knowledge.write", filename=filename, content=content)
        return {"topic": topic, "source": "web", "results": search_results, "saved": bool(saved), "filename": filename}
