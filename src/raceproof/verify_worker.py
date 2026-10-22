from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from raceproof.contracts import VerificationReport
from raceproof.database import create_database_engine
from raceproof.events import EventRecorder
from raceproof.sample.inventory import purchase_inventory
from raceproof.scheduler import ControlledScheduler, benchmark_operation


def operation_shape(source: str) -> str:
    if "available_stock > 0" in source and "update(" in source:
        return "atomic_claim"
    if "with_for_update" in source:
        return "row_lock"
    if '"after_read"' in source or "'after_read'" in source:
        return "stale_read"
    return "unknown"


def verify(
    database_url: str,
    root: Path,
    replays: int,
    benchmark_runs: int,
    baseline_p95_ms: float | None = None,
    performance_limit: float = 2.5,
) -> VerificationReport:
    source_path = root / "src" / "raceproof" / "sample" / "inventory.py"
    source = source_path.read_text(encoding="utf-8")
    shape = operation_shape(source)
    engine = create_database_engine(database_url)
    results = []
    replay_mode = "exact" if shape == "stale_read" else "adapted"
    for _ in range(replays):
        recorder = EventRecorder()
        scheduler = ControlledScheduler(engine, recorder)
        if replay_mode == "exact":
            result = scheduler.reproduce_stale_read(purchase_inventory)
        else:
            result = scheduler.parallel_claim(purchase_inventory)
        results.append(result)
    schedule_valid = shape in {"stale_read", "atomic_claim", "row_lock"}
    invariants_pass = all(
        result.invariant is not None and result.invariant.passed for result in results
    )
    outcomes_valid = all(
        list(result.actor_outcomes.values()).count("accepted") == 1
        and list(result.actor_outcomes.values()).count("rejected") == 1
        for result in results
    )
    completed = all(result.completed for result in results)
    regression = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_contracts.py",
            "tests/test_patching.py",
            "tests/test_verification_shape.py",
        ],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        timeout=120,
        shell=False,
        check=False,
    )
    performance = benchmark_operation(engine, purchase_inventory, benchmark_runs)
    performance_acceptable = (
        baseline_p95_ms is None or performance.p95_latency_ms <= baseline_p95_ms * performance_limit
    )
    gates = {
        "schedule_semantically_valid": schedule_valid,
        "all_replays_completed": completed,
        "business_invariant": invariants_pass,
        "allowed_outcomes": outcomes_valid,
        "regression_tests": regression.returncode == 0,
        "no_transaction_errors": performance.errors == 0,
        "no_deadlocks": performance.deadlocks == 0,
        "performance_within_configured_limit": performance_acceptable,
    }
    return VerificationReport(
        passed=all(gates.values()),
        replay_mode=replay_mode,
        gates=gates,
        schedule_results=results,
        regression_output=(regression.stdout + regression.stderr)[-8000:],
        performance=performance,
        limitations=[
            f"Operation classified as {shape} from bounded Python/SQLAlchemy source analysis.",
            "Finite replays cover only the named two-actor inventory schedules.",
            "Performance values are local observations, not production capacity claims.",
            (
                "Candidate p95 was compared with the same local baseline and configured multiplier."
                if baseline_p95_ms is not None
                else "No comparative baseline was supplied; the performance gate was informational."
            ),
        ],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--replays", type=int, default=5)
    parser.add_argument("--benchmark-runs", type=int, default=10)
    parser.add_argument("--baseline-p95-ms", type=float)
    parser.add_argument("--performance-limit", type=float, default=2.5)
    args = parser.parse_args()
    report = verify(
        args.database_url,
        args.root.resolve(),
        args.replays,
        args.benchmark_runs,
        args.baseline_p95_ms,
        args.performance_limit,
    )
    print(report.model_dump_json())
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
