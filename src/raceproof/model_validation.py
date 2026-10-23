from __future__ import annotations

from typing import Literal

from langchain.agents import create_agent
from langchain.tools import tool
from pydantic import BaseModel

from raceproof.model import _availability, _called_tools, _gemini
from raceproof.security import redact_sensitive
from raceproof.usage import StructuredOutputError, UsageTracker


class CapabilityResponse(BaseModel):
    model_role: Literal["investigation", "repair"]
    tool_value: str
    structured_output_ok: Literal[True]


class CapabilityResult(BaseModel):
    role: str
    model: str
    passed: bool
    tool_calling: bool = False
    structured_output: bool = False
    error: str | None = None


def validate_model_capability(
    model: str,
    role: Literal["investigation", "repair"],
    tracker: UsageTracker,
    max_retries: int,
    api_key: str | None = None,
) -> CapabilityResult:
    available, reason = _availability(model, api_key)
    if not available:
        return CapabilityResult(role=role, model=model, passed=False, error=reason)

    @tool
    def capability_probe() -> str:
        """Return the required value for this model capability check."""
        return "raceproof-capability-ok"

    try:
        agent = create_agent(
            _gemini(model, api_key),
            [capability_probe],
            system_prompt=(
                "Call capability_probe exactly once, then return the requested structured "
                "response. Do not answer from memory."
            ),
            response_format=CapabilityResponse,
            name=f"{role}_capability_probe",
        )
        result = tracker.invoke_with_retry(
            agent=role,
            model=model,
            invoke=lambda config: agent.invoke(
                {"messages": [{"role": "user", "content": f"Validate the {role} model role."}]},
                config=config,
            ),
            max_retries=max_retries,
        )
        response = CapabilityResponse.model_validate(result["structured_response"])
        tool_ok = any(call.get("name") == "capability_probe" for call in _called_tools(result))
        structured_ok = response.tool_value == "raceproof-capability-ok"
        if not tool_ok or not structured_ok:
            raise StructuredOutputError("model did not complete the required tool and schema probe")
        return CapabilityResult(
            role=role, model=model, passed=True, tool_calling=True, structured_output=True
        )
    except Exception as exc:  # noqa: BLE001 - validation returns structured failure evidence
        return CapabilityResult(role=role, model=model, passed=False, error=redact_sensitive(exc))
