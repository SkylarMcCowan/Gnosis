from skills.conversation.recover import ConversationRecoverSkill
from skills.knowledge.maintain import KnowledgeMaintainSkill
from skills.repository.change_review import RepositoryChangeReviewSkill
from skills.research.verify import ResearchVerifySkill


class _Registry:
    def __init__(self):
        self.calls = []

    def execute(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return {"tool": name, **kwargs}


def test_conversation_recover_composes_inspection_and_optional_plan(monkeypatch):
    import skills.conversation.recover as module
    registry = _Registry()
    monkeypatch.setattr(module, "tool_registry", registry)

    result = ConversationRecoverSkill().execute(goal="finish this")

    assert result["conversation"]["tool"] == "conversation.inspect"
    assert result["plan"]["tool"] == "task.plan"
    assert [name for name, _ in registry.calls] == ["conversation.inspect", "task.plan"]


def test_research_verify_composes_evidence_tool(monkeypatch):
    import skills.research.verify as module
    registry = _Registry()
    monkeypatch.setattr(module, "tool_registry", registry)

    result = ResearchVerifySkill().execute("draft", "question", [])

    assert result["tool"] == "evidence.verify"
    assert registry.calls[0][1]["answer_text"] == "draft"


def test_knowledge_maintain_only_forgets_when_requested(monkeypatch):
    import skills.knowledge.maintain as module
    registry = _Registry()
    monkeypatch.setattr(module, "tool_registry", registry)

    result = KnowledgeMaintainSkill().execute("books")

    assert "related" in result and "forget" not in result
    assert [name for name, _ in registry.calls] == ["knowledge.related"]


def test_repository_change_review_runs_tests_only_when_requested(monkeypatch):
    import skills.repository.change_review as module
    registry = _Registry()
    monkeypatch.setattr(module, "tool_registry", registry)

    result = RepositoryChangeReviewSkill().execute(run_tests=True)

    assert result["tests"]["tool"] == "test.run"
    assert [name for name, _ in registry.calls] == ["repo.inspect", "test.run"]
