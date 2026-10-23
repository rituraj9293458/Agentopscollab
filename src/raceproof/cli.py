from __future__ import annotations

import argparse
from pathlib import Path

from raceproof.config import get_settings
from raceproof.database import create_database_engine
from raceproof.events import EventRecorder
from raceproof.model import GeminiRepairModel
from raceproof.sample.inventory import purchase_inventory
from raceproof.scheduler import ControlledScheduler
from raceproof.workflow import RaceProofRunner


def main() -> int:
    parser = argparse.ArgumentParser(prog="raceproof")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("reproduce", help="run only the controlled PostgreSQL reproduction")
    subparsers.add_parser("run", help="run the bounded LangGraph workflow")
    args = parser.parse_args()
    settings = get_settings()
    if args.command == "reproduce":
        recorder = EventRecorder()
        engine = create_database_engine(settings.database_url, recorder)
        try:
            result = ControlledScheduler(
                engine, recorder, settings.schedule_timeout_seconds
            ).reproduce_stale_read(purchase_inventory)
        finally:
            engine.dispose()
        print(result.model_dump_json(indent=2))
        return 0 if result.invariant and not result.invariant.passed else 2
    root = Path.cwd()
    model = GeminiRepairModel(settings.model_name)
    report = RaceProofRunner(root, settings, model).run()
    print(report.model_dump_json(indent=2))
    return (
        0 if report.status.value in {"REPRODUCED", "VERIFIED_CANDIDATE", "MODEL_UNAVAILABLE"} else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
