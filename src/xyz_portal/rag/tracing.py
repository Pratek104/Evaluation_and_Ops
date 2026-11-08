"""LangSmith tracing configuration for the handbook assistant.

The app is not built on LangChain, so tracing uses the LangSmith SDK directly
(``trace`` context manager plus ``@traceable`` spans). This module loads
``.env`` before the SDK reads its settings, accepts both the standard
``LANGSMITH_*`` names and the legacy ``Langsmith`` key, and exports safe no-op
fallbacks when tracing is unavailable so the chatbot keeps working.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal

from dotenv import load_dotenv

from ..config import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_PROJECT = "xyz-handbook-rag"
DEFAULT_ENDPOINT = "https://api.smith.langchain.com"


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


# ``Langsmith`` is the spelling used in the original .env file; keep accepting
# it so tracing still works if someone copies that file around.
_api_key = _first_env(
    "LANGSMITH_API_KEY",
    "LANGCHAIN_API_KEY",
    "Langsmith",
    "LANGSMITH_KEY",
)
_project = _first_env(
    "LANGSMITH_PROJECT",
    "LANGCHAIN_PROJECT",
    "LANGCHAIN_SESSION",
    default=DEFAULT_PROJECT,
)
_endpoint = _first_env(
    "LANGSMITH_ENDPOINT",
    "LANGCHAIN_ENDPOINT",
    default=DEFAULT_ENDPOINT,
)
_tracing_flag = _first_env(
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING_V2",
    default="true" if _api_key else "false",
).lower()
_enabled_by_env = _tracing_flag in {"1", "true", "yes", "on"}

if _api_key:
    os.environ["LANGSMITH_API_KEY"] = _api_key
    os.environ.setdefault("LANGCHAIN_API_KEY", _api_key)
if _project:
    os.environ.setdefault("LANGSMITH_PROJECT", _project)
    os.environ.setdefault("LANGCHAIN_PROJECT", _project)
if _endpoint:
    os.environ.setdefault("LANGSMITH_ENDPOINT", _endpoint)
    os.environ.setdefault("LANGCHAIN_ENDPOINT", _endpoint)

if _enabled_by_env and _api_key:
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
else:
    # Avoid noisy SDK warnings and accidental traces when no key is configured.
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"

_langsmith_trace: Any = None
_langsmith_traceable: Any = None

try:
    from langsmith import trace as _langsmith_trace_import
    from langsmith import traceable as _langsmith_traceable_import

    _langsmith_trace = _langsmith_trace_import
    _langsmith_traceable = _langsmith_traceable_import
    SDK_AVAILABLE = True
except Exception:  # pragma: no cover - only when langsmith is not installed
    SDK_AVAILABLE = False

TRACING_ENABLED = bool(_api_key and _enabled_by_env and SDK_AVAILABLE)
PROJECT_NAME = _project

if TRACING_ENABLED:
    TRACING_STATUS = f"Tracing to LangSmith project “{PROJECT_NAME}”."
elif not _api_key:
    TRACING_STATUS = "LangSmith API key missing. Add LANGSMITH_API_KEY to .env."
elif not SDK_AVAILABLE:
    TRACING_STATUS = "langsmith is not installed. Run pip install -r requirements.txt."
else:
    TRACING_STATUS = "LangSmith tracing is turned off (LANGSMITH_TRACING=false)."


RunType = Literal[
    "tool",
    "chain",
    "llm",
    "retriever",
    "embedding",
    "prompt",
    "parser",
]


class _NoopRun:
    """Stand-in for a LangSmith run when tracing is disabled."""

    def end(self, **_: Any) -> None:
        pass


@contextmanager
def trace_run(
    name: str,
    /,
    *,
    run_type: RunType = "chain",
    inputs: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> Iterator[Any]:
    """Start a trace when LangSmith is configured, otherwise do nothing."""
    if not TRACING_ENABLED:
        yield _NoopRun()
        return

    with _langsmith_trace(
        name,
        run_type=run_type,
        inputs=inputs,
        metadata=metadata,
        tags=tags,
        project_name=PROJECT_NAME,
    ) as run:
        yield run


def traceable(*args: Any, **kwargs: Any) -> Any:
    """Decorator that becomes a no-op when LangSmith is not configured."""
    if not TRACING_ENABLED:
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def passthrough(function: Any) -> Any:
            return function

        return passthrough

    return _langsmith_traceable(*args, **kwargs)
