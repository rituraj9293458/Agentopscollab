from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class FinalStatus(StrEnum):
    SUSPECTED = "SUSPECTED"
    REPRODUCED = "REPRODUCED"
    VERIFIED_CANDIDATE = "VERIFIED_CANDIDATE"
    UNRESOLVED = "UNRESOLVED"
    UNCONFIRMED = "UNCONFIRMED"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    UNVERIFIABLE_SCHEDULE = "UNVERIFIABLE_SCHEDULE"


class EventKind(StrEnum):
    AGENT = "agent"
    STAGE = "stage"
    TRANSACTION = "transaction"
    CHECKPOINT = "checkpoint"
    SQL = "sql"
    INVARIANT = "invariant"
    REPAIR = "repair"
    VERIFICATION = "verification"
    ERROR = "error"


class ScheduleStatus(StrEnum):
    COMPLETED = "COMPLETED"
    INVALID = "INVALID"
    TIMED_OUT = "TIMED_OUT"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class RunEvent(BaseModel):
    sequence: int
    timestamp: datetime = Field(default_factory=utc_now)
    kind: EventKind
    stage: str
    actor: str | None = None
    action: str
    detail: dict[str, Any] = Field(default_factory=dict)


class InvariantResult(BaseModel):
    name: str
    passed: bool
    assertion: str
    evidence: dict[str, Any]
    explanation: str


class ScheduleAction(BaseModel):
    kind: Literal["wait_checkpoint", "release", "wait_completion", "release_all"]
    actors: list[str] = Field(default_factory=list)
    checkpoint: str | None = None

    @model_validator(mode="after")
    def validate_action(self) -> ScheduleAction:
        if self.kind in {"wait_checkpoint", "release"} and not self.checkpoint:
            raise ValueError(f"{self.kind} requires checkpoint")
        if self.kind != "release_all" and not self.actors:
            raise ValueError(f"{self.kind} requires actors")
        return self


class ScheduleSpec(BaseModel):
    name: str
    description: str
    actions: list[ScheduleAction]


class ActorSpec(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    input: dict[str, Any]


class CommandSpec(BaseModel):
    argv: list[str] = Field(min_length=1, max_length=30)
    cwd: str = "."
    timeout_seconds: int = Field(default=120, ge=1, le=600)

    @model_validator(mode="after")
    def reject_shell_syntax(self) -> CommandSpec:
        forbidden = {";", "&&", "||", "|", "`", "$((", "$("}
        if any(any(token in arg for token in forbidden) for arg in self.argv):
            raise ValueError("command arguments may not contain shell operators")
        return self


class OperationSpec(BaseModel):
    display_name: str
    callable: str
    source_files: list[str] = Field(min_length=1)
    editable_paths: list[str] = Field(min_length=1)
    protected_paths: list[str] = Field(default_factory=list)


class ApprovedInvariant(BaseModel):
    name: str
    description: str
    approved: Literal[True]


class VerificationSpec(BaseModel):
    allowed_outcomes: dict[str, int]
    regression: CommandSpec
    replay_count: int = Field(default=5, ge=1, le=50)
    benchmark_runs: int = Field(default=10, ge=3, le=200)
    performance_regression_limit: float = Field(default=2.5, ge=1, le=10)


class TargetConfig(BaseModel):
    config_version: Literal[1]
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,50}$")
    name: str
    description: str
    repository: str = "."
    python_paths: list[str] = Field(default_factory=lambda: ["src"])
    adapter_path: str
    adapter_factory: str = "create_adapter"
    database_url_env: str = "RACEPROOF_DATABASE_URL"
    operation: OperationSpec
    actors: list[ActorSpec] = Field(min_length=2, max_length=8)
    invariant: ApprovedInvariant
    reproduction_schedule: ScheduleSpec
    investigation_schedules: list[ScheduleSpec] = Field(default_factory=list)
    verification_schedules: list[ScheduleSpec] = Field(min_length=1)
    verification: VerificationSpec
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_actor_references(self) -> TargetConfig:
        actor_ids = [actor.id for actor in self.actors]
        if len(actor_ids) != len(set(actor_ids)):
            raise ValueError("actor IDs must be unique")
        known = set(actor_ids)
        for schedule in [
            self.reproduction_schedule,
            *self.investigation_schedules,
            *self.verification_schedules,
        ]:
            for action in schedule.actions:
                unknown = set(action.actors) - known
                if unknown:
                    raise ValueError(
                        f"schedule {schedule.name} references unknown actors: {sorted(unknown)}"
                    )
        return self


