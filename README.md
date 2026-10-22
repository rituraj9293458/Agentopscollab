# RaceProof

RaceProof is an experimental developer tool for investigating, reproducing, repairing, and verifying PostgreSQL concurrency defects. The included inventory scenario deliberately oversells one item by forcing this schedule with two independent SQLAlchemy sessions:

1. Actor A begins and reads stock `1`.
2. Actor B begins and reads stock `1`.
3. Actor A inserts an order, writes stock `0`, and commits.
4. Actor B inserts an order, writes its stale value `0`, and commits.
5. A deterministic SQL oracle observes two orders for one initial item.

The prototype separates model judgment from executable evidence. A model may diagnose the failure and author a unified diff. It cannot decide whether the invariant passed, edit the verifier, or promote its own patch. Every accepted candidate remains subject to human review.

## What is implemented

- Real PostgreSQL 17 execution at `READ COMMITTED` with one SQLAlchemy session per actor.
- A controlled stale-read scheduler that waits for both reads and observes A's commit before releasing B.
- Structured SQL, transaction, checkpoint, graph-stage, and invariant events.
- AST-based suspicion detection, clearly distinguished from runtime reproduction.
- A conditional LangGraph workflow with bounded repair attempts and per-node state history.
- Configurable LangChain model integration with Pydantic structured output.
- Complete model-authored unified diffs, path allowlists, protected files, `git apply --check`, syntax checks, and disposable candidate/run workspaces.
- Exact replay for unchanged stale-read operations and an adapted concurrent schedule for atomic claims or row locks.
- Regression, invariant, outcome, transaction-error, deadlock, and local performance gates.
- FastAPI status, report, and Server-Sent Events endpoints.
- A responsive React dashboard driven by real backend events.
- Unit and PostgreSQL integration tests.

`VERIFIED_CANDIDATE` means only that the candidate passed the named finite experiments. It is not a proof of race freedom.

## Architecture at a glance

```text
source + schema
      |
      v
inspect -> hypothesize -> controlled execute -> SQL invariant
                                              |
                                     reproduced failure
                                              |
                                              v
    final report <- verify <- guarded apply <- structured model repair
                       |                              ^
                       +---------- replan -----------+
                                  max 3 attempts
```

Deterministic components own scheduling, PostgreSQL execution, invariant evaluation, patch policy, regression tests, measurements, and status. The model owns diagnosis and candidate source authorship only.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer
- Git
- PostgreSQL 15 or newer, either Docker or a local isolated cluster
- An OpenAI or Anthropic key only for live repair generation

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,openai]"
Copy-Item .env.example .env
```

Choose one PostgreSQL option.

### Docker

```powershell
docker compose up -d postgres
docker compose ps
```

The Compose database is disposable and exposed on port `55432`.

### Workspace-local PostgreSQL on Windows

If PostgreSQL 17 is installed but Docker is unavailable:

```powershell
.\scripts\start_local_postgres.ps1
$env:RACEPROOF_DATABASE_URL='postgresql+psycopg://raceproof@127.0.0.1:55432/raceproof'
```

This initializes `.raceproof/postgres` with trust authentication bound only to `127.0.0.1`. It does not alter another installed PostgreSQL cluster. Stop it with `scripts/stop_local_postgres.ps1`.

Never point RaceProof at a production database. The reset operation drops and recreates the sample tables.

## Run the core experiment

Reproduce only the deterministic failure:

```powershell
raceproof reproduce
```

Run the complete graph:

```powershell
raceproof run
```

Without a model key, the graph still inspects and reproduces the failure, then ends as `MODEL_UNAVAILABLE`. This is intentional. It does not substitute a canned repair.

For live OpenAI repair:

```powershell
$env:RACEPROOF_MODEL_PROVIDER='openai'
$env:RACEPROOF_MODEL_NAME='gpt-5'
$env:OPENAI_API_KEY='your-key'
raceproof run
```

For Anthropic, install `langchain-anthropic`, set provider/name, and set `ANTHROPIC_API_KEY`.

## Backend and dashboard

Terminal 1:

```powershell
uvicorn raceproof.api:app --reload
```

Terminal 2:

```powershell
Set-Location frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to FastAPI at `127.0.0.1:8000`.

API summary:

- `GET /api/health`: backend and PostgreSQL status.
- `POST /api/runs`: start the inventory investigation.
- `GET /api/runs/{run_id}`: status, events, and completed report.
- `GET /api/runs/{run_id}/events`: live Server-Sent Events.
- `GET /api/runs/{run_id}/report`: final structured evidence.

## Tests

```powershell
pytest -q -m "not integration"
pytest -q
npm --prefix frontend run build
```

Integration tests skip if the isolated PostgreSQL URL is unreachable. They cover real oversell reproduction, database reset, timeout evidence, the reference atomic-claim harness, model-unavailable behavior, and a generated-patch test double. The test double validates orchestration only and is never reported as live autonomous reasoning.

## Artifacts

Each graph run writes:

- `artifacts/runs/<run_id>/state-history.jsonl`
- `artifacts/runs/<run_id>/report.json`
- `artifacts/runs/<run_id>/candidate.diff` only after successful verification
- `artifacts/workspaces/attempt-N/candidate` and `run`

The repository checkout is the baseline and is not modified by the repair loop.

## Configuration

See `.env.example`. Important settings are the database URL, provider/model, attempt cap, schedule timeout, benchmark sample count, and observed performance regression multiplier.

## Known limitations

- The source inspector and schedule classifier cover one synchronous Python, SQLAlchemy, PostgreSQL scenario.
- The dashboard process uses in-memory live run tracking. Durable JSON artifacts remain after restart.
- The LangGraph checkpointer is in memory for the active process; node histories are also written durably as JSONL. A production system should use `SqliteSaver` or `PostgresSaver`.
- Candidate execution is a separate process and workspace, but it is not an OS sandbox. Run untrusted model output only in a dedicated container or VM.
- The path policy is lexical plus AST/compile validation, not a complete malicious-code proof.
- Benchmarks are small local observations and are not production performance claims.
- No live provider call is claimed in the repository's tests.

See [ARCHITECTURE.md](ARCHITECTURE.md), [EXPERIMENTS.md](EXPERIMENTS.md), and [HACKATHON_REBUILD_GUIDE.md](HACKATHON_REBUILD_GUIDE.md) for the engineering rationale.

