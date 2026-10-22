import pytest

from raceproof.database import reset_database
from raceproof.events import EventRecorder
from raceproof.sample.inventory import purchase_inventory
from raceproof.sample.reference_safe import purchase_inventory_reference
from raceproof.scheduler import ControlledScheduler

pytestmark = pytest.mark.integration


def test_controlled_schedule_reproduces_real_oversell(postgres_engine) -> None:
    recorder = EventRecorder()
    result = ControlledScheduler(postgres_engine, recorder).reproduce_stale_read(purchase_inventory)
    assert result.completed
    assert result.exact
    assert result.actor_outcomes == {"A": "accepted", "B": "accepted"}
    assert result.invariant is not None
    assert not result.invariant.passed
    assert result.invariant.successful_orders == 2


def test_reference_atomic_claim_passes_adapted_schedule(postgres_engine) -> None:
    recorder = EventRecorder()
    result = ControlledScheduler(postgres_engine, recorder).parallel_claim(
        purchase_inventory_reference
    )
    assert result.completed
    assert result.invariant is not None and result.invariant.passed
    assert sorted(result.actor_outcomes.values()) == ["accepted", "rejected"]


def test_database_reset_isolation(postgres_engine) -> None:
    recorder = EventRecorder()
    ControlledScheduler(postgres_engine, recorder).reproduce_stale_read(purchase_inventory)
    reset_database(postgres_engine)
    with postgres_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM orders").scalar_one() == 0
        assert (
            connection.exec_driver_sql(
                "SELECT available_stock FROM products WHERE id=1"
            ).scalar_one()
            == 1
        )


def test_scheduler_timeout_is_reported(postgres_engine) -> None:
    def never_reaches_anchor(session, product_id, actor_id, checkpoint):
        return True

    recorder = EventRecorder()
    result = ControlledScheduler(
        postgres_engine, recorder, timeout_seconds=0.05
    ).reproduce_stale_read(never_reaches_anchor)
    assert not result.exact
    assert "checkpoint was not reached" in (result.error or "")
