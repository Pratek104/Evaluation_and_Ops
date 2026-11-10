"""Prompt-building tests for the handbook assistant."""

from __future__ import annotations

from xyz_portal.chat import build_llm_messages, make_retrieval_query
from xyz_portal.rag import Passage, SearchResult
from xyz_portal.rag.openrouter import merge_tool_call_delta


def _user() -> dict:
    return {
        "name": "Karan Joshi",
        "role": "EMPLOYEE",
        "role_label": "Employee",
        "department": "Technology",
        "permissions": ("handbook:read",),
    }


def test_retrieval_query_uses_previous_question_for_follow_up() -> None:
    history = [{"role": "user", "content": "What is the probation period?"}]
    assert (
        make_retrieval_query("What about leave?", history)
        == "What is the probation period? What about leave?"
    )


def test_retrieval_query_keeps_standalone_question() -> None:
    history = [{"role": "user", "content": "What is the probation period?"}]
    question = "How do I claim domestic travel reimbursement?"
    assert make_retrieval_query(question, history) == question


def test_llm_messages_include_grounding_and_user_scope() -> None:
    results = [
        SearchResult(Passage(0, 7, "Employees receive 20 days of leave."), 0.9),
        SearchResult(Passage(1, 9, "Travel requires prior approval."), 0.8),
    ]
    messages = build_llm_messages(
        "How much leave do I get?",
        [{"role": "assistant", "content": "Hello"}],
        results,
        _user(),
    )
    system = messages[0]["content"]
    assert "[Passage 1 | page 7]" in system
    assert "General handbook only" in system
    assert "Karan Joshi" in system
    assert messages[-1] == {
        "role": "user",
        "content": "How much leave do I get?",
    }
    assert messages[1] == {"role": "assistant", "content": "Hello"}


def test_llm_messages_include_leave_tool_instructions() -> None:
    messages = build_llm_messages(
        "I want to apply for leave.",
        [],
        [],
        _user(),
        include_leave_tools=True,
    )
    system = messages[0]["content"]
    assert "submit_leave_request" in system
    assert "ask for explicit confirmation" in system
    assert "Current date:" in system


def test_merge_tool_call_delta_accumulates_streamed_arguments() -> None:
    calls: dict[int, dict] = {}
    merge_tool_call_delta(
        calls,
        [
            {
                "index": 0,
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "submit_leave_request",
                    "arguments": '{"leave_type":',
                },
            }
        ],
    )
    merge_tool_call_delta(
        calls,
        [
            {
                "index": 0,
                "function": {"arguments": '"Sick Leave"}'},
            }
        ],
    )
    assert calls[0]["id"] == "call_1"
    assert calls[0]["function"]["name"] == "submit_leave_request"
    assert calls[0]["function"]["arguments"] == '{"leave_type":"Sick Leave"}'
