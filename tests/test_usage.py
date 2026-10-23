from types import SimpleNamespace

import pytest

from raceproof.usage import (
    BudgetExceededError,
    ModelAuthenticationError,
    ModelQuotaExceededError,
    ModelRateLimitError,
    UsageLimits,
    UsageTracker,
    _extract_usage,
    classify_model_error,
)


def test_request_budgets_are_enforced_before_provider_call() -> None:
    tracker = UsageTracker(UsageLimits(2, 1, 1, 1000))
    tracker.start_request("investigation", "model-a", False)
    with pytest.raises(BudgetExceededError, match="investigation"):
        tracker.start_request("investigation", "model-a", False)
    tracker.start_request("repair", "model-b", True)
    with pytest.raises(BudgetExceededError, match="global"):
        tracker.start_request("repair", "model-b", False)
    snapshot = tracker.snapshot()
    assert snapshot.total_requests == 2
    assert snapshot.fallback_invocations == 1


def test_provider_reported_tokens_and_unknown_usage_are_explicit() -> None:
    tracker = UsageTracker(UsageLimits())
    tracker.start_request("repair", "model-b", False)
    tracker.finish_request("repair", "model-b", (11, 7, 18))
    tracker.start_request("repair", "model-b", False)
    tracker.finish_request("repair", "model-b", None)
    snapshot = tracker.snapshot()
    assert snapshot.total_tokens == 18
    assert snapshot.unknown_token_responses == 1
    assert snapshot.approximate_cost_usd is None


def test_usage_extraction_reads_langchain_metadata() -> None:
    response = SimpleNamespace(
        generations=[
            [
                SimpleNamespace(
                    message=SimpleNamespace(
                        usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
                    )
                )
            ]
        ]
    )
    assert _extract_usage(response) == (3, 2, 5)


@pytest.mark.parametrize(
    "message,expected",
    [
        ("API key not valid", ModelAuthenticationError),
        ("429 RESOURCE_EXHAUSTED retry later", ModelRateLimitError),
        ("429 project quota exhausted for daily requests", ModelQuotaExceededError),
    ],
)
def test_provider_failures_are_classified(message: str, expected: type[Exception]) -> None:
    assert isinstance(classify_model_error(RuntimeError(message)), expected)
