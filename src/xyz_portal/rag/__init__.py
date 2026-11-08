"""Role-scoped retrieval, OpenRouter streaming, and LangSmith tracing."""

from __future__ import annotations

from .engine import (
    ACCESS_SCOPES,
    PUBLIC_HANDBOOK_LAST_PAGE,
    Passage,
    RagEngine,
    SearchResult,
    passage_access_level,
    scope_allows,
)
from .openrouter import (
    OpenRouterError,
    is_free_model,
    stream_chat,
    supports_reasoning,
)
from .tracing import (
    PROJECT_NAME,
    TRACING_ENABLED,
    TRACING_STATUS,
    trace_run,
    traceable,
)

__all__ = [
    "ACCESS_SCOPES",
    "PROJECT_NAME",
    "PUBLIC_HANDBOOK_LAST_PAGE",
    "TRACING_ENABLED",
    "TRACING_STATUS",
    "OpenRouterError",
    "Passage",
    "RagEngine",
    "SearchResult",
    "is_free_model",
    "passage_access_level",
    "scope_allows",
    "stream_chat",
    "supports_reasoning",
    "trace_run",
    "traceable",
]
