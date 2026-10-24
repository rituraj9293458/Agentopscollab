# RaceProof

RaceProof is an experimental platform for investigating, reproducing, repairing, and verifying PostgreSQL concurrency defects in Python applications. The engine is application-neutral. A target application supplies a validated contract and a narrow adapter that describe its operation, actors, checkpoints, reset behavior, approved invariant, verification schedules, and regression command.

RaceProof has exactly two LLM reasoning agents. The Investigation Agent interprets approved source and schema evidence, forms a structured hypothesis, and selects an approved experiment. The Repair Agent receives only a confirmed handoff artifact, analyzes the failure, and proposes a complete unified diff. Neither agent can define the invariant, edit the scheduler, choose its own editable paths, or promote a patch. PostgreSQL execution and deterministic gates remain the authority.

`VERIFIED_CANDIDATE` means only that a patch passed the named finite experiments. It is not a proof of race freedom and it still requires human review.

## Included target applications

The examples are real mini-applications outside the RaceProof package:

| Target | Defect | Approved invariant | Expected repair family |
| --- | --- | --- | --- |
| `inventory_oversell` | Two purchases consume the same observed unit | Initial stock equals final stock plus committed orders | Atomic conditional update |
| `booking_double_reservation` | Two customers reserve one exclusive resource | At most one booking exists per resource | Row lock or database constraint |

Both targets run through the same loader, scheduler, LangGraph workflow, verifier, API, and dashboard. Core modules under `src/raceproof` do not import either application.

## Target contract

Each target repository contains a `raceproof.json` and adapter:

```text
target-app/
  raceproof.json
  raceproof_adapter.py
  src/target_package/
  tests/
```

The validated contract declares:

- repository-relative Python, source, editable, and protected paths;
- an importable application operation;
- actor IDs and structured inputs;
- one developer-approved invariant;
- approved investigation schedules, including a deterministic reproduction and optional controls;
- exact and adapted verification schedules;
- allowed outcome counts, replay count, regression command, and performance bounds;
- known target-specific limitations.

The adapter implements four application-owned capabilities: reset disposable state, run one actor transaction, evaluate the approved invariant, and return schema DDL. Invalid paths, unknown actors, unapproved invariants, shell operators, and missing required files are rejected before execution.

See [`examples/inventory_app/raceproof.json`](examples/inventory_app/raceproof.json) and [`examples/booking_app/raceproof.json`](examples/booking_app/raceproof.json).

To add a target, copy one example outside `src/raceproof`, replace its domain package and tests, implement the four `TargetAdapter` methods, declare only repository-relative paths, add a serial negative control and a reproducible checkpoint schedule, and encode the business rule as an approved deterministic invariant. Run `raceproof reproduce --config <path>` before enabling either LLM agent. Registration in the bundled dashboard additionally requires placing the target under `examples/<target-id>`.

## Workflow

```text
load -> inspect -> Investigation Agent -> execute experiment -> observe
                       ^                                |
                       +---- unconfirmed, replan -------+
                                                        |
                                               confirmed handoff
                                                        v
 human review <- verify <- guarded apply <- Repair Agent
      |                                  ^
      +-- request revision --------------+
      |
 final report
                    |                            ^
                    +------ failed gates --------+
                         bounded attempts
```

The agents use distinct LangChain prompts, structured outputs, and permissions. The engine builds one role-specific snapshot containing only each agent's approved bounded context and embeds it once in that agent's request. This avoids tool-call loops and a separate provider request for every source, schema, schedule, and feedback read. LangGraph validates the selected experiment, owns both bounded loops, and passes a compact typed artifact between them instead of an open-ended conversation.

Each repair attempt starts from the unchanged target repository. A diff can touch only declared editable paths. It is checked with `git apply --check`, parsed, compiled, and executed in a disposable copy. If the original checkpoint no longer exists, the exact schedule is marked invalid or timed out and the verifier tries only a developer-declared adapted schedule. A missing checkpoint never becomes a pass.

After every deterministic gate passes, the SQLite-checkpointed graph pauses as
`AWAITING_HUMAN_REVIEW`. The dashboard shows the complete diff, gate evidence, performance,
residual risks, usage, trace link, and stage timings. A reviewer can approve, reject, or request a
bounded revision. Only approval produces `APPROVED`; verification alone is not final acceptance.

## Requirements and setup

