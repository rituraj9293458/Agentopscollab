from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from raceproof.contracts import ScheduleStatus, VerificationReport
from raceproof.database import create_database_engine
from raceproof.events import EventRecorder
from raceproof.scheduler import ControlledScheduler, benchmark_schedule, outcomes_match
from raceproof.target import load_adapter, load_target_config


def _run_regression(root: Path, target) -> subprocess.CompletedProcess[str]:
    command = target.config.verification.regression
    argv = list(command.argv)
    if argv[0] in {"python", "python3"}:
        argv[0] = sys.executable
    python_paths = [str(root / path) for path in target.config.python_paths]
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([*python_paths, os.environ.get("PYTHONPATH", "")]),
    }
    return subprocess.run(
        argv,
        cwd=root / command.cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=command.timeout_seconds,
        shell=False,
        check=False,
    )


def verify(
    database_url: str,
    root: Path,
    config_relative_path: str,
    baseline_p95_ms: float | None = None,
) -> VerificationReport:
    target = load_target_config(root / config_relative_path, allowed_roots=[root])
    adapter = load_adapter(target)
    config = target.config
    engine = create_database_engine(database_url)
    selected_results = []
    attempted_modes: list[str] = []
    try:
        for _ in range(config.verification.replay_count):
            selected = None
            for index, schedule in enumerate(config.verification_schedules):
                recorder = EventRecorder()
                result = ControlledScheduler(engine, recorder).execute(
                    adapter,
                    config.actors,
                    schedule,
                    exact=index == 0,
                )
                attempted_modes.append(f"{schedule.name}:{result.status.value}")
                if result.status == ScheduleStatus.COMPLETED:
                    selected = result
                    break
            if selected is not None:
                selected_results.append(selected)

        schedule_valid = len(selected_results) == config.verification.replay_count
        invariants_pass = schedule_valid and all(
            result.invariant is not None and result.invariant.passed for result in selected_results
        )
        outcomes_valid = schedule_valid and all(
            outcomes_match(result.actor_outcomes, config.verification.allowed_outcomes)
            for result in selected_results
        )
        completed = schedule_valid and all(result.completed for result in selected_results)
        regression = _run_regression(root, target)
        performance = benchmark_schedule(
            engine,
            adapter,
            config.actors,
            config.verification_schedules[-1],
            config.verification.benchmark_runs,
        )
    finally:
        engine.dispose()

    performance_acceptable = (
        baseline_p95_ms is None
        or performance.p95_latency_ms
        <= baseline_p95_ms * config.verification.performance_regression_limit
    )
    gates = {
        "schedule_semantically_valid": schedule_valid,
        "all_replays_completed": completed,
        "business_invariant": invariants_pass,
        "allowed_outcomes": outcomes_valid,
        "regression_tests": regression.returncode == 0,
        "no_transaction_errors": performance.errors == 0,
        "benchmark_schedules_completed": performance.schedule_failures == 0,
        "no_deadlocks": performance.deadlocks == 0,
        "performance_within_configured_limit": performance_acceptable,
    }
    replay_modes = sorted({"exact" if result.exact else "adapted" for result in selected_results})
    return VerificationReport(
        passed=all(gates.values()),
        replay_mode="+".join(replay_modes) if replay_modes else "unverifiable",
        gates=gates,
        schedule_results=selected_results,
        regression_output=(regression.stdout + regression.stderr)[-8000:],
        performance=performance,
        limitations=[
            f"Target: {config.name}.",
            "Finite replays cover only the developer-declared schedules.",
            "A missing original checkpoint triggers a declared adapted schedule, never a pass.",
            "Performance values are local observations, not production capacity claims.",
            "Schedule attempts: " + ", ".join(attempted_modes),
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
    parser.add_argument("--config", default="raceproof.json")
    parser.add_argument("--baseline-p95-ms", type=float)
    args = parser.parse_args()
    report = verify(
        args.database_url,
        args.root.resolve(),
        args.config,
        args.baseline_p95_ms,
    )
    print(report.model_dump_json())
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
