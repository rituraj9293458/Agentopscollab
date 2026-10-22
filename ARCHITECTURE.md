# RaceProof Architecture

## Trust model

RaceProof treats model output as an untrusted proposal. The central boundary is:

| Capability | Owner | Pass/fail authority |
| --- | --- | --- |
| Source prioritization and diagnosis | LLM plus static evidence | None |
| Repair source authorship | LLM | None |
| Schedule execution | Deterministic Python and PostgreSQL | Execution evidence |
| Business invariant | Approved SQL/Python oracle | Yes |
| Patch path and syntax policy | Deterministic guard | Yes |
| Regression and performance gates | Pytest and measured execution | Yes |
| Candidate acceptance | Deterministic aggregate plus human | Yes |

The product reports `SUSPECTED`, `REPRODUCED`, `VERIFIED_CANDIDATE`, `UNRESOLVED`, `MODEL_UNAVAILABLE`, `UNVERIFIABLE_SCHEDULE`, or `EXECUTION_ERROR`. A verified candidate still requires human approval.

## Components

### Inspection

`inspection.py` walks the Python AST and looks for a bounded transaction shape: a row read, check-then-act branch, dependent insert, and absolute update derived from an observed value. A static finding is a hypothesis, never a reproduced defect.

### Database and event capture

`database.py` creates a SQLAlchemy 2.x engine at PostgreSQL `READ COMMITTED`. Every actor owns a separate session and connection lifecycle. An engine event listener records real SQL with thread-local actor attribution. Parameters are intentionally excluded from the dashboard event to reduce accidental secret or PII exposure.

### Scheduler

`ControlledScheduler.reproduce_stale_read` uses thread events rather than timing luck. Each operation calls the semantic `after_read` checkpoint while its transaction remains open. The coordinator releases A, waits for its commit event, then releases B. The final query is evaluated only after both workers finish.

The candidate verifier classifies a bounded set of semantic operation shapes. If a repair removes `after_read`, it does not count a missing checkpoint as success. Atomic conditional updates and row-lock strategies use an adapted two-actor workload. Unknown shapes fail `schedule_semantically_valid`.

### Invariant

The inventory oracle requires both:

```text
successful_orders <= initial_stock
final_stock = initial_stock - successful_orders
```

The LLM cannot change this code because scheduler, invariant, tests, and fixtures are protected paths.

### Repair model

`LangChainRepairModel` initializes the configured provider only when the matching API key and provider package exist. `PatchProposal` is a Pydantic schema containing diagnosis, strategy, assumptions, a complete unified diff, expected SQL shape, anchor hint, residual risks, and `cannot_repair`.

The model receives exact source, models, schema description, actor trace, final rows, invariant result, allowed outcomes, editable paths, and prior failed attempts. Secrets and environment contents are not included.

### Patch containment

Each attempt starts from a fresh copied baseline:

```text
repository baseline (unchanged)
  artifacts/workspaces/attempt-N/candidate  model diff applied here
  artifacts/workspaces/attempt-N/run        disposable execution copy
```

The guard requires Git diff syntax, a one-file allowlist, no path traversal, a changed-line cap, no scheduling markers, no sleeps, and no process or network additions. It runs `git apply --check`, applies without a shell, parses Python AST, and runs `compileall`. The final diff is recomputed from baseline and clean candidate files so run instrumentation cannot leak.

### Verification

The worker is a separate Python process with the candidate `src` first on `PYTHONPATH`. It resets the sample schema before each schedule, executes five controlled or adapted replays, checks allowed outcomes, runs non-integration regressions, checks errors and deadlocks, and records a small local benchmark.

The current gates are:

- semantic schedule classification is supported;
- every replay completes;
- every approved invariant passes;
- each two-actor replay produces one accepted and one rejected request;
- regression tests pass;
- no transaction errors are observed;
- no deadlocks are observed.

### LangGraph

The compiled graph is:

```text
START -> inspect -> hypothesize -> execute
                                  | not reproduced
                                  v
                               finalize
                                  ^
                                  |
                        repair -> verify
                           ^         |
                           +--replan-+
```

Conditional edges enforce reproduction before repair, patch acceptance before verification, success before promotion, and the configured attempt limit. An in-memory checkpointer supports active graph state. Every node also appends a durable JSONL state record for research review.

### API and UI

FastAPI starts runs in background threads and exposes Server-Sent Events. The React dashboard renders the actual event stream, transaction lanes, invariant state, graph stages, verification gates, observed measurements, and candidate diff. It contains no prerecorded success path.

## Important decisions

1. **Controlled semantic checkpoints over simultaneous starts.** Reproduction is reliable and the intended interleaving is inspectable.
2. **Atomic conditional update as a likely inventory strategy.** PostgreSQL reevaluates an `UPDATE` predicate after waiting on a concurrent updater at `READ COMMITTED`, which makes the stock predicate an effective claim boundary. The model must still author the actual candidate.
3. **One reasoning agent across specialized graph nodes.** Multiple personas add coordination cost without increasing evidence quality for this bounded prototype.
4. **Fresh attempt from baseline.** Failed patches never accumulate hidden state.
5. **SSE over WebSockets.** The dashboard needs one-way ordered events and SSE is smaller and easier to debug.
6. **No automatic merge.** `VERIFIED_CANDIDATE` is evidence for review, not authorization to alter the baseline.

## Security boundaries and limitations

The prototype never needs a production database and resets its target schema destructively. Generated code executes in a child process with timeouts, but without OS-level isolation. A stronger implementation must run each candidate in an ephemeral container with CPU, memory, network, filesystem, and database grants restricted. Patch filtering reduces accidental scope expansion but cannot prove code is benign.

The FastAPI run store is not designed for multiple server workers. A production variant needs durable run coordination, authenticated endpoints, access control, secret redaction, artifact retention, and a database allowlist.

## Research basis

- [PostgreSQL transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
- [SQLAlchemy session basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)
- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangChain structured output](https://docs.langchain.com/oss/python/langchain/structured-output)