- Python 3.11 or newer
- Node.js 20 or newer
- Git
- PostgreSQL 15 or newer in an isolated disposable database
- A Gemini API key only for live investigation and repair generation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,gemini]"
Copy-Item .env.example .env
docker compose up -d postgres
```

Open `W:\AgentOpsDemo\.env` and replace only the placeholder in this line:

```dotenv
GEMINI_API_KEY=placeholder
```

Keep `.env` local. It is ignored by Git. Restart the backend after changing it, then run `raceproof model-status` for a no-network detection check and `raceproof validate-models` for the opt-in live capability check. Never paste a real key into source, frontend variables, logs, reports, or chat.

Optional LangSmith tracing is disabled by default. To trace a complete run, its nine workflow
stages, both agents, controlled schedules, guarded patch application, verification, and underlying
LangChain model calls, set:

```dotenv
LANGSMITH_API_KEY=your-langsmith-key
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=raceproof-local
```

Restart the backend after changing these values. Trace serialization redacts configured API keys
and PostgreSQL URL passwords. Traces intentionally include approved source, candidate diffs, SQL
evidence, and structured model results, so enable tracing only for a LangSmith workspace where that
code and evidence may be stored.

If Docker is unavailable on Windows and PostgreSQL 17 is installed:

```powershell
.\scripts\start_local_postgres.ps1
$env:RACEPROOF_DATABASE_URL='postgresql+psycopg://raceproof@127.0.0.1:55432/raceproof'
```

Never point RaceProof at a production database. Target adapters are explicitly authorized to reset their own tables.

## CLI

List bundled targets:

```powershell
raceproof targets
```

Reproduce either defect without an API key:

```powershell
raceproof reproduce --config examples/inventory_app/raceproof.json
raceproof reproduce --config examples/booking_app/raceproof.json
```

Inspect the configured roles without making a provider request:

```powershell
raceproof model-status
```

After placing the key in `.env`, validate both exact model IDs, tool calling, and structured output with an opt-in live request:

```powershell
raceproof validate-models
```

Run the bounded workflow:

```powershell
raceproof run --config examples/inventory_app/raceproof.json
```

`GOOGLE_API_KEY` is also accepted. Without a key, the autonomous workflow loads and inspects the target, then terminates honestly as `MODEL_UNAVAILABLE` before claiming LLM investigation. Deterministic reproduction remains available through `raceproof reproduce`.

The default Investigation Agent uses `gemini-3.5-flash-lite`. The Repair Agent uses `gemini-3.1-flash-lite`. Optional fallback uses `gemini-3.8-flash` and is disabled by default. Set `RACEPROOF_ENABLE_MODEL_FALLBACK=true` only after validating it. Fallback occurs only for unavailable-model or structured-output failures. It does not bypass authentication, quota, rate, or local budget failures.

Local budgets default to 12 total provider requests, 5 Investigation Agent requests, 7 Repair Agent requests, and 60,000 provider-reported tokens. A normal successful path uses one model request per agent and does not make a second Investigation Agent call after PostgreSQL has already established the result. Provider retries default to one. Request limits are enforced before a provider call. Token limits are enforced from provider metadata and stop the next call after an overrun. If metadata is missing, the report marks token totals as lower bounds. Dollar estimates are omitted unless a verified pricing table is explicitly configured.

## API and dashboard

```powershell
.\scripts\start_backend.ps1
npm --prefix frontend install
npm --prefix frontend run dev
```

The backend launcher restricts reload monitoring to `src/raceproof`. Do not run unrestricted
`uvicorn raceproof.api:app --reload` from the repository root. Repair and verification create
Python files under `artifacts/`; an unrestricted watcher would restart the API during the run and
discard its in-memory run registry. For a backend with reload disabled, use
`.\scripts\start_backend.ps1 -NoReload`.

The dashboard fetches generic target metadata and sends only a selected `target_id` when starting a run.

Verified runs also include deterministic database-behavior evidence:

- baseline and candidate SQL, actor outcomes, schedule status, and invariant result side by side;
- sampled PostgreSQL lock waits with owner, waiter, lock type, mode, duration, relation, and release point;
- a wait-for graph with explicit cycle detection and deadlock status.

Lock evidence from an exact schedule that becomes invalid after a transaction-shape change is retained
only as diagnostic evidence. It never counts as a successful replay or verification gate.

- `GET /api/targets`: list validated registered targets.
- `GET /api/health`: report service and PostgreSQL status.
- `GET /api/model-status`: report model IDs, local budgets, fallback state, and only whether a key is configured.
- `POST /api/runs`: start `{ "target_id": "inventory_oversell" }`.
- `GET /api/runs/{run_id}`: status, events, and report.
- `GET /api/runs/{run_id}/events`: Server-Sent Events stream.
- `GET /api/runs/{run_id}/report`: completed structured evidence.
- `POST /api/runs/{run_id}/review`: approve, reject, or request revision for a verified candidate.

## Verification and tests

```powershell
python -m ruff check src tests examples
pytest -q -m "not integration"
pytest -q
npm --prefix frontend run build
```

The integration suite uses real PostgreSQL. It proves that both external applications reproduce distinct invariant failures through the same engine, candidate workspaces leave source repositories unchanged, missing checkpoints are not accepted, and a generated atomic-update test candidate passes all declared gates.

## Artifacts

Runs write to the engine artifact root:

- `artifacts/runs/<run_id>/state-history.jsonl`
- `artifacts/runs/<run_id>/report.json`
- `artifacts/runs/<run_id>/candidate.diff` only for a verified candidate
- `artifacts/workspaces/attempt-N/candidate`
- `artifacts/workspaces/attempt-N/run`

## Honest limitations

- The current inspector handles synchronous Python and common SQLAlchemy read, branch, update, insert, and flush shapes.
- The two bundled targets demonstrate reuse, not universal concurrency analysis.
- Automated tests use structured model doubles and do not establish successful live Gemini reasoning.
- The live `validate-models` command is opt-in, consumes provider quota, and was not run unless a real key was configured.
- Verification covers configured finite schedules and outcomes, not all possible interleavings.
- Candidate code runs in a child process and disposable workspace, but not an OS sandbox. Use a restricted container or VM for untrusted generated code.
- The API run registry is in memory. Paused human-review runs are recoverable after a restart from their persisted report and SQLite LangGraph checkpoint. Completed reports are durable and reloadable by run ID.
- Patch filtering is defense in depth and cannot prove arbitrary generated code is benign.
- Performance results are local observations, not production capacity claims.

See [ARCHITECTURE.md](ARCHITECTURE.md) and [EXPERIMENTS.md](EXPERIMENTS.md) for boundaries and evidence.
