from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path

from raceproof.config import get_settings
from raceproof.contracts import RunEvent, RunReport
from raceproof.model import GeminiInvestigationAgent, GeminiRepairAgent
from raceproof.runtime import build_usage_tracker
from raceproof.security import redact_sensitive
from raceproof.target import LoadedTarget
from raceproof.tracing import configure_langsmith
from raceproof.usage import UsageTracker
from raceproof.workflow import RaceProofRunner


@dataclass
class ActiveRun:
    run_id: str
    status: str = "queued"
    events: list[RunEvent] = field(default_factory=list)
    report: RunReport | None = None
    error: str | None = None
    updates: queue.Queue[RunEvent | None] = field(default_factory=queue.Queue)
    usage_tracker: UsageTracker | None = None
    runner: RaceProofRunner | None = None


class RunService:
    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root
        self.runs: dict[str, ActiveRun] = {}
        self.lock = threading.Lock()
        self.execution_lock = threading.Lock()

    def start(self, run_id: str, target: LoadedTarget) -> ActiveRun:
        active = ActiveRun(run_id=run_id)
        with self.lock:
            self.runs[run_id] = active

        def listener(event: RunEvent) -> None:
            active.events.append(event)
            active.status = event.stage
            active.updates.put(event)

        def execute() -> None:
            settings = get_settings()
            configure_langsmith(settings)
            tracker = build_usage_tracker(settings)
            active.usage_tracker = tracker
            common = {
                "usage_tracker": tracker,
                "fallback_model": settings.fallback_model,
                "fallback_enabled": settings.enable_model_fallback,
                "max_retries": settings.model_max_retries,
                "api_key": settings.gemini_api_key_value,
            }
            investigation_agent = GeminiInvestigationAgent(
                settings.resolved_investigation_model, **common
            )
            repair_agent = GeminiRepairAgent(settings.resolved_repair_model, **common)
            try:
                active.status = "running"
                runner = RaceProofRunner(
                    self.repository_root,
                    target,
                    settings,
                    investigation_agent,
                    repair_agent,
                    listener,
                    tracker,
                )
                active.runner = runner
                with self.execution_lock:
                    active.report = runner.run(run_id)
                active.status = active.report.status.value
            except Exception as exc:  # noqa: BLE001 - background failure becomes run evidence
                active.error = redact_sensitive(f"{type(exc).__name__}: {exc}")
                active.status = "EXECUTION_ERROR"
            finally:
                active.updates.put(None)

        threading.Thread(target=execute, daemon=True, name=f"raceproof-{run_id}").start()
        return active

    def restore_reviewable(
        self,
        run_id: str,
        target: LoadedTarget,
        report: RunReport,
    ) -> ActiveRun:
        """Rebuild a paused HITL run after an API process restart.

        LangGraph state is durable in the SQLite checkpointer. The API-facing run
        registry is intentionally lightweight, so reconstruct it from the persisted
        report rather than requiring the original worker thread to remain alive.
        """
        if report.status.value != "AWAITING_HUMAN_REVIEW":
            raise ValueError("run is not awaiting human review")
        with self.lock:
            existing = self.runs.get(run_id)
            if existing is not None:
                return existing
            active = ActiveRun(
                run_id=run_id,
                status=report.status.value,
                events=list(report.events),
                report=report,
            )
            self.runs[run_id] = active

        def listener(event: RunEvent) -> None:
            active.events.append(event)
            active.status = event.stage
            active.updates.put(event)

        settings = get_settings()
        configure_langsmith(settings)
        tracker = build_usage_tracker(settings)
        active.usage_tracker = tracker
        common = {
            "usage_tracker": tracker,
            "fallback_model": settings.fallback_model,
            "fallback_enabled": settings.enable_model_fallback,
            "max_retries": settings.model_max_retries,
            "api_key": settings.gemini_api_key_value,
        }
        active.runner = RaceProofRunner(
            self.repository_root,
            target,
            settings,
            GeminiInvestigationAgent(settings.resolved_investigation_model, **common),
            GeminiRepairAgent(settings.resolved_repair_model, **common),
            listener,
            tracker,
            initial_events=list(report.events),
        )
        return active

    def review(self, run_id: str, action: str, comment: str = "") -> ActiveRun:
        active = self.get(run_id)
        if active is None or active.runner is None or active.report is None:
            raise KeyError("active reviewable run not found")
        if active.report.status.value != "AWAITING_HUMAN_REVIEW":
            raise ValueError("run is not awaiting human review")
        active.updates = queue.Queue()
        active.status = "human_review"

        def execute_review() -> None:
            try:
                with self.execution_lock:
                    active.report = active.runner.resume_human_review(run_id, action, comment)
                active.status = active.report.status.value
            except Exception as exc:  # noqa: BLE001 - review failure becomes run evidence
                active.error = redact_sensitive(f"{type(exc).__name__}: {exc}")
                active.status = "EXECUTION_ERROR"
            finally:
                active.updates.put(None)

        threading.Thread(
            target=execute_review,
            daemon=True,
            name=f"raceproof-review-{run_id}",
        ).start()
        return active

    def get(self, run_id: str) -> ActiveRun | None:
        with self.lock:
            return self.runs.get(run_id)
