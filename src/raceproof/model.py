from __future__ import annotations

import json
import os
from typing import Protocol

from raceproof.contracts import FailureBundle, PatchProposal


class RepairModel(Protocol):
    def available(self) -> tuple[bool, str]: ...

    def propose(self, bundle: FailureBundle) -> PatchProposal: ...


class LangChainRepairModel:
    """Configurable live model integration. It never substitutes a canned repair."""

    def __init__(self, provider: str, model_name: str) -> None:
        self.provider = provider.lower()
        self.model_name = model_name

    def available(self) -> tuple[bool, str]:
        key_names = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }
        key_name = key_names.get(self.provider)
        if key_name is None:
            return False, f"unsupported model provider: {self.provider}"
        if not os.environ.get(key_name):
            return False, f"{key_name} is not configured; live autonomous repair is unavailable"
        try:
            if self.provider == "openai":
                import langchain_openai  # noqa: F401
            elif self.provider == "anthropic":
                import langchain_anthropic  # noqa: F401
        except ImportError:
            return False, f"LangChain integration package for {self.provider} is not installed"
        return True, "live model configured"

    def propose(self, bundle: FailureBundle) -> PatchProposal:
        available, reason = self.available()
        if not available:
            raise RuntimeError(reason)
        from langchain.chat_models import init_chat_model

        model = init_chat_model(self.model_name, model_provider=self.provider, temperature=0)
        structured = model.with_structured_output(PatchProposal)
        prompt = (
            "You are RaceProof's bounded concurrency repair agent. Diagnose the reproduced "
            "PostgreSQL race and author one complete unified Git diff. Modify only editable_paths. "
            "Never modify tests, invariants, schedulers, fixtures, or configuration. Do not add sleeps, "
            "network calls, subprocess calls, or scheduling markers. Preserve the public function "
            "signature. Prefer the smallest repair matching the conflict shape. A candidate will be "
            "accepted only by deterministic execution. If evidence is insufficient, set cannot_repair.\n\n"
            + json.dumps(bundle.model_dump(mode="json"), indent=2)
        )
        result = structured.invoke(prompt)
        return result if isinstance(result, PatchProposal) else PatchProposal.model_validate(result)
