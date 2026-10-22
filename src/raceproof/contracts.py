from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class FinalStatus(StrEnum):
    SUSPECTED = "SUSPECTED"
    REPRODUCED = "REPRODUCED"
    VERIFIED_CANDIDATE = "VERIFIED_CANDIDATE"
    UNRESOLVED = "UNRESOLVED"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    UNVERIFIABLE_SCHEDULE = "UNVERIFIABLE_SCHEDULE"


class EventKind(StrEnum):
    STAGE = "stage"
    TRANSACTION = "transaction"
    CHECKPOINT = "checkpoint"
    SQL = "sql"
    INVARIANT = "invariant"
    REPAIR = "repair"
    VERIFICATION = "verification"
    ERROR = "error"


class RunEvent(BaseModel):
    sequence: int
    timestamp: datetime = Field(default_factory=utc_now)
    kind: EventKind
    stage: str
    actor: str | None = None
    action: str
    detail: dict[str, Any] = Field(default_factory=dict)


class InvariantResult(BaseModel):
    name: str = "orders_do_not_exceed_initial_stock"
    passed: bool
    initial_stock: int
    successful_orders: int
    final_stock: int
    explanation: str


class ScheduleResult(BaseModel):
    schedule_name: str
    exact: bool
    completed: bool
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


class FailureBundle(BaseModel):
    target_operation: str
    source_files: dict[str, str]
    schema_ddl: str
    findings: list[StaticFinding]
    reproduced_schedule: ScheduleResult
    business_invariant: str
    allowed_outcomes: dict[str, Any]
    editable_paths: list[str]
    protected_paths: list[str]
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


class PatchValidation(BaseModel):
    accepted: bool
    errors: list[str] = Field(default_factory=list)
    changed_paths: list[str] = Field(default_factory=list)


class PerformanceResult(BaseModel):
    runs: int
    successes: int
    rejections: int
    errors: int
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
    target_operation: str
    status: FinalStatus
    findings: list[StaticFinding] = Field(default_factory=list)
    baseline: ScheduleResult | None = None
    attempts: list[RepairAttempt] = Field(default_factory=list)
    final_diff: str | None = None
    events: list[RunEvent] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    human_approval_required: bool = True
