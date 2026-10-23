from __future__ import annotations

import json
import os
from typing import Protocol

from raceproof.contracts import FailureBundle, PatchProposal


class RepairModel(Protocol):
    def available(self) -> tuple[bool, str]: ...

    def propose(self, bundle: FailureBundle) -> PatchProposal: ...


class GeminiRepairModel:
    """Gemini repair integration. It never substitutes a canned repair."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def available(self) -> tuple[bool, str]:
        if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
            return (
                False,
                (
                    "GEMINI_API_KEY or GOOGLE_API_KEY is not configured; "
                    "live autonomous repair is unavailable"
                ),
            )
        try:
            import langchain_google_genai  # noqa: F401
        except ImportError:
            return False, "langchain-google-genai is not installed"
        return True, f"Gemini model {self.model_name} configured"

    def propose(self, bundle: FailureBundle) -> PatchProposal:
        available, reason = self.available()
        if not available:
            raise RuntimeError(reason)
        from langchain_google_genai import ChatGoogleGenerativeAI

        model = ChatGoogleGenerativeAI(
            model=self.model_name,
            temperature=0,
            max_retries=2,
        )
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
