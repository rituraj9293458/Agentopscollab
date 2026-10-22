from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path

from raceproof.config import get_settings
from raceproof.contracts import RunEvent, RunReport
from raceproof.model import LangChainRepairModel
from raceproof.workflow import RaceProofRunner


@dataclass
class ActiveRun:
    run_id: str
    status: str = "queued"
    events: list[RunEvent] = field(default_factory=list)
    report: RunReport | None = None
    error: str | None = None
    updates: queue.Queue[RunEvent | None] = field(default_factory=queue.Queue)


class RunService:
    def __init__(self, repository_root: Path) -> None:
        self.repository_root = repository_root
        self.runs: dict[str, ActiveRun] = {}
        self.lock = threading.Lock()

    def start(self, run_id: str) -> ActiveRun:
        active = ActiveRun(run_id=run_id)
        with self.lock:
            self.runs[run_id] = active

        def listener(event: RunEvent) -> None:
            active.events.append(event)
            active.status = event.stage
            active.updates.put(event)

        def execute() -> None:
            settings = get_settings()
            model = LangChainRepairModel(settings.model_provider, settings.model_name)
            try:
                active.status = "running"
                runner = RaceProofRunner(self.repository_root, settings, model, listener)
                active.report = runner.run(run_id)
                active.status = active.report.status.value
            except Exception as exc:  # noqa: BLE001 - background failure becomes run evidence
                active.error = f"{type(exc).__name__}: {exc}"
                active.status = "EXECUTION_ERROR"
            finally:
                active.updates.put(None)

        threading.Thread(target=execute, daemon=True, name=f"raceproof-{run_id}").start()
        return active

    def get(self, run_id: str) -> ActiveRun | None:
        with self.lock:
            return self.runs.get(run_id)
