# Experiment Log

## E1: Inventory stale write

**Question:** Can two independent SQLAlchemy transactions consume one observed unit?

**Method:** The target contract waits for both actors at `after_read`, releases A through commit, then releases B with its stale Python object.

**Executable oracle:** `final_stock >= 0 and final_stock + committed_orders == initial_stock`.

**Expected failure evidence:** Both actors return `accepted`, two orders commit, final stock is zero, and conservation fails.

**Status:** Reproduced on real PostgreSQL through the generic scheduler.

## E2: Booking double reservation

**Question:** Does the same engine reproduce a different defect shape in another application?

**Method:** Each actor checks the booking count for one resource. The schedule holds both after the availability read, commits A, then releases B to insert its stale decision.

**Executable oracle:** `active_bookings_per_resource <= 1`.

**Expected failure evidence:** Both actors return `accepted`, two bookings commit for one resource, and exclusivity fails.

**Status:** Reproduced on real PostgreSQL through the same scheduler and report contracts. Core code contains no booking imports.

## E3: Missing checkpoint after repair

**Question:** Does removal of `after_read` count as a successful exact replay?

**Method:** A test adapter completes without emitting the required marker. A generated atomic inventory candidate also removes the stale-read checkpoint.

**Result:** The exact schedule is `INVALID` when actors finish without the checkpoint, or `TIMED_OUT` when locking prevents all actors from reaching it. Neither result is a pass. The verifier proceeds only to a developer-declared adapted schedule.

## E4: Atomic conditional inventory claim

**Hypothesis:** An update shaped as `UPDATE ... SET stock = stock - 1 WHERE id = ? AND stock > 0` lets PostgreSQL arbitrate one remaining unit.

**Method:** A test-only generated proposal is applied through the real diff guard and disposable workspaces. Verification runs exact replay first, then the declared parallel-start fallback when the original marker is absent.

**Acceptance:** Three candidate replays each produce one accepted and one rejected actor, the invariant passes, target regressions pass, no transaction errors or deadlocks are observed, and the local performance gate passes.

**Status:** Verified as orchestration evidence. The test double is not represented as a live Gemini result.

## E5: Contract validation and isolation

**Probes:** Unapproved invariant, path traversal, shell operators, protected test edits, inserted sleeps, unknown checkpoints, and candidate mutation.

**Expected:** Reject invalid contracts or diffs before candidate execution. Keep the original target source byte-for-byte unchanged after a verified candidate run.

**Status:** Covered by unit and PostgreSQL integration tests.

## E6: Model unavailable

**Question:** What happens without provider credentials?

**Result:** Both bundled targets still run inspection and real reproduction. Repair terminates as `MODEL_UNAVAILABLE`; no canned patch or verified result is invented.

## E7: Two-agent architecture

**Decision:** Use one Investigation Agent and one Repair Agent with distinct prompts, tools, and structured outputs.

**Reason:** Hypothesis formation and patch authorship are separate reasoning problems with different permissions. A compact confirmed artifact prevents unlimited conversational coupling. Static inspection, PostgreSQL execution, invariant evaluation, patch policy, regression tests, and measurements remain deterministic, so no supervisor or verifier agent is needed.

**Test evidence:** Structured model doubles confirm source and schema reach the Investigator, a serial negative control triggers investigation replanning, a confirmed failure creates the handoff, a failed candidate verification reaches the next Repair attempt, protected edits remain rejected, and backend agent events identify their real producer. These tests validate orchestration, not live Gemini quality.

## Current validation record

The refactor is accepted only when all of these succeed locally:

```powershell
python -m ruff check src tests examples
python -m pytest -q -m "not integration"
python -m pytest -q -m integration
npm --prefix frontend run build
```

Integration tests require an isolated PostgreSQL database and are skipped if it is unavailable. Any final report must distinguish a skipped environment from a tested one.

## Next experiments

- Add an idempotency target using a unique key and `ON CONFLICT DO NOTHING` without claiming exactly-once external effects.
- Compare row locking, atomic updates, and optimistic versioning under fixed contention distributions.
- Add serializable write-skew cases with complete transaction retries.
- Record lock waits and SQLSTATEs from PostgreSQL system views.
- Execute generated candidates in ephemeral no-network containers.
