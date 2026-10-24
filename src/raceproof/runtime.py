from __future__ import annotations

from raceproof.config import Settings
from raceproof.usage import UsageLimits, UsageTracker


def build_usage_tracker(settings: Settings) -> UsageTracker:
    return UsageTracker(
        UsageLimits(
            max_model_requests=settings.max_model_requests,
            max_investigation_requests=settings.max_investigation_requests,
            max_repair_requests=settings.max_repair_requests,
            max_total_tokens=settings.max_total_tokens,
        ),
        pricing_json=settings.model_pricing_json,
        pricing_verified=settings.model_pricing_verified,
    )


def model_status(settings: Settings) -> dict[str, object]:
    key = settings.gemini_api_key_value
    return {
        "key_configured": bool(key and key != "placeholder"),
        "investigation_model": settings.resolved_investigation_model,
        "repair_model": settings.resolved_repair_model,
        "fallback_model": settings.fallback_model,
        "fallback_enabled": settings.enable_model_fallback,
        "langsmith": {
            "configured": bool(
                settings.langsmith_api_key_value
                and settings.langsmith_api_key_value != "placeholder"
            ),
            "tracing": settings.langsmith_tracing,
            "project": settings.langsmith_project,
        },
        "budgets": {
            "max_model_requests": settings.max_model_requests,
            "max_investigation_requests": settings.max_investigation_requests,
            "max_repair_requests": settings.max_repair_requests,
            "max_total_tokens": settings.max_total_tokens,
        },
    }
