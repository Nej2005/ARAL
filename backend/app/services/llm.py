"""The only module that talks to Gemini (BACKEND.md §13).

`generate_structured(system, user, schema)` returns a validated Pydantic instance.
Tests replace `generate_structured` via `set_backend()`.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.config import settings

log = logging.getLogger("aral.llm")

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    code = "LLM_ERROR"


class LLMQuotaExceeded(LLMError):
    code = "LLM_QUOTA_EXCEEDED"


class LLMBlocked(LLMError):
    """The response was blocked or cut off; callers may split the input and retry."""

    code = "LLM_ERROR"


Backend = Callable[[str, str, type[BaseModel], str], BaseModel]

_lock = threading.Lock()
_last_call_at = 0.0
_backend: Backend | None = None


def set_backend(fn: Backend | None) -> None:
    global _backend
    _backend = fn


def _throttle() -> None:
    global _last_call_at
    gap = settings.llm_min_seconds_between_calls
    with _lock:
        wait = _last_call_at + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


def _client():
    from google import genai

    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not set. Put a free AI Studio key in backend/.env.")
    return genai.Client(api_key=settings.gemini_api_key)


def _status_code(err) -> int | None:
    for attr in ("code", "status_code"):
        v = getattr(err, attr, None)
        if isinstance(v, int):
            return v
    return None


def _call_once(client, model: str, system: str, user: str, schema: type[T], label: str) -> str:
    from google.genai import types

    _throttle()
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_json_schema=schema.model_json_schema(),
        temperature=0.2,
    )
    t0 = time.monotonic()
    resp = client.models.generate_content(model=model, contents=user, config=cfg)
    usage = getattr(resp, "usage_metadata", None)
    log.info(
        "gemini %s model=%s in=%s out=%s %.1fs",
        label, model,
        getattr(usage, "prompt_token_count", None),
        getattr(usage, "candidates_token_count", None),
        time.monotonic() - t0,
    )
    text = resp.text
    if not text:
        fb = getattr(resp, "prompt_feedback", None)
        reason = getattr(fb, "block_reason", None)
        cands = getattr(resp, "candidates", None) or []
        finish = getattr(cands[0], "finish_reason", None) if cands else None
        raise LLMBlocked(f"Empty response (block={reason}, finish={finish}).")
    cands = getattr(resp, "candidates", None) or []
    finish = str(getattr(cands[0], "finish_reason", "") or "") if cands else ""
    if "MAX_TOKENS" in finish:
        raise LLMBlocked("Response was cut off (MAX_TOKENS).")
    return text


def _gemini_backend(system: str, user: str, schema: type[T], label: str) -> T:
    from google.genai import errors as gerrors

    client = _client()
    models = [settings.gemini_model]
    if settings.gemini_fallback_model:
        models.append(settings.gemini_fallback_model)

    # One call may wait out rate limits and overload, but must finish well inside a 300 s request.
    deadline = time.monotonic() + 230
    quota_hit = server_busy = False
    for model in models:
        validation_retries = 1
        attempt = 0
        while True:
            attempt += 1
            try:
                text = _call_once(client, model, system, user, schema, label)
            except gerrors.APIError as e:
                code = _status_code(e)
                if code == 429:
                    # Free-tier limits are per minute: wait out the window, then try the fallback model.
                    delay = 10 * attempt + random.uniform(0, 3)
                    if attempt <= 4 and time.monotonic() + delay < deadline:
                        log.warning("gemini 429 on %s (%s); retry in %.0fs", model, label, delay)
                        time.sleep(delay)
                        continue
                    quota_hit = True
                    break
                if code is not None and code >= 500:
                    # "Model overloaded" (503) usually passes within seconds; then try the fallback model.
                    delay = 6 * attempt + random.uniform(0, 2)
                    if attempt <= 3 and time.monotonic() + delay < deadline:
                        log.warning("gemini %s on %s (%s); retry in %.0fs", code, model, label, delay)
                        time.sleep(delay)
                        continue
                    server_busy = True
                    break
                raise LLMError(f"Gemini request failed ({code}): {e}") from e
            except LLMBlocked:
                raise
            except (OSError, TimeoutError) as e:
                if attempt <= 3 and time.monotonic() + 2 * attempt < deadline:
                    time.sleep(2 * attempt)
                    continue
                raise LLMError(f"Could not reach Gemini: {e}") from e
            try:
                return schema.model_validate_json(text)
            except ValidationError as e:
                if validation_retries > 0:
                    validation_retries -= 1
                    log.warning("gemini returned invalid JSON for %s; retrying once", label)
                    continue
                raise LLMError(f"Gemini returned data that did not match the schema: {e}") from e
    if server_busy:
        raise LLMError("Gemini is overloaded right now. Try again in a few minutes.")
    if quota_hit:
        raise LLMQuotaExceeded("Gemini's free-tier limit was reached. Progress is saved; try again later.")
    raise LLMError("No Gemini model available.")


def generate_structured(system: str, user: str, schema: type[T], label: str = "") -> T:
    backend = _backend or _gemini_backend
    return backend(system, user, schema, label)  # type: ignore[return-value]
