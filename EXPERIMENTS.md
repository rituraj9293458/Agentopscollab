# Experiment Log

## E1: PostgreSQL `READ COMMITTED` stale absolute write

**Question:** Can two SQLAlchemy sessions deterministically create two orders from one available item?

**Method:** Keep both transactions open after their initial read. Release A through commit, observe its commit in the coordinator, then release B. B writes `observed_stock - 1` from its Python value.

**Expected evidence:** Both actors report accepted, orders are `2`, stock is `0`, and the invariant fails.

**Why this is plausible:** PostgreSQL `READ COMMITTED` gives each plain `SELECT` a statement-time snapshot. SQLAlchemy sessions are mutable transaction state and must not be shared across threads. Each actor therefore uses its own session.

**Status:** Implemented. Runtime results are recorded in generated reports, not hardcoded here.

## E2: Timing luck versus controlled checkpoints

**Approach rejected:** Start two threads at nearly the same time and repeat until a race appears.

**Reason:** A random overlap does not prove which schedule occurred and can disappear under logging or load. Semantic checkpoints make the sequence explicit and timeout failures diagnostic.

## E3: Missing checkpoint after repair

**Question:** If a repair replaces read/check/write with one conditional `UPDATE`, does the removed `after_read` marker count as success?

**Result:** No. Candidate source is classified into bounded semantic shapes. Atomic claims and row locks receive an adapted two-actor workload. Unknown shapes fail the schedule-validity gate. A missing marker alone never passes verification.

**Remaining risk:** Source-shape classification is narrow and can reject valid unfamiliar repairs. That is safer than claiming success without a meaningful schedule.

## E4: Atomic conditional claim

**Hypothesis:** `UPDATE products SET available_stock = available_stock - 1 WHERE id = ? AND available_stock > 0` lets the database arbitrate the claim. Under contention, a waiting updater reevaluates its predicate against the updated row and receives row count zero.

**Implementation use:** A reference operation exists only to test scheduler and verifier behavior. Live workflow repair still requires a model-authored diff.

**Acceptance:** One accepted, one rejected, invariant passed, no errors, no deadlocks, and regressions passed across named replays.

## E5: Patch containment

**Probes:** Diff to a test file, path traversal, sleeps, subprocess/network additions, malformed diff, syntax failure, and changed-line overflow.

**Expected:** Reject before candidate execution and feed exact errors to the next bounded attempt.

**Limitation:** Static policy is defense in depth, not a secure sandbox.

## E6: Model unavailable

**Question:** What happens with no provider key?

**Expected:** Inspection and real reproduction still run. Repair ends as `MODEL_UNAVAILABLE`; no patch or verified result is invented.

## E7: Persistence choice

LangGraph's in-memory checkpointer is enough for one active local run, while JSONL captures durable research history. Official guidance notes that `InMemorySaver` does not survive restarts and recommends a persistent saver for production. A hackathon implementation can add `SqliteSaver` after core evidence is stable.

## Sources checked

- [PostgreSQL transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
- [SQLAlchemy session basics and thread model](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)
- [LangGraph orchestration](https://docs.langchain.com/oss/python/langgraph/overview)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangChain structured output](https://docs.langchain.com/oss/python/langchain/structured-output)

## Future experiments

- Add a duplicate-refund scenario using a unique key plus `ON CONFLICT DO NOTHING`; do not imply exactly-once external provider effects.
- Compare row locking, atomic update, and optimistic versioning under fixed contention distributions.
- Test serializable write-skew cases with complete transaction retry.
- Record lock waits and SQLSTATEs from PostgreSQL system views.
- Run adversarial generated patches in an ephemeral no-network container.

