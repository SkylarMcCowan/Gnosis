from tools.base import Permission
from tools.evidence.verify import EvidenceVerifyTool


def test_evidence_verify_tool_forwards_all_inputs():
    calls = []

    def verify(answer_text, evidence, user_prompt=""):
        calls.append((answer_text, evidence, user_prompt))
        return {"has_findings": False}

    tool = EvidenceVerifyTool(verify)
    evidence = [{"url": "https://example.com"}]

    assert tool.permission == Permission.SAFE
    assert tool.execute("answer", "question", evidence) == {"has_findings": False}
    assert calls == [("answer", evidence, "question")]
