from __future__ import annotations

import json
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from langchain_core.callbacks import BaseCallbackHandler
from pydantic import BaseModel, Field

T = TypeVar("T")


class ModelRuntimeError(RuntimeError):
    code = "MODEL_ERROR"
    transient = False


class BudgetExceededError(ModelRuntimeError):
    code = "BUDGET_EXCEEDED"


class ModelAuthenticationError(ModelRuntimeError):
    code = "AUTHENTICATION_ERROR"


class ModelUnavailableError(ModelRuntimeError):
    code = "MODEL_UNAVAILABLE"


class ModelRateLimitError(ModelRuntimeError):
    code = "RATE_LIMITED"
    transient = True


class ModelQuotaExceededError(ModelRuntimeError):
    code = "QUOTA_EXCEEDED"


class ModelTransientError(ModelRuntimeError):
    code = "PROVIDER_TRANSIENT_ERROR"
    transient = True


class StructuredOutputError(ModelRuntimeError):
    code = "STRUCTURED_OUTPUT_ERROR"


class AgentUsage(BaseModel):
    requests: int = 0
    failed_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    unknown_token_responses: int = 0


class UsageSnapshot(BaseModel):
    total_requests: int = 0
    requests_by_agent: dict[str, int] = Field(default_factory=dict)
    requests_by_model: dict[str, int] = Field(default_factory=dict)
    usage_by_agent: dict[str, AgentUsage] = Field(default_factory=dict)
    usage_by_model: dict[str, AgentUsage] = Field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    unknown_token_responses: int = 0
    failed_requests: int = 0
    rate_limit_errors: int = 0
    fallback_invocations: int = 0
    remaining_request_budget: int = 0
    remaining_investigation_budget: int = 0
    remaining_repair_budget: int = 0
    remaining_token_budget: int = 0
    budget_exhausted: bool = False
    warnings: list[str] = Field(default_factory=list)
    approximate_cost_usd: float | None = None
    cost_is_partial: bool = False


@dataclass(frozen=True)
class UsageLimits:
    max_model_requests: int = 12
    max_investigation_requests: int = 5
    max_repair_requests: int = 7
    max_total_tokens: int = 60_000


def classify_model_error(exc: BaseException) -> ModelRuntimeError:
    if isinstance(exc, ModelRuntimeError):
        return exc
    message = str(exc).lower()
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    status = status or getattr(response, "status_code", None)
    if status in {401, 403} or any(
        marker in message
        for marker in (
            "api key not valid",
            "api_key_invalid",
            "unauthenticated",
            "permission denied",
        )
    ):
        return ModelAuthenticationError(str(exc))
    if status == 404 or any(
        marker in message
        for marker in ("model not found", "unknown model", "invalid model", "not supported for")
    ):
        return ModelUnavailableError(str(exc))
    if status == 429 or "429" in message or "resource_exhausted" in message:
        if any(
            marker in message
            for marker in ("per day", "daily", "quota exhausted", "billing", "project quota")
        ):
            return ModelQuotaExceededError(str(exc))
        return ModelRateLimitError(str(exc))
    if status is not None and int(status) >= 500:
        return ModelTransientError(str(exc))
    if any(marker in message for marker in ("timeout", "timed out", "connection", "temporarily")):
        return ModelTransientError(str(exc))
    if any(
        marker in message
        for marker in ("structured_response", "validation error", "tool call", "malformed")
    ):
        return StructuredOutputError(str(exc))
    return ModelRuntimeError(str(exc))


def retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("retry-after") or headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


class _UsageCallback(BaseCallbackHandler):
    def __init__(self, tracker: UsageTracker, agent: str, model: str, fallback: bool) -> None:
        self.raise_error = True
        self.tracker = tracker
        self.agent = agent
        self.model = model
        self.fallback = fallback

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        **kwargs: Any,
    ) -> None:
        self.tracker.start_request(self.agent, self.model, self.fallback)

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        usage = _extract_usage(response)
        self.tracker.finish_request(self.agent, self.model, usage)

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        self.tracker.fail_request(self.agent, self.model, classify_model_error(error))


