# Six-Hour Implementation Plan for Two Developers

## Outcome target

At six hours, the demo must reliably reproduce one real PostgreSQL oversell, show the trace and failed invariant, and run one model-authored candidate through protected deterministic verification. If live repair is unavailable, the demo must stop honestly after reproduction and show the evidence.

## Work split

Developer A owns PostgreSQL, scheduling, invariant, candidate execution, and tests. Developer B owns the LangGraph/model boundary, FastAPI event model, dashboard, and integration. Both review the security boundary and final demo script.

| Time | Developer A | Developer B | Go/no-go evidence |
| --- | --- | --- | --- |
| 0:00 to 0:30 | Compose, schema, vulnerable function | Skeleton graph, contracts, UI shell | Database health query succeeds |
| 0:30 to 1:30 | Two-session controlled schedule | SSE run service and live stage UI | 10 of 10 oversell replays fail invariant |
| 1:30 to 2:15 | Reset and executable oracle | Transaction lane visualization | UI shows real A/B events and final rows |
| 2:15 to 3:15 | Candidate workspace and subprocess verifier | Structured model proposal and prompt | Generated diff passes guard or gives exact rejection |
| 3:15 to 4:15 | Exact/adapted replay and gate aggregation | Conditional repair/replan graph | Safe reference strategy passes, vulnerable source fails |
| 4:15 to 5:00 | Integration and failure tests | Diff, before/after, limitation UI | Full local test suite passes |
| 5:00 to 6:00 | Harden timeouts and demo data | Polish, responsive layout, rehearsal | Fresh setup and one recorded end-to-end run |

## Essential

- Real PostgreSQL and separate transactions.
- Controlled A/B schedule.
- Approved executable invariant.
- Honest statuses and bounded attempts.
- Actual model-authored diff path.
- Protected verification files and clean candidate workspace.
- Minimal live dashboard.

## Optional after the core works

- SQLite graph checkpointer.
- Additional adjacent schedules.
- Lock-wait introspection from `pg_stat_activity`.
- Second duplicate-operation scenario with a unique constraint.
- Containerized candidate sandbox.
- Side-by-side syntax-highlighted diff.

## Highest risks

1. Transaction checkpoints accidentally flush or commit before the intended point.
2. A candidate removes the checkpoint and creates a false pass.
3. SQLAlchemy module/session state is imported from the baseline instead of the candidate.
4. LLM output is not a complete applicable diff.
5. Candidate tests mutate the same database concurrently.
6. Demo time is spent on UI before the database evidence is repeatable.

## Fallbacks

- If the model provider is unavailable, demonstrate reproduction, `MODEL_UNAVAILABLE`, and the patch contract. Do not replay a canned fix as AI output.
- If adapted scheduling cannot classify the candidate, return `UNVERIFIABLE_SCHEDULE` and show the missing semantic anchor.
- If Docker is unavailable, start an isolated local PostgreSQL cluster bound to loopback.
- If SSE reconnect behavior becomes unstable, poll `GET /api/runs/{id}` while keeping the same real event list.
- If performance samples are noisy, display measurements without a comparative pass claim.

