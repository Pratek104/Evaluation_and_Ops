"""Prompt construction and retrieval-query helpers for the handbook chat."""

from __future__ import annotations

from typing import Any

from .auth import handbook_scope
from .constants import SCOPE_LABELS, SYSTEM_PROMPT
from .rag import SearchResult


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
) -> list[dict[str, str]]:
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
    )
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": f"{SYSTEM_PROMPT}{user_context}\nHANDBOOK PASSAGES\n{context}",
        }
    ]
    for message in history[-6:]:
        if message.get("role") in ("user", "assistant") and message.get("content"):
            messages.append({"role": message["role"], "content": message["content"]})
    messages.append({"role": "user", "content": question})
    return messages
