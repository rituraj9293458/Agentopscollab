from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from langsmith import traceable
from pydantic import SecretStr

from raceproof.security import redact_sensitive


SENSITIVE_KEYS = {
    "api_key",
    "database_url",
    "gemini_api_key",
    "google_api_key",
    "langsmith_api_key",
    "password",
    "token",
}


def _safe_value(value: Any) -> Any:
    if isinstance(value, SecretStr):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else _safe_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_safe_value(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if hasattr(value, "model_dump"):
        return _safe_value(value.model_dump(mode="json"))
    return redact_sensitive(repr(value))


def safe_trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Redact credentials while retaining useful RaceProof trace evidence."""
    return _safe_value(inputs)


def safe_trace_outputs(outputs: Any) -> Any:
    """Redact credentials from values sent to LangSmith."""
    return _safe_value(outputs)


def traced(*, name: str, run_type: str = "chain"):
    """Create a consistently redacted optional LangSmith trace decorator."""
    return traceable(
        name=name,
        run_type=run_type,
        process_inputs=safe_trace_inputs,
        process_outputs=safe_trace_outputs,
    )


def configure_langsmith(settings: Any) -> bool:
    """Export validated .env settings for LangChain and LangSmith instrumentation."""
    key = settings.langsmith_api_key_value
    enabled = bool(settings.langsmith_tracing and key and key != "placeholder")
    os.environ["LANGSMITH_TRACING"] = "true" if enabled else "false"
    os.environ["LANGSMITH_TRACING_V2"] = "true" if enabled else "false"
    if enabled:
        os.environ["LANGSMITH_API_KEY"] = key
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    return enabled
