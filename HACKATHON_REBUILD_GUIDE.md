# Hackathon Rebuild Guide

This guide describes how two developers can reconstruct the essential ideas without copying the experimental repository.

## Keep the product claim narrow

Build one excellent path: synchronous Python, SQLAlchemy 2.x, PostgreSQL, and inventory overselling. The demo claim is that RaceProof reproduced one named race and a candidate passed named experiments. Do not claim general race detection or proof.

## Recommended order

### Milestone 1: database truth

Create `products` and `orders`, a reset function, and a vulnerable purchase operation. Run a single purchase and confirm one order and zero stock. Do not add LangGraph yet.

Validation: print rows from PostgreSQL after the transaction.

### Milestone 2: deterministic interleaving

Give each actor its own session. Add one semantic callback after the stock read. Use coordination events so both reads finish before A proceeds; wait for A's commit before B proceeds.

Validation: repeat at least ten times. Every run should produce the same event order and failed invariant. Treat a timeout as evidence, not a pass.

### Milestone 3: executable oracle and event contract

Define typed events and a SQL-backed invariant result. Preserve actor, sequence, transaction boundary, checkpoint, SQL shape, final rows, and error.

Validation: corrupt a seed or expected outcome and ensure the oracle fails visibly.

### Milestone 4: guarded candidates

Copy the baseline into a fresh candidate, accept a complete Git diff, reject non-allowlisted paths, run `git apply --check`, parse/compile Python, then copy to a disposable run directory.

Validation: try to edit the invariant and test files. Both must fail before execution.

### Milestone 5: candidate verifier

Launch a child Python process using candidate source. Reset PostgreSQL, execute exact or semantically adapted schedules, run regressions, and aggregate explicit gates.

Validation: the vulnerable baseline must fail. A manually created reference atomic update may test the harness, but label it reference code rather than model output.

### Milestone 6: model and graph

Define a structured proposal schema, then add one reasoning model across graph nodes. Provide exact evidence and previous failures. Cap attempts at three. The graph must have real conditional edges for reproduction, apply failure, verification failure, and success.

Validation: a test double returns malformed, unsafe, failing, and passing diffs in separate tests. A missing key returns `MODEL_UNAVAILABLE`.

### Milestone 7: API and dashboard

Stream the same backend events used by reports. Show two actor lanes, the actual invariant, graph node activity, gates, and the exact final diff.

Validation: disconnect PostgreSQL and confirm the UI shows an execution error instead of a success animation.

## Critical interfaces

```text
purchase(session, product_id, actor_id, checkpoint) -> bool
checkpoint(actor_id, semantic_name) -> None
schedule(operation) -> ScheduleResult
invariant(database) -> InvariantResult
repair(FailureBundle) -> PatchProposal
guard(diff, candidate) -> PatchValidation
verify(candidate) -> VerificationReport
```

Keep these small. They let database, model, and UI work proceed independently.

## Simplify

- One scenario, two actors, one operation.
- One model agent with specialized nodes.
- SSE instead of bidirectional sockets.
- Local files for artifacts.
- One editable application file.
- A small fixed replay count with honest labeling.

## Avoid

- Multiple agent personas.
- Random stress as the primary reproduction.
- Letting the model write tests or invariants.
- Applying attempt N on top of attempt N-1.
- Replaying stale source line numbers after a structural patch.
- Calling a reference patch model-generated.
- Building auth, queues, or deployment infrastructure before the core race works.

## Common failure modes

| Symptom | Likely cause | Debug action |
| --- | --- | --- |
| Both reads do not overlap | Checkpoint fires after commit/flush | Log transaction state at the callback |
| B writes `-1` instead of stale `0` | Relative SQL update replaced the intended vulnerable absolute write | Inspect emitted SQL and Python observed value |
| Candidate imports baseline | `PYTHONPATH` or current directory order is wrong | Print candidate module `__file__` in verifier diagnostics |
| Missing checkpoint passes | Exact replay assumes old source structure | Require supported semantic shape or mark unverifiable |
| Both atomic claims succeed | Predicate is missing or row count ignored | Record SQL and assert allowed response counts |
| UI shows stale success | Frontend has demo defaults | Render only report/event data and use pending placeholders |
| Retry compounds changes | Candidate copied from prior attempt | Recreate every candidate from baseline |

## Demo rehearsal

1. Start the disposable PostgreSQL database.
2. Run unit and integration tests.
3. Start backend and dashboard.
4. Confirm health before judges arrive.
5. Run reproduction and narrate A/B ordering.
6. Point to the SQL oracle, not an LLM explanation, for failure proof.
7. Run live repair only if a provider key is known to work.
8. If it fails, show the exact gate and `UNRESOLVED`; honesty is part of the architecture.
9. Review the final diff and limitations.

## Concepts worth retaining

Retain semantic schedules, immutable baseline and fresh attempts, structured evidence bundles, model-authored diffs, protected oracles, deterministic gate ownership, explicit terminal failures, and human approval. Everything else is replaceable implementation detail.

