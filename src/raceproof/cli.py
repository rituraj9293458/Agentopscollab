from __future__ import annotations

import argparse
import os
from pathlib import Path

from raceproof.config import get_settings
from raceproof.database import create_database_engine
from raceproof.events import EventRecorder
from raceproof.model import GeminiInvestigationAgent, GeminiRepairAgent
from raceproof.scheduler import ControlledScheduler
from raceproof.target import TargetRegistry, load_adapter, load_target_config
from raceproof.workflow import RaceProofRunner


def main() -> int:
    parser = argparse.ArgumentParser(prog="raceproof")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("targets", help="list bundled target applications")
    reproduce = subparsers.add_parser(
        "reproduce", help="run only the controlled PostgreSQL reproduction"
    )
    reproduce.add_argument("--config", type=Path, required=True)
    run = subparsers.add_parser("run", help="run the bounded LangGraph workflow")
    run.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    settings = get_settings()
    root = Path.cwd().resolve()
    if args.command == "targets":
        for target in TargetRegistry(root / "examples").list():
            print(f"{target.config.id}\t{target.config.name}\t{target.config.operation.callable}")
        return 0
    target = load_target_config(args.config)
    if args.command == "reproduce":
        recorder = EventRecorder()
        database_url = os.environ.get(target.config.database_url_env, settings.database_url)
        engine = create_database_engine(database_url, recorder)
        try:
            adapter = load_adapter(target)
            result = ControlledScheduler(
                engine, recorder, settings.schedule_timeout_seconds
            ).execute(
                adapter,
                target.config.actors,
                target.config.reproduction_schedule,
                exact=True,
            )
        finally:
            engine.dispose()
        print(result.model_dump_json(indent=2))
        return 0 if result.invariant and not result.invariant.passed else 2
    investigation_agent = GeminiInvestigationAgent(settings.model_name)
    repair_agent = GeminiRepairAgent(settings.model_name)
    report = RaceProofRunner(root, target, settings, investigation_agent, repair_agent).run()
    print(report.model_dump_json(indent=2))
    return (
        0 if report.status.value in {"REPRODUCED", "VERIFIED_CANDIDATE", "MODEL_UNAVAILABLE"} else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
