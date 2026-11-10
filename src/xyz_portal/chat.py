"""Prompt construction and retrieval-query helpers for the handbook chat."""

from __future__ import annotations

from datetime import date
from typing import Any

from .auth import handbook_scope
from .constants import SCOPE_LABELS, SYSTEM_PROMPT
from .rag import SearchResult

LEAVE_TOOL_PROMPT = """You can also handle leave requests and HR decisions with the \
provided tools. This workflow is an exception to the handbook-only rule above: use \
tool results for leave actions, and use handbook passages for leave policy.

Leave workflow rules:
1. When the employee asks to apply for leave, collect the leave type, start date, \
end date, and reason. Ask one concise follow-up question for anything missing. \
Never invent dates, reasons, or leave types.
2. If the employee gives only a duration, ask for the start date or confirm the \
computed end date before submitting.
3. Before calling submit_leave_request, restate the leave type, dates, and reason, \
and ask for explicit confirmation.
4. Call submit_leave_request only after confirmation. On success, show the formatted \
letter returned by the tool, state the reference number, and say it is in the HR \
inbox. If the tool fails, explain the error and ask for the missing detail.
5. Use list_my_leave_requests or get_leave_request when the employee asks about \
existing requests.
6. HR users may use get_hr_inbox and decide_leave_request. Confirm the decision \
first, and never approve the approver's own request.
7. Never claim a leave request was submitted or decided unless the corresponding \
tool returned ok=true.
8. Do not present tool output as a handbook citation. Cite handbook pages only for \
policy statements that come from the supplied passages.
"""


def make_retrieval_query(question: str, history: list[dict[str, Any]]) -> str:
    """Add the previous question to short follow-ups for better retrieval."""
    previous_questions = [
        message["content"] for message in history if message["role"] == "user"
    ]
    if not previous_questions:
        return question

    lowered = question.lower().strip()
    follow_up_starts = (
        "what about",
        "how about",
        "what if",
        "does that",
        "is that",
        "and ",
        "then ",
    )
    pronouns = (
        " it",
        " its",
        " them",
        " they",
        " that",
        " those",
        " this",
        " these",
    )
    refers_back = any(marker in f" {lowered}" for marker in pronouns)
    if (
        len(question.split()) <= 4
        or lowered.startswith(follow_up_starts)
        or refers_back
    ):
        return f"{previous_questions[-1]} {question}"
    return question


def build_llm_messages(
    question: str,
    history: list[dict[str, Any]],
    results: list[SearchResult],
    user: dict[str, Any],
    *,
    include_leave_tools: bool = False,
) -> list[dict[str, Any]]:
    """Create the grounded prompt sent to the model."""
    context = "\n\n".join(
        f"[Passage {number} | page {result.passage.page}]\n{result.passage.text}"
        for number, result in enumerate(results, start=1)
    )
    user_context = (
        "\n\nSIGNED-IN USER\n"
        f"Name: {user['name']}\n"
        f"Role: {user['role_label']} ({user['role']})\n"
        f"Department: {user['department']}\n"
        f"Handbook access scope: {SCOPE_LABELS[handbook_scope(user)]}\n"
        f"Current date: {date.today().isoformat()}\n"
    )
    system_prompt = f"{SYSTEM_PROMPT}{user_context}\nHANDBOOK PASSAGES\n{context}"
    if include_leave_tools:
        system_prompt = f"{system_prompt}\n\n{LEAVE_TOOL_PROMPT}"

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]
    for message in history[-6:]:
        if message.get("role") in ("user", "assistant") and message.get("content"):
            messages.append({"role": message["role"], "content": message["content"]})
    messages.append({"role": "user", "content": question})
    return messages
