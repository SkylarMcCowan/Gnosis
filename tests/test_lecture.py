import pytest

import webagent
from core.exceptions import ChatCancelled
from core.lecture import create_lecture


def test_lecture_multiple_searches_writes_and_sources(tmp_path):
    queries, requests, output = [], [], []

    def search(query):
        queries.append(query)
        return [{"title": "Reference", "url": "https://example.org/source", "content": "Evidence"}]

    def stream(messages):
        requests.append(messages)
        yield f"Explanation {len(requests)}."

    response, evidence, path = create_lecture(
        "Stars", plan=lambda _: None, search=search, stream=stream,
        output_dir=tmp_path, on_chunk=output.append, on_status=lambda _: None,
    )
    assert len(set(queries)) == len(requests) == 6
    assert len(evidence) == 1
    assert response == "".join(output) == path.read_text()
    assert "Explanation 1." in requests[1][1]["content"]
    assert "https://example.org/source" in requests[0][1]["content"]
    assert response.count("## Sources consulted") == 1


def test_cancel_retains_partial_draft_and_closes_stream(tmp_path):
    closed = []

    def stream(messages):
        try:
            yield "Completed paragraph."
            raise ChatCancelled()
        finally:
            closed.append(True)

    with pytest.raises(ChatCancelled):
        create_lecture("../Stars", plan=lambda _: {}, search=lambda _: [], stream=stream,
                       output_dir=tmp_path, on_chunk=lambda _: None, on_status=lambda _: None)
    draft, = tmp_path.glob("*.md")
    assert "Completed paragraph." in draft.read_text()
    assert "incomplete draft" in draft.read_text()
    assert "No live sources" in draft.read_text()
    assert closed == [True]


def test_command_shared_with_gui_and_terminal(monkeypatch, tmp_path):
    monkeypatch.setattr(webagent, "_selected_model", lambda: "test-model")
    monkeypatch.setattr(webagent.agent_dialogue, "call_agent_json", lambda *a, **kw: None)
    monkeypatch.setattr(webagent.tool_registry, "execute", lambda *a, **kw: [])
    monkeypatch.setattr(webagent, "model_chat", lambda **kw: iter([{"message": {"content": "Detailed prose."}}]))
    chunks, sources = [], []
    answer = webagent._chat_response_impl("/lecture Stars", chunks.append, sources.append)
    assert answer == "".join(chunks)
    assert answer.count("Detailed prose.") == 6
    assert sources == [[]]
    assert webagent.context.assistant_convo[-1]["content"] == answer
    assert webagent._COMMAND_ROUTER.dispatch("/lecture")
    assert not webagent._COMMAND_ROUTER.dispatch("/lectures")


def test_empty_model_response_leaves_incomplete_file(tmp_path):
    with pytest.raises(RuntimeError, match="no text"):
        create_lecture("Stars", plan=lambda _: {}, search=lambda _: [], stream=lambda _: iter([]),
                       output_dir=tmp_path, on_chunk=lambda _: None, on_status=lambda _: None)
    assert "incomplete draft" in next(tmp_path.glob("*.md")).read_text()


def test_lecture_keeps_user_context_in_plan_search_and_sections(tmp_path):
    plans, queries, messages = [], [], []
    context = "Discuss the Hermetic Order of the Golden Dawn and Crowley."
    def stream(request):
        messages.append(request)
        yield "Lecture text."
    create_lecture("Golden Dawn", topic_context=context,
                   plan=plans.append, search=lambda q: queries.append(q) or [],
                   stream=stream, output_dir=tmp_path, on_chunk=lambda _: None,
                   on_status=lambda _: None)
    assert context in plans[0]
    assert all(context in query for query in queries)
    assert all(context in request[1]["content"] for request in messages)
