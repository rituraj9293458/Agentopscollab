from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text

from raceproof.config import get_settings
from raceproof.database import create_database_engine
from raceproof.service import RunService


class StartRunRequest(BaseModel):
    scenario: str = "inventory_oversell"


repository_root = Path(__file__).resolve().parents[2]
service = RunService(repository_root)
app = FastAPI(title="RaceProof API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, object]:
    database = False
    error = None
    try:
        engine = create_database_engine(get_settings().database_url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        database = True
    except Exception as exc:  # noqa: BLE001 - health must report any driver failure
        error = f"{type(exc).__name__}: {exc}"
    return {"service": "ok", "postgresql": database, "database_error": error}


@app.post("/api/runs", status_code=202)
def start_run(request: StartRunRequest) -> dict[str, str]:
    if request.scenario != "inventory_oversell":
        raise HTTPException(status_code=422, detail="only inventory_oversell is implemented")
    run_id = uuid.uuid4().hex[:12]
    service.start(run_id)
    return {"run_id": run_id, "status": "queued"}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, object]:
    active = service.get(run_id)
    if active is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "run_id": run_id,
        "status": active.status,
        "events": [event.model_dump(mode="json") for event in active.events],
        "report": active.report.model_dump(mode="json") if active.report else None,
        "error": active.error,
    }


@app.get("/api/runs/{run_id}/events")
def stream_events(run_id: str) -> StreamingResponse:
    active = service.get(run_id)
    if active is None:
        raise HTTPException(status_code=404, detail="run not found")

    def generate():
        for existing in active.events:
            yield f"data: {existing.model_dump_json()}\n\n"
        while True:
            event = active.updates.get()
            if event is None:
                yield "event: done\ndata: {}\n\n"
                break
            yield f"data: {event.model_dump_json()}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/runs/{run_id}/report")
def get_report(run_id: str):
    active = service.get(run_id)
    if active is None:
        raise HTTPException(status_code=404, detail="run not found")
    if active.report is None:
        raise HTTPException(status_code=409, detail="report is not ready")
    return active.report
