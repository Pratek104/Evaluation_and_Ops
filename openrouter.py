"""Minimal streaming client for the OpenRouter chat completions API."""

from __future__ import annotations

import json
from collections.abc import Iterator

import requests

from tracing import traceable

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Free models that are tried, in order, when the selected free model is
# rate-limited or temporarily unavailable. Paid models are never substituted
# automatically.
FREE_FALLBACKS = [
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
]


class OpenRouterError(RuntimeError):
    """A user-facing OpenRouter failure."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def is_free_model(model: str) -> bool:
    return model.endswith(":free")


def supports_reasoning(model: str) -> bool:
    return "gemma-4" in model or model.startswith("nvidia/nemotron-3-ultra")


def _trace_llm_inputs(inputs: dict) -> dict:
    """Describe an OpenRouter request without exposing the API key."""
    messages = inputs.get("messages") or []
    return {
        "model": inputs.get("model"),
        "messages": [
            {
                "role": message.get("role"),
                "content": message.get("content"),
            }
            for message in messages
            if isinstance(message, dict)
        ],
        "reasoning": bool(inputs.get("reasoning", False)),
        "temperature": inputs.get("temperature", 0.2),
        "max_tokens": inputs.get("max_tokens", 1600),
        "allow_free_fallback": bool(inputs.get("allow_free_fallback", True)),
    }


def _reduce_stream_events(events: list[tuple[str, str]] | None) -> dict:
    """Turn the streamed events into one useful LLM span output."""
    content: list[str] = []
    reasoning: list[str] = []
    notices: list[str] = []
    model = ""

    for event in events or []:
        if not isinstance(event, tuple) or len(event) != 2:
            continue
        kind, value = event
        if kind == "content" and isinstance(value, str):
            content.append(value)
        elif kind == "reasoning" and isinstance(value, str):
            reasoning.append(value)
        elif kind == "notice" and isinstance(value, str):
            notices.append(value)
        elif kind == "model" and isinstance(value, str):
            model = value

    reasoning_text = "".join(reasoning)
    return {
        "model": model,
        "content": "".join(content),
        "reasoning": reasoning_text,
        "reasoning_chars": len(reasoning_text),
        "notices": notices,
        "event_count": len(events or []),
    }


def _error_from_response(status_code: int, body: str) -> OpenRouterError:
    detail = ""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {}

    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        detail = str(error.get("message") or "")
        metadata = error.get("metadata")
        if isinstance(metadata, dict) and metadata.get("raw"):
            detail = str(metadata["raw"])
    elif isinstance(error, str):
        detail = error

    detail = " ".join(detail.split())
    if len(detail) > 240:
        detail = detail[:237] + "…"

    if status_code == 401:
        message = "OpenRouter rejected the API key. Check OPENROUTER_API_KEY in .env."
    elif status_code == 402:
        message = "The OpenRouter account does not have enough credits for this request."
    elif status_code == 403:
        message = "This model is not available to your OpenRouter account."
    elif status_code == 404:
        message = "The selected model is unavailable. Pick another model in the sidebar."
    elif status_code == 429:
        message = "The model is rate-limited right now. Try again shortly or pick another model."
    elif status_code >= 500:
        message = "OpenRouter is temporarily unavailable. Please retry in a moment."
    else:
        message = detail or f"OpenRouter returned HTTP {status_code}."

    if detail and status_code not in (401, 402, 429):
        message = f"{message} ({detail})"

    return OpenRouterError(
        message,
        status_code=status_code,
        retryable=status_code in (404, 429, 500, 502, 503, 504),
    )


def _parse_sse_line(line: str) -> dict | None:
    line = line.strip()
    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


@traceable(
    run_type="llm",
    name="openrouter_chat",
    process_inputs=_trace_llm_inputs,
    reduce_fn=_reduce_stream_events,
)
def stream_chat(
    model: str,
    messages: list[dict],
    api_key: str,
    *,
    reasoning: bool = False,
    temperature: float = 0.2,
    max_tokens: int = 1600,
    allow_free_fallback: bool = True,
    timeout: tuple[float, float] = (15.0, 240.0),
) -> Iterator[tuple[str, str]]:
    """Stream a chat completion.

    Yields ``(kind, value)`` events where kind is one of ``model``, ``notice``,
    ``reasoning`` or ``content``. The model/notice events explain an automatic
    switch between free models.
    """
    if not api_key:
        raise OpenRouterError(
            "OPENROUTER_API_KEY is missing. Add it to the .env file."
        )

    candidates = [model]
    if allow_free_fallback and is_free_model(model):
        candidates.extend(fallback for fallback in FREE_FALLBACKS if fallback != model)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "XYZ Handbook Assistant",
    }

    last_error: OpenRouterError | None = None

    for attempt, candidate in enumerate(candidates):
        payload: dict = {
            "model": candidate,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if reasoning and supports_reasoning(candidate):
            payload["reasoning"] = {"enabled": True}

        has_more_candidates = attempt < len(candidates) - 1

        try:
            with requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
                stream=True,
            ) as response:
                if response.status_code != 200:
                    error = _error_from_response(
                        response.status_code, response.text
                    )
                    last_error = error
                    if error.retryable and has_more_candidates:
                        continue
                    if (
                        error.retryable
                        and is_free_model(model)
                        and len(candidates) > 1
                    ):
                        break
                    raise error

                yield ("model", candidate)
                if candidate != model:
                    yield (
                        "notice",
                        f"{model} was unavailable, so this answer used {candidate}.",
                    )

                for raw_line in response.iter_lines():
                    line = (
                        raw_line.decode("utf-8", errors="replace")
                        if isinstance(raw_line, bytes)
                        else raw_line
                    )
                    event = _parse_sse_line(line or "")
                    if event is None:
                        continue

                    if "error" in event:
                        raise _error_from_response(
                            502, json.dumps(event)
                        )

                    choices = event.get("choices") or []
                    if not choices:
                        continue

                    delta = choices[0].get("delta") or {}

                    reasoning_text = delta.get("reasoning")
                    if isinstance(reasoning_text, str) and reasoning_text:
                        yield ("reasoning", reasoning_text)
                    elif delta.get("reasoning_details"):
                        for detail in delta["reasoning_details"]:
                            if not isinstance(detail, dict):
                                continue
                            text = detail.get("text") or detail.get("summary")
                            if isinstance(text, str) and text:
                                yield ("reasoning", text)

                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield ("content", content)

                return

        except requests.RequestException as exc:
            last_error = OpenRouterError(
                f"Could not reach OpenRouter: {exc}",
                retryable=True,
            )
            if has_more_candidates:
                continue
            raise last_error from exc

    if is_free_model(model) and len(candidates) > 1:
        raise OpenRouterError(
            "All free models are rate-limited right now. "
            "Pick a paid model in the sidebar or try again in a minute.",
            status_code=last_error.status_code if last_error else None,
        )

    raise last_error or OpenRouterError("The model request failed.")
