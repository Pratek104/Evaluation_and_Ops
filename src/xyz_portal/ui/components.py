"""Reusable chat rendering components."""

from __future__ import annotations

import streamlit as st

from ..constants import MODEL_LABELS
from ..formatting import format_pages


def render_sources(sources: list[dict]) -> None:
    """Render the retrieved passages behind an assistant answer."""
    if not sources:
        return

    with st.expander(
        f"Sources · {len(sources)} passages · "
        f"{format_pages([source['page'] for source in sources])}",
        icon=":material/description:",
    ):
        for number, source in enumerate(sources, start=1):
            text = source["text"]
            excerpt = text[:520].rstrip()
            if len(text) > 520:
                excerpt += "…"
            st.markdown(
                f"**Passage {number}** · page {source['page']} · "
                f"relevance {source['score']:.2f}"
            )
            st.caption(excerpt)


def render_reasoning(reasoning: str) -> None:
    """Render the model's optional reasoning trace."""
    if not reasoning.strip():
        return
    with st.status(
        "Model reasoning",
        state="complete",
        expanded=False,
        type="compact",
    ):
        st.markdown(reasoning)


def render_message(message: dict) -> None:
    """Render one persisted chat message."""
    role = message["role"]
    avatar = ":material/menu_book:" if role == "assistant" else None
    with st.chat_message(role, avatar=avatar):
        if role == "assistant":
            render_reasoning(message.get("reasoning", ""))
        st.markdown(message["content"])
        if role == "assistant":
            render_sources(message.get("sources", []))
            if message.get("model"):
                label = MODEL_LABELS.get(message["model"], message["model"])
                st.caption(f"Answered with {label}")
