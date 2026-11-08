"""Handbook assistant page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from ... import auth
from ...chat import build_llm_messages, make_retrieval_query
from ...config import API_KEY, DEFAULT_MODEL, PDF_PATH
from ...constants import MODEL_LABELS, SCOPE_LABELS, SUGGESTIONS
from ...rag import (
    PROJECT_NAME,
    TRACING_ENABLED,
    TRACING_STATUS,
    OpenRouterError,
    RagEngine,
    is_free_model,
    stream_chat,
    supports_reasoning,
    trace_run,
)
from ..components import render_message, render_reasoning, render_sources


@st.cache_resource(show_spinner=False)
def load_engine(pdf_path: str, file_signature: str) -> RagEngine:
    """Build the index once per PDF version and share it across sessions."""
    del file_signature  # Only used to invalidate the cache.
    return RagEngine.load(Path(pdf_path))


def _render_chat_sidebar():
    """Render assistant settings and return the selected controls."""
    with st.sidebar:
        st.divider()
        st.markdown("#### Assistant settings")
        stats_slot = st.container()

        model_options = list(MODEL_LABELS)
        if DEFAULT_MODEL not in model_options:
            model_options.insert(0, DEFAULT_MODEL)
        default_index = model_options.index(DEFAULT_MODEL)

        selected_model = st.selectbox(
            "Answer model",
            options=model_options,
            index=default_index,
            format_func=lambda model: MODEL_LABELS.get(model, model),
            help="Free models may be rate-limited. Gemma 3 models are paid.",
        )

        reasoning_available = supports_reasoning(selected_model)
        use_reasoning = st.toggle(
            "Extended reasoning",
            value=True,
            disabled=not reasoning_available,
            help=(
                "Let the model reason before answering. Available on Gemma 4 and "
                "Nemotron 3 Ultra."
            ),
        )
        if not reasoning_available:
            st.caption(
                "Extended reasoning is only available on Gemma 4 and Nemotron 3 Ultra."
            )

        top_k = st.slider(
            "Passages to retrieve",
            min_value=3,
            max_value=8,
            value=5,
            help="More passages give broader context but use more tokens.",
        )

        st.space("small")
        clear_col, rebuild_col = st.columns(2)
        if clear_col.button(
            "Clear chat",
            icon=":material/delete:",
            width="stretch",
            disabled=not st.session_state.messages,
        ):
            st.session_state.messages = []
            st.rerun()
        if rebuild_col.button(
            "Rebuild index",
            icon=":material/refresh:",
            width="stretch",
            help="Re-read the PDF and recompute embeddings.",
        ):
            RagEngine.clear_cache(PDF_PATH)
            load_engine.clear()
            st.rerun()

        st.space("small")
        st.caption(
            "Answers are generated only from the handbook sections available "
            "to your role."
        )

    return (
        selected_model,
        use_reasoning,
        reasoning_available,
        top_k,
        stats_slot,
    )


def _render_engine_status(engine: RagEngine, stats_slot: Any) -> None:
    """Render the index and tracing status in the assistant sidebar."""
    with stats_slot, st.container(border=True):
        st.markdown(f"**{PDF_PATH.name}**")
        st.caption(
            f"{engine.page_count} pages · {len(engine.passages)} searchable passages"
        )
        if engine.embedding_error:
            st.badge(
                "Keyword search",
                icon=":material/search:",
                color="orange",
            )
        else:
            st.badge(
                "Hybrid search",
                icon=":material/bolt:",
                color="green",
            )
        st.badge(
            f"LangSmith · {PROJECT_NAME}" if TRACING_ENABLED else "LangSmith off",
            icon=":material/timeline:",
            color="green" if TRACING_ENABLED else "gray",
            help=TRACING_STATUS,
        )


def _handle_prompt(
    prompt: str,
    user: dict[str, Any],
    engine: RagEngine,
    selected_model: str,
    use_reasoning: bool,
    reasoning_available: bool,
    top_k: int,
    scope: str,
) -> None:
    """Retrieve passages, stream one answer, and persist the turn."""
    history = st.session_state.messages
    history_turns = sum(1 for message in history if message["role"] == "user")
    retrieval_query = make_retrieval_query(prompt, history)
    st.session_state.messages.append({"role": "user", "content": prompt})

    turn_inputs = {
        "question": prompt,
        "retrieval_query": retrieval_query,
        "model": selected_model,
        "top_k": top_k,
        "reasoning": bool(use_reasoning and reasoning_available),
        "history_turns": history_turns,
        "employee_id": user["employee_id"],
        "role": user["role"],
        "access_scope": scope,
    }

    with trace_run(
        "handbook_chat",
        run_type="chain",
        inputs=turn_inputs,
        tags=["streamlit", "rag", f"role:{user['role'].lower()}"],
    ) as run:
        turn_output: dict[str, Any] = {"status": "incomplete"}

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant", avatar=":material/menu_book:"):
            with st.status("Searching the handbook", type="compact") as search_status:
                results = engine.search(
                    retrieval_query,
                    top_k=top_k,
                    access_scope=scope,
                )
                search_status.update(
                    label=f"Found {len(results)} passages available to your role",
                    state="complete",
                )

            sources = [
                {
                    "page": result.passage.page,
                    "score": result.score,
                    "text": result.passage.text,
                }
                for result in results
            ]
            pages = sorted({source["page"] for source in sources})

            if not results:
                answer = (
                    "I couldn't find that in the handbook sections available "
                    "to your role. Try rephrasing with a policy or section "
                    "name, or contact HR if you need access."
                )
                st.markdown(answer)
                turn_output = {
                    "status": "no_results",
                    "answer": answer,
                    "retrieved": 0,
                    "pages": [],
                    "access_scope": scope,
                }
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": answer,
                        "sources": [],
                        "reasoning": "",
                        "model": "",
                    }
                )
            else:
                llm_messages = build_llm_messages(
                    prompt,
                    st.session_state.messages[:-1],
                    results,
                    user,
                )
                stream_state: dict[str, Any] = {
                    "reasoning": [],
                    "content": [],
                    "notices": [],
                    "model": selected_model,
                }
                reasoning_slot = st.empty()

                def token_stream():
                    for kind, value in stream_chat(
                        selected_model,
                        llm_messages,
                        API_KEY,
                        reasoning=use_reasoning and reasoning_available,
                        allow_free_fallback=is_free_model(selected_model),
                    ):
                        if kind == "reasoning":
                            stream_state["reasoning"].append(value)
                        elif kind == "content":
                            stream_state["content"].append(value)
                            yield value
                        elif kind == "notice":
                            stream_state["notices"].append(value)
                        elif kind == "model":
                            stream_state["model"] = value

                try:
                    st.write_stream(token_stream())
                    answer = "".join(stream_state["content"]).strip()
                    reasoning = "".join(stream_state["reasoning"])

                    if not answer:
                        answer = (
                            "The model did not return an answer. Please try again or "
                            "pick another model."
                        )
                        st.markdown(answer)

                    with reasoning_slot:
                        render_reasoning(reasoning)

                    for notice in stream_state["notices"]:
                        st.caption(notice)

                    render_sources(sources)
                    used_model = stream_state["model"]
                    st.caption(
                        f"Answered with {MODEL_LABELS.get(used_model, used_model)}"
                    )

                    turn_output = {
                        "status": "ok",
                        "answer": answer,
                        "used_model": used_model,
                        "retrieved": len(sources),
                        "pages": pages,
                        "reasoning_chars": len(reasoning),
                        "fallback_notices": stream_state["notices"],
                        "access_scope": scope,
                    }

                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": answer,
                            "sources": sources,
                            "reasoning": reasoning,
                            "model": used_model,
                        }
                    )
                except OpenRouterError as exc:
                    with reasoning_slot:
                        render_reasoning("".join(stream_state["reasoning"]))
                    st.error(str(exc), title="Model request failed")

                    partial = "".join(stream_state["content"]).strip()
                    turn_output = {
                        "status": "error",
                        "error": str(exc),
                        "used_model": stream_state["model"],
                        "partial_answer": partial,
                        "retrieved": len(sources),
                        "pages": pages,
                        "reasoning_chars": len("".join(stream_state["reasoning"])),
                        "access_scope": scope,
                    }
                    if partial:
                        st.session_state.messages.append(
                            {
                                "role": "assistant",
                                "content": partial
                                + "\n\n_(The response was interrupted.)_",
                                "sources": sources,
                                "reasoning": "".join(stream_state["reasoning"]),
                                "model": stream_state["model"],
                            }
                        )

        run.end(outputs=turn_output)


def render(user: dict[str, Any]) -> None:
    """Render the role-scoped handbook assistant."""
    if not auth.has_permission(user, "handbook:read"):
        st.error("The handbook assistant is not available for your role.")
        return

    (
        selected_model,
        use_reasoning,
        reasoning_available,
        top_k,
        stats_slot,
    ) = _render_chat_sidebar()

    scope = auth.handbook_scope(user)
    st.title("Ask the handbook")
    st.caption(f"{user['name']} · {user['role_label']} · Access: {SCOPE_LABELS[scope]}")

    if not API_KEY:
        st.error(
            "Add `OPENROUTER_API_KEY` to the project `.env` file, then restart "
            "the app.",
            title="API key missing",
        )
        st.stop()

    if not PDF_PATH.exists():
        st.error(
            f"Could not find `{PDF_PATH.name}` at `{PDF_PATH}`. Add the PDF or "
            "update `PDF_PATH` in `.env`.",
            title="PDF missing",
        )
        st.stop()

    file_signature = f"{PDF_PATH.stat().st_mtime_ns}-{PDF_PATH.stat().st_size}"
    try:
        with st.spinner("Reading the handbook and building the search index…"):
            engine = load_engine(str(PDF_PATH), file_signature)
    except Exception as exc:
        st.error(
            f"Could not index `{PDF_PATH.name}`: {exc}",
            title="Indexing failed",
        )
        st.stop()

    _render_engine_status(engine, stats_slot)

    for message in st.session_state.messages:
        render_message(message)

    suggestions = dict(SUGGESTIONS)
    if scope == "directory":
        suggestions["Directory"] = "Who reports to Priya Nair?"
    elif scope == "full":
        suggestions["Payroll"] = (
            "What is the total monthly salary for all 15 employees?"
        )

    selected_suggestion = None
    empty_state = None
    if not st.session_state.messages:
        st.space("small")
        empty_state = st.empty()
        with empty_state.container(border=True):
            st.markdown("#### Start with a question")
            st.caption(
                "Each answer is retrieved from the handbook and cites the page it "
                "came from. Restricted appendix content is never retrieved for "
                "roles that cannot access it."
            )
            chosen = st.pills(
                "Suggested questions",
                options=list(suggestions),
                label_visibility="collapsed",
                width="stretch",
            )
            if chosen:
                selected_suggestion = suggestions[chosen]

    prompt = st.chat_input(
        "Ask about leave, travel, pay…",
        submit_mode="disable",
    )
    if not prompt and selected_suggestion:
        prompt = selected_suggestion

    if prompt:
        if empty_state is not None:
            empty_state.empty()
        _handle_prompt(
            prompt,
            user,
            engine,
            selected_model,
            use_reasoning,
            reasoning_available,
            top_k,
            scope,
        )
