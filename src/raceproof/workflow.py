from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Literal, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from raceproof.config import Settings
from raceproof.contracts import (
    EventKind,
    FailureBundle,
    FinalStatus,
    RepairAttempt,
    RunReport,
)
from raceproof.database import create_database_engine
from raceproof.events import EventRecorder
from raceproof.inspection import inspect_python_file
from raceproof.model import RepairModel
from raceproof.patching import PatchGuard, WorkspaceManager, canonical_diff
from raceproof.sample.inventory import purchase_inventory
from raceproof.sample.models import Base
from raceproof.scheduler import ControlledScheduler, benchmark_operation
from raceproof.verification import verify_candidate


class WorkflowState(TypedDict, total=False):
    run_id: str
    status: str
    findings: list[dict[str, Any]]
    baseline: dict[str, Any]
    baseline_performance: dict[str, Any]
    attempts: list[dict[str, Any]]
    attempt_number: int
    failure_bundle: dict[str, Any]
    candidate_path: str
    proposal: dict[str, Any]
    final_diff: str
    terminal_reason: str


class RaceProofRunner:
    editable_paths: ClassVar[set[str]] = {"src/raceproof/sample/inventory.py"}
    protected_prefixes: ClassVar[tuple[str, ...]] = (
        "tests/",
        "src/raceproof/scheduler.py",
        "src/raceproof/invariants.py",
    )

    def __init__(
        self,
        repository_root: Path,
        settings: Settings,
        repair_model: RepairModel,
        listener: Any | None = None,
    ) -> None:
        self.repository_root = repository_root.resolve()
        self.settings = settings
        self.repair_model = repair_model
        self.recorder = EventRecorder(listener)
        self.workspace = WorkspaceManager(
            self.repository_root, self.repository_root / settings.artifact_dir
        )
        self.guard = PatchGuard(self.editable_paths, self.protected_prefixes)
        self._history_lock = threading.Lock()
        self.graph = self._build_graph()

    def _stage(self, action: str, detail: dict[str, Any] | None = None) -> None:
        self.recorder.add(EventKind.STAGE, action, action, detail=detail)

    def _persist(self, run_id: str, node: str, state: WorkflowState) -> None:
        output = self.repository_root / self.settings.artifact_dir / "runs" / run_id
        output.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "node": node,
            "state": state,
        }
        with (
            self._history_lock,
            (output / "state-history.jsonl").open("a", encoding="utf-8") as stream,
        ):
            stream.write(json.dumps(record, default=str) + "\n")

    def _inspect(self, state: WorkflowState) -> WorkflowState:
        self._stage("inspect")
        path = self.repository_root / "src" / "raceproof" / "sample" / "inventory.py"
        findings = inspect_python_file(path, self.repository_root)
        update: WorkflowState = {
            "findings": [finding.model_dump(mode="json") for finding in findings]
        }
        self._persist(state["run_id"], "inspect", update)
        return update

    def _hypothesize(self, state: WorkflowState) -> WorkflowState:
        self._stage("hypothesize", {"finding_count": len(state.get("findings", []))})
        update: WorkflowState = {"status": FinalStatus.SUSPECTED.value}
        self._persist(state["run_id"], "hypothesize", update)
        return update

    def _execute(self, state: WorkflowState) -> WorkflowState:
        self._stage("schedule")
        engine = create_database_engine(self.settings.database_url, self.recorder)
        try:
            result = ControlledScheduler(
                engine, self.recorder, self.settings.schedule_timeout_seconds
            ).reproduce_stale_read(purchase_inventory)
            baseline_performance = benchmark_operation(
                engine,
                purchase_inventory,
                self.settings.benchmark_runs,
                self.settings.schedule_timeout_seconds,
            )
        finally:
            engine.dispose()
        reproduced = bool(
            result.completed and result.exact and result.invariant and not result.invariant.passed
        )
        status = FinalStatus.REPRODUCED.value if reproduced else FinalStatus.EXECUTION_ERROR.value
        update: WorkflowState = {
            "baseline": result.model_dump(mode="json"),
            "baseline_performance": baseline_performance.model_dump(mode="json"),
            "status": status,
            "terminal_reason": ""
            if reproduced
            else "controlled schedule did not reproduce the invariant failure",
        }
        self._persist(state["run_id"], "execute", update)
        return update

    def _route_after_execute(self, state: WorkflowState) -> Literal["repair", "finalize"]:
        return "repair" if state.get("status") == FinalStatus.REPRODUCED.value else "finalize"

    def _build_bundle(self, state: WorkflowState) -> FailureBundle:
        source_path = self.repository_root / "src" / "raceproof" / "sample" / "inventory.py"
        models_path = self.repository_root / "src" / "raceproof" / "sample" / "models.py"
        ddl = "\n\n".join(
            str(CreateTable(table).compile(dialect=postgresql.dialect()))
            for table in Base.metadata.sorted_tables
        )
        return FailureBundle(
            target_operation="raceproof.sample.inventory.purchase_inventory",
            source_files={
                "src/raceproof/sample/inventory.py": source_path.read_text(encoding="utf-8"),
                "src/raceproof/sample/models.py": models_path.read_text(encoding="utf-8"),
            },
            schema_ddl=ddl,
            findings=state.get("findings", []),
            reproduced_schedule=state["baseline"],
            business_invariant="successful_orders <= initial_stock AND final_stock = initial_stock - successful_orders",
            allowed_outcomes={"accepted": 1, "rejected": 1, "errors": 0},
            editable_paths=sorted(self.editable_paths),
            protected_paths=list(self.protected_prefixes),
            previous_attempts=state.get("attempts", []),
        )

    def _repair(self, state: WorkflowState) -> WorkflowState:
        attempt_number = state.get("attempt_number", 0) + 1
        self._stage("repair", {"attempt": attempt_number})
        available, reason = self.repair_model.available()
        if not available:
            update: WorkflowState = {
                "attempt_number": attempt_number,
                "status": FinalStatus.MODEL_UNAVAILABLE.value,
                "terminal_reason": reason,
            }
            self._persist(state["run_id"], "repair", update)
            return update
        bundle = self._build_bundle(state)
        proposal = self.repair_model.propose(bundle)
        attempt = RepairAttempt(number=attempt_number, proposal=proposal)
        if proposal.cannot_repair:
            attempt.failure_reason = "model reported that it cannot produce a justified repair"
            update = {
                "attempt_number": attempt_number,
                "attempts": [*state.get("attempts", []), attempt.model_dump(mode="json")],
                "status": FinalStatus.UNRESOLVED.value,
                "terminal_reason": attempt.failure_reason,
            }
            self._persist(state["run_id"], "repair", update)
            return update
        candidate = self.workspace.create_candidate(attempt_number)
        validation = self.guard.apply(candidate, proposal.unified_diff)
        attempt.patch_validation = validation
        if not validation.accepted:
            attempt.failure_reason = "; ".join(validation.errors)
        update = {
            "attempt_number": attempt_number,
            "failure_bundle": bundle.model_dump(mode="json"),
            "proposal": proposal.model_dump(mode="json"),
            "candidate_path": str(candidate),
            "attempts": [*state.get("attempts", []), attempt.model_dump(mode="json")],
            "status": FinalStatus.REPRODUCED.value
            if validation.accepted
            else FinalStatus.UNRESOLVED.value,
            "terminal_reason": ""
            if validation.accepted
            else (attempt.failure_reason or "patch rejected"),
        }
        self._persist(state["run_id"], "repair", update)
        return update

    def _route_after_repair(self, state: WorkflowState) -> Literal["verify", "retry", "finalize"]:
        if state.get("status") == FinalStatus.MODEL_UNAVAILABLE.value:
            return "finalize"
        if state.get("candidate_path") and not state.get("terminal_reason"):
            return "verify"
        if state.get("attempt_number", 0) < self.settings.max_repair_attempts:
            return "retry"
        return "finalize"

    def _retry(self, state: WorkflowState) -> WorkflowState:
        self._stage("replan", {"next_attempt": state.get("attempt_number", 0) + 1})
        update: WorkflowState = {"status": FinalStatus.REPRODUCED.value, "terminal_reason": ""}
        self._persist(state["run_id"], "replan", update)
        return update

    def _verify(self, state: WorkflowState) -> WorkflowState:
        self._stage("verify", {"attempt": state["attempt_number"]})
        candidate = Path(state["candidate_path"])
        run_copy = self.workspace.create_run_copy(candidate, state["attempt_number"])
        report = verify_candidate(
            run_copy,
            self.settings.database_url,
            replays=5,
            benchmark_runs=self.settings.benchmark_runs,
            baseline_p95_ms=state.get("baseline_performance", {}).get("p95_latency_ms"),
            performance_limit=self.settings.performance_regression_limit,
        )
        attempts = [dict(item) for item in state["attempts"]]
        attempts[-1]["verification"] = report.model_dump(mode="json")
        if report.passed:
            diff = canonical_diff(
                self.repository_root,
                candidate,
                attempts[-1]["patch_validation"]["changed_paths"],
            )
            status = FinalStatus.VERIFIED_CANDIDATE.value
            reason = ""
        else:
            failed = [name for name, passed in report.gates.items() if not passed]
            attempts[-1]["failure_reason"] = "failed verification gates: " + ", ".join(failed)
            diff = ""
            status = (
                FinalStatus.UNVERIFIABLE_SCHEDULE.value
                if not report.gates.get("schedule_semantically_valid", False)
                else FinalStatus.UNRESOLVED.value
            )
            reason = attempts[-1]["failure_reason"]
        update: WorkflowState = {
            "attempts": attempts,
            "status": status,
            "terminal_reason": reason,
            "final_diff": diff,
        }
        self._persist(state["run_id"], "verify", update)
        return update

    def _route_after_verify(self, state: WorkflowState) -> Literal["retry", "finalize"]:
        if state.get("status") == FinalStatus.VERIFIED_CANDIDATE.value:
            return "finalize"
        if state.get("attempt_number", 0) < self.settings.max_repair_attempts:
            return "retry"
        return "finalize"

    def _finalize(self, state: WorkflowState) -> WorkflowState:
        self._stage("finalize", {"status": state.get("status")})
        self._persist(state["run_id"], "finalize", {"status": state.get("status", "")})
        return state

    def _build_graph(self):
        graph = StateGraph(WorkflowState)
        graph.add_node("inspect", self._inspect)
        graph.add_node("hypothesize", self._hypothesize)
        graph.add_node("execute", self._execute)
        graph.add_node("repair", self._repair)
        graph.add_node("retry", self._retry)
        graph.add_node("verify", self._verify)
        graph.add_node("finalize", self._finalize)
        graph.add_edge(START, "inspect")
        graph.add_edge("inspect", "hypothesize")
        graph.add_edge("hypothesize", "execute")
        graph.add_conditional_edges("execute", self._route_after_execute)
        graph.add_conditional_edges("repair", self._route_after_repair)
        graph.add_edge("retry", "repair")
        graph.add_conditional_edges("verify", self._route_after_verify)
        graph.add_edge("finalize", END)
        return graph.compile(checkpointer=InMemorySaver())

    def run(self, run_id: str | None = None) -> RunReport:
        run_id = run_id or uuid.uuid4().hex[:12]
        initial: WorkflowState = {
            "run_id": run_id,
            "status": FinalStatus.SUSPECTED.value,
            "attempts": [],
            "attempt_number": 0,
        }
        final = self.graph.invoke(
            initial,
            config={"configurable": {"thread_id": run_id}, "recursion_limit": 30},
        )
        report = RunReport(
            run_id=run_id,
            finished_at=datetime.now(UTC),
            target_operation="raceproof.sample.inventory.purchase_inventory",
            status=FinalStatus(final["status"]),
            findings=final.get("findings", []),
            baseline=final.get("baseline"),
            attempts=final.get("attempts", []),
            final_diff=final.get("final_diff") or None,
            events=self.recorder.snapshot(),
            limitations=[
                "The implemented detector and scheduler target synchronous Python, SQLAlchemy 2.x, and PostgreSQL.",
                "Verification covers named finite schedules and is not a proof of race freedom.",
                final.get("terminal_reason", ""),
            ],
        )
        output = self.repository_root / self.settings.artifact_dir / "runs" / run_id
        output.mkdir(parents=True, exist_ok=True)
        (output / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        if report.final_diff:
            (output / "candidate.diff").write_text(report.final_diff, encoding="utf-8")
        return report