def _extract_usage(response: Any) -> tuple[int, int, int] | None:
    generations = getattr(response, "generations", []) or []
    for group in generations:
        for generation in group:
            message = getattr(generation, "message", None)
            metadata = getattr(message, "usage_metadata", None) or {}
            if metadata:
                input_tokens = metadata.get("input_tokens")
                output_tokens = metadata.get("output_tokens")
                total_tokens = metadata.get("total_tokens")
                if input_tokens is not None and output_tokens is not None:
                    total = (
                        total_tokens if total_tokens is not None else input_tokens + output_tokens
                    )
                    return int(input_tokens), int(output_tokens), int(total)
            response_metadata = getattr(message, "response_metadata", None) or {}
            token_usage = response_metadata.get("token_usage") or response_metadata.get(
                "usage_metadata"
            )
            if token_usage:
                input_tokens = token_usage.get("prompt_token_count") or token_usage.get(
                    "input_tokens"
                )
                output_tokens = token_usage.get("candidates_token_count") or token_usage.get(
                    "output_tokens"
                )
                total_tokens = token_usage.get("total_token_count") or token_usage.get(
                    "total_tokens"
                )
                if input_tokens is not None and output_tokens is not None:
                    total = (
                        total_tokens if total_tokens is not None else input_tokens + output_tokens
                    )
                    return int(input_tokens), int(output_tokens), int(total)
    return None