class ScheduleResult(BaseModel):
    schedule_name: str
    status: ScheduleStatus
    completed: bool
    exact: bool
    reproduced_failure: bool
    actor_outcomes: dict[str, str]
    events: list[RunEvent]
    invariant: InvariantResult | None = None
    elapsed_ms: float
    error: str | None = None


class StaticFinding(BaseModel):
    file: str
    line_start: int
    line_end: int
    severity: str
    signals: list[str]
    explanation: str


class InvestigationDecision(BaseModel):
    suspected_source: str
    concurrency_pattern: str
    reasoning_summary: str
    required_interleaving: list[str]
    expected_invariant_violation: str
    experiment_name: str
    confidence: float = Field(ge=0, le=1)
    supporting_evidence: list[str]
    unresolved: bool = False


class InvestigationConclusion(BaseModel):
    root_cause: str
    execution_interpretation: str
    evidence_references: list[str]
    repair_ready: bool
    additional_evidence_needed: list[str] = Field(default_factory=list)


class InvestigationContext(BaseModel):
    target_id: str
    target_name: str
    target_operation: str
    source_files: dict[str, str]
    schema_ddl: str
    findings: list[StaticFinding]
    transaction_boundaries: list[str]
    checkpoints: list[str]
    available_experiments: list[ScheduleSpec]
    invariant: ApprovedInvariant
    prior_attempts: list[InvestigationAttempt] = Field(default_factory=list)
    repair_evidence_requests: list[str] = Field(default_factory=list)


class InvestigationAttempt(BaseModel):
    number: int
    decision: InvestigationDecision
    result: ScheduleResult | None = None
    failure_reason: str | None = None


class InvestigationArtifact(BaseModel):
    target_id: str
    target_operation: str
    confirmed_vulnerability: bool
    relevant_source_spans: list[StaticFinding]
    reproduced_schedule: ScheduleResult
    sql_trace: list[RunEvent]
    violated_invariant: InvariantResult
    final_database_state: dict[str, Any]
    hypothesized_root_cause: str
    execution_interpretation: str
    evidence_references: list[str]


class FailureBundle(BaseModel):
    target_id: str
    target_operation: str
    source_files: dict[str, str]
    schema_ddl: str
    findings: list[StaticFinding]
    reproduced_schedule: ScheduleResult
    business_invariant: str
    allowed_outcomes: dict[str, Any]
    editable_paths: list[str]
    protected_paths: list[str]
    investigation_artifact: InvestigationArtifact
    previous_attempts: list[dict[str, Any]] = Field(default_factory=list)


class PatchProposal(BaseModel):
    diagnosis: str
    strategy: str
    assumptions: list[str]
    unified_diff: str
    expected_sql_shape: list[str]
    schedule_anchor_hint: str | None = None
    residual_risks: list[str]
    cannot_repair: bool = False
    request_additional_investigation: bool = False
    additional_evidence_request: list[str] = Field(default_factory=list)


class PatchValidation(BaseModel):
    accepted: bool
    errors: list[str] = Field(default_factory=list)
    changed_paths: list[str] = Field(default_factory=list)


class PerformanceResult(BaseModel):
    runs: int
    outcomes: dict[str, int]
    errors: int
    schedule_failures: int
    mean_latency_ms: float
    p95_latency_ms: float
    throughput_per_second: float
    deadlocks: int = 0
    retries: int = 0
    observed_only: bool = True


class VerificationReport(BaseModel):
    passed: bool
    replay_mode: str
    gates: dict[str, bool]
    schedule_results: list[ScheduleResult]
    regression_output: str
    performance: PerformanceResult | None
    limitations: list[str]


class RepairAttempt(BaseModel):
    number: int
    proposal: PatchProposal | None = None
    patch_validation: PatchValidation | None = None
    verification: VerificationReport | None = None
    failure_reason: str | None = None


class RunReport(BaseModel):
    run_id: str
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    target_id: str
    target_name: str
    target_operation: str
    invariant_name: str
    invariant_description: str
    status: FinalStatus
    findings: list[StaticFinding] = Field(default_factory=list)
    investigation_attempts: list[InvestigationAttempt] = Field(default_factory=list)
    investigation_artifact: InvestigationArtifact | None = None
    baseline: ScheduleResult | None = None
    attempts: list[RepairAttempt] = Field(default_factory=list)
    final_diff: str | None = None
    events: list[RunEvent] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    human_approval_required: bool = True
