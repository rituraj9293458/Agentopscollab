from __future__ import annotations

import math
import statistics
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from raceproof.contracts import (
    EventKind,
    InvariantResult,
    PerformanceResult,
    ScheduleResult,
)
from raceproof.database import actor_session, read_final_state, reset_database, session_factory
from raceproof.events import EventRecorder

PurchaseOperation = Callable[[Session, int, str, Callable[[str, str], None]], bool]


def evaluate_inventory_invariant(engine: Engine, initial_stock: int = 1) -> InvariantResult:
    final_stock, orders = read_final_state(engine)
    passed = orders <= initial_stock and final_stock == initial_stock - orders
    return InvariantResult(
        passed=passed,
        initial_stock=initial_stock,
        successful_orders=orders,
        final_stock=final_stock,
        explanation=(
            f"orders={orders}, initial_stock={initial_stock}, final_stock={final_stock}; "
            "required orders <= initial_stock and final_stock = initial_stock - orders"
        ),
    )


class ControlledScheduler:
    def __init__(self, engine: Engine, recorder: EventRecorder, timeout_seconds: float = 8) -> None:
        self.engine = engine
        self.recorder = recorder
        self.timeout_seconds = timeout_seconds
        self.factory = session_factory(engine)

    def reproduce_stale_read(self, operation: PurchaseOperation) -> ScheduleResult:
        """Force A.read, B.read, A.commit, B.commit using two real transactions."""
        started = time.perf_counter()
        reset_database(self.engine)
        reached = {actor: threading.Event() for actor in ("A", "B")}
        release = {actor: threading.Event() for actor in ("A", "B")}
        committed = {actor: threading.Event() for actor in ("A", "B")}
        done = {actor: threading.Event() for actor in ("A", "B")}
        outcomes: dict[str, str] = {}
        errors: list[str] = []

        def checkpoint(actor: str, name: str) -> None:
            self.recorder.add(EventKind.CHECKPOINT, "execute", name, actor)
            if name == "after_read":
                reached[actor].set()
                if not release[actor].wait(self.timeout_seconds):
                    raise TimeoutError(f"{actor} timed out waiting for release at {name}")

        def worker(actor: str) -> None:
            try:
                self.recorder.add(EventKind.TRANSACTION, "execute", "BEGIN", actor)
                with actor_session(self.factory, actor) as session:
                    with session.begin():
                        accepted = operation(session, 1, actor, checkpoint)
                    outcomes[actor] = "accepted" if accepted else "rejected"
                self.recorder.add(EventKind.TRANSACTION, "execute", "COMMIT", actor)
                committed[actor].set()
            except Exception as exc:  # noqa: BLE001 - worker evidence must not be hidden
                outcomes[actor] = "error"
                errors.append(f"{actor}: {type(exc).__name__}: {exc}")
                self.recorder.add(
                    EventKind.ERROR,
                    "execute",
                    "ROLLBACK",
                    actor,
                    {"error": f"{type(exc).__name__}: {exc}"},
                )
            finally:
                done[actor].set()

        threads = [
            threading.Thread(target=worker, args=(actor,), daemon=True) for actor in ("A", "B")
        ]
        for thread in threads:
            thread.start()

        exact = reached["A"].wait(self.timeout_seconds) and reached["B"].wait(self.timeout_seconds)
        if exact:
            release["A"].set()
            if not committed["A"].wait(self.timeout_seconds):
                errors.append("A did not commit before scheduler released B")
            release["B"].set()
        else:
            errors.append("required after_read checkpoint was not reached by both actors")
            release["A"].set()
            release["B"].set()

        for thread in threads:
            thread.join(self.timeout_seconds)
        completed = all(flag.is_set() for flag in done.values()) and not any(
            thread.is_alive() for thread in threads
        )
        if not completed:
            errors.append("scheduler timeout: one or more actors did not finish")
        invariant = evaluate_inventory_invariant(self.engine)
        self.recorder.add(
            EventKind.INVARIANT,
            "evaluate",
            "PASS" if invariant.passed else "FAIL",
            detail=invariant.model_dump(),
        )
        return ScheduleResult(
            schedule_name="stale_read_a_then_b",
            exact=exact,
            completed=completed,
            actor_outcomes=outcomes,
            events=self.recorder.snapshot(),
            invariant=invariant,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            error="; ".join(errors) or None,
        )

    def parallel_claim(self, operation: PurchaseOperation) -> ScheduleResult:
        """Adapted replay for operations whose structure removed the stale-read anchor."""
        started = time.perf_counter()
        reset_database(self.engine)
        gate = threading.Barrier(2, timeout=self.timeout_seconds)
        outcomes: dict[str, str] = {}
        errors: list[str] = []

        def checkpoint(actor: str, name: str) -> None:
            self.recorder.add(EventKind.CHECKPOINT, "verify", name, actor)
            if name == "before_claim":
                gate.wait()

        def worker(actor: str) -> None:
            try:
                self.recorder.add(EventKind.TRANSACTION, "verify", "BEGIN", actor)
                with actor_session(self.factory, actor) as session:
                    with session.begin():
                        accepted = operation(session, 1, actor, checkpoint)
                    outcomes[actor] = "accepted" if accepted else "rejected"
                self.recorder.add(EventKind.TRANSACTION, "verify", "COMMIT", actor)
            except Exception as exc:  # noqa: BLE001 - report arbitrary candidate failures
                outcomes[actor] = "error"
                if isinstance(exc, DBAPIError) and getattr(exc.orig, "sqlstate", None):
                    errors.append(f"{actor}: SQLSTATE {exc.orig.sqlstate}: {exc}")
                else:
                    errors.append(f"{actor}: {type(exc).__name__}: {exc}")

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker, actor) for actor in ("A", "B")]
            try:
                for future in futures:
                    future.result(timeout=self.timeout_seconds * 2)
            except TimeoutError:
                errors.append("adapted parallel schedule timed out")

        invariant = evaluate_inventory_invariant(self.engine)
        completed = len(outcomes) == 2 and "error" not in outcomes.values()
        return ScheduleResult(
            schedule_name="parallel_claim_adapted",
            exact=False,
            completed=completed,
            actor_outcomes=outcomes,
            events=self.recorder.snapshot(),
            invariant=invariant,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            error="; ".join(errors) or None,
        )


def benchmark_operation(
    engine: Engine,
    operation: PurchaseOperation,
    runs: int = 20,
    timeout_seconds: float = 8,
) -> PerformanceResult:
    latencies: list[float] = []
    successes = rejections = errors = deadlocks = 0
    wall_start = time.perf_counter()
    for _ in range(runs):
        recorder = EventRecorder()
        result = ControlledScheduler(engine, recorder, timeout_seconds).parallel_claim(operation)
        latencies.append(result.elapsed_ms)
        successes += sum(value == "accepted" for value in result.actor_outcomes.values())
        rejections += sum(value == "rejected" for value in result.actor_outcomes.values())
        errors += sum(value == "error" for value in result.actor_outcomes.values())
        if result.error and "40P01" in result.error:
            deadlocks += 1
    total_seconds = max(time.perf_counter() - wall_start, 0.000001)
    sorted_latencies = sorted(latencies)
    p95_index = max(0, math.ceil(0.95 * len(sorted_latencies)) - 1)
    return PerformanceResult(
        runs=runs,
        successes=successes,
        rejections=rejections,
        errors=errors,
        mean_latency_ms=statistics.fmean(latencies),
        p95_latency_ms=sorted_latencies[p95_index],
        throughput_per_second=(runs * 2) / total_seconds,
        deadlocks=deadlocks,
    )
