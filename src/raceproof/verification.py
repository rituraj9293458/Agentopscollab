from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from raceproof.contracts import VerificationReport


def verify_candidate(
    candidate: Path,
    database_url: str,
    replays: int = 5,
    benchmark_runs: int = 10,
    baseline_p95_ms: float | None = None,
    performance_limit: float = 2.5,
    timeout_seconds: int = 180,
) -> VerificationReport:
    env = {**os.environ, "PYTHONPATH": str(candidate / "src")}
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "raceproof.verify_worker",
            "--database-url",
            database_url,
            "--root",
            str(candidate),
            "--replays",
            str(replays),
            "--benchmark-runs",
            str(benchmark_runs),
            *(["--baseline-p95-ms", str(baseline_p95_ms)] if baseline_p95_ms is not None else []),
            "--performance-limit",
            str(performance_limit),
        ],
        cwd=candidate,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        shell=False,
        check=False,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"verification worker produced no report: {completed.stderr[-4000:]}")
    try:
        return VerificationReport.model_validate(json.loads(lines[-1]))
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"verification worker returned invalid JSON: {exc}; stderr={completed.stderr[-2000:]}"
        ) from exc