class UsageTracker:
    def __init__(
        self,
        limits: UsageLimits,
        *,
        pricing_json: str | None = None,
        pricing_verified: bool = False,
    ) -> None:
        self.limits = limits
        self._lock = threading.Lock()
        self._requests_by_agent: Counter[str] = Counter()
        self._requests_by_model: Counter[str] = Counter()
        self._usage_by_agent: defaultdict[str, AgentUsage] = defaultdict(AgentUsage)
        self._usage_by_model: defaultdict[str, AgentUsage] = defaultdict(AgentUsage)
        self._failed_requests = 0
        self._rate_limit_errors = 0
        self._fallback_invocations = 0
        self._warnings: list[str] = []
        self._budget_exhausted = False
        self._pricing = self._parse_pricing(pricing_json) if pricing_verified else {}
        self._pricing_verified = pricing_verified and bool(self._pricing)

    @staticmethod
    def _parse_pricing(value: str | None) -> dict[str, dict[str, float]]:
        if not value:
            return {}
        try:
            raw = json.loads(value)
            return {
                str(model): {
                    "input_per_million": float(prices["input_per_million"]),
                    "output_per_million": float(prices["output_per_million"]),
                }
                for model, prices in raw.items()
            }
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return {}

    def callback(self, agent: str, model: str, *, fallback: bool = False) -> BaseCallbackHandler:
        return _UsageCallback(self, agent, model, fallback)

    def start_request(self, agent: str, model: str, fallback: bool) -> None:
        with self._lock:
            total = sum(self._requests_by_agent.values())
            agent_limit = (
                self.limits.max_investigation_requests
                if agent == "investigation"
                else self.limits.max_repair_requests
            )
            if total >= self.limits.max_model_requests:
                self._budget_exhausted = True
                raise BudgetExceededError("global model request budget exhausted")
            if self._requests_by_agent[agent] >= agent_limit:
                self._budget_exhausted = True
                raise BudgetExceededError(f"{agent} model request budget exhausted")
            current_tokens = sum(item.total_tokens for item in self._usage_by_agent.values())
            if current_tokens >= self.limits.max_total_tokens:
                self._budget_exhausted = True
                raise BudgetExceededError("provider-reported token budget exhausted")
            self._requests_by_agent[agent] += 1
            self._requests_by_model[model] += 1
            self._usage_by_agent[agent].requests += 1
            self._usage_by_model[model].requests += 1
            if fallback:
                self._fallback_invocations += 1

    def finish_request(self, agent: str, model: str, usage: tuple[int, int, int] | None) -> None:
        with self._lock:
            if usage is None:
                self._usage_by_agent[agent].unknown_token_responses += 1
                self._usage_by_model[model].unknown_token_responses += 1
                warning = f"Token usage metadata unavailable for {agent} request on {model}."
                if warning not in self._warnings:
                    self._warnings.append(warning)
                return
            input_tokens, output_tokens, total_tokens = usage
            for item in (self._usage_by_agent[agent], self._usage_by_model[model]):
                item.input_tokens += input_tokens
                item.output_tokens += output_tokens
                item.total_tokens += total_tokens
            if (
                sum(item.total_tokens for item in self._usage_by_agent.values())
                > self.limits.max_total_tokens
            ):
                self._budget_exhausted = True

    def fail_request(self, agent: str, model: str, error: ModelRuntimeError) -> None:
        with self._lock:
            self._failed_requests += 1
            self._usage_by_agent[agent].failed_requests += 1
            self._usage_by_model[model].failed_requests += 1
            if isinstance(error, ModelRateLimitError):
                self._rate_limit_errors += 1
            warning = f"{error.code}: {error}"
            if warning not in self._warnings:
                self._warnings.append(warning[:500])

    def record_agent_failure(self, error: ModelRuntimeError) -> None:
        with self._lock:
            warning = f"{error.code}: {error}"
            if warning not in self._warnings:
                self._warnings.append(warning[:500])

    def ensure_within_budget(self) -> None:
        with self._lock:
            if self._budget_exhausted:
                raise BudgetExceededError("configured model request or token budget exhausted")

    def invoke_with_retry(
        self,
        *,
        agent: str,
        model: str,
        invoke: Callable[[dict[str, Any]], T],
        max_retries: int,
        fallback: bool = False,
    ) -> T:
        for attempt in range(max_retries + 1):
            callback = self.callback(agent, model, fallback=fallback)
            try:
                result = invoke({"callbacks": [callback]})
                self.ensure_within_budget()
                return result
            except BudgetExceededError:
                raise
            except Exception as exc:
                error = classify_model_error(exc)
                self.record_agent_failure(error)
                if not error.transient or attempt >= max_retries:
                    raise error from exc
                delay = retry_after_seconds(exc)
                if delay is None:
                    delay = min(2**attempt, 8)
                time.sleep(min(delay, 30))
        raise AssertionError("unreachable retry loop")

    def snapshot(self) -> UsageSnapshot:
        with self._lock:
            total_requests = sum(self._requests_by_agent.values())
            input_tokens = sum(item.input_tokens for item in self._usage_by_agent.values())
            output_tokens = sum(item.output_tokens for item in self._usage_by_agent.values())
            total_tokens = sum(item.total_tokens for item in self._usage_by_agent.values())
            unknown = sum(item.unknown_token_responses for item in self._usage_by_agent.values())
            cost: float | None = None
            cost_partial = False
            if self._pricing_verified:
                cost = 0.0
                for model, usage in self._usage_by_model.items():
                    prices = self._pricing.get(model)
                    if prices is None:
                        cost_partial = True
                        continue
                    cost += usage.input_tokens / 1_000_000 * prices["input_per_million"]
                    cost += usage.output_tokens / 1_000_000 * prices["output_per_million"]
                cost_partial = cost_partial or unknown > 0
            return UsageSnapshot(
                total_requests=total_requests,
                requests_by_agent=dict(self._requests_by_agent),
                requests_by_model=dict(self._requests_by_model),
                usage_by_agent={
                    key: value.model_copy() for key, value in self._usage_by_agent.items()
                },
                usage_by_model={
                    key: value.model_copy() for key, value in self._usage_by_model.items()
                },
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                unknown_token_responses=unknown,
                failed_requests=self._failed_requests,
                rate_limit_errors=self._rate_limit_errors,
                fallback_invocations=self._fallback_invocations,
                remaining_request_budget=max(0, self.limits.max_model_requests - total_requests),
                remaining_investigation_budget=max(
                    0,
                    self.limits.max_investigation_requests
                    - self._requests_by_agent["investigation"],
                ),
                remaining_repair_budget=max(
                    0, self.limits.max_repair_requests - self._requests_by_agent["repair"]
                ),
                remaining_token_budget=max(0, self.limits.max_total_tokens - total_tokens),
                budget_exhausted=self._budget_exhausted,
                warnings=list(self._warnings),
                approximate_cost_usd=cost,
                cost_is_partial=cost_partial,
            )
