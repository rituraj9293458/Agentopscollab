from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from raceproof.config import Settings
from raceproof.contracts import FailureBundle, FinalStatus, PatchProposal
from raceproof.workflow import RaceProofRunner

pytestmark = pytest.mark.integration


class UnavailableModel:
    def available(self):
        return False, "test model intentionally unavailable"

    def propose(self, bundle):  # pragma: no cover
        raise AssertionError("must not be called")


class GeneratedRepairTestDouble:
    """Controlled orchestration double. It is not presented as live model reasoning."""

    def available(self):
        return True, "test double"

    def propose(self, bundle: FailureBundle) -> PatchProposal:
        path = "src/raceproof/sample/inventory.py"
        before = bundle.source_files[path]
        after = before.replace(
            "from sqlalchemy import select", "from sqlalchemy import select, update"
        )
        start = "    product = session.scalar(select(Product).where(Product.id == product_id))\n"
        end = "    return True\n"
        left = after.index(start)
        right = after.index(end, left) + len(end)
        replacement = """    checkpoint(actor_id, \"before_claim\")
    claim = session.execute(
        update(Product)
        .where(Product.id == product_id, Product.available_stock > 0)
        .values(available_stock=Product.available_stock - 1)
    )
    if claim.rowcount != 1:
        return False
    session.add(Order(product_id=product_id, actor_id=actor_id))
    session.flush()
    checkpoint(actor_id, \"after_claim\")
    return True
"""
        after = after[:left] + replacement + after[right:]
        body = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        return PatchProposal(
            diagnosis="Two transactions use the same stale stock value.",
            strategy="Atomic conditional update",
            assumptions=["Product row exists before purchase."],
            unified_diff=f"diff --git a/{path} b/{path}\n{body}",
            expected_sql_shape=["UPDATE products", "available_stock > 0"],
            schedule_anchor_hint="before_claim",
            residual_risks=["Only the inventory operation is changed."],
        )


def settings_for(tmp_path: Path, database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        artifact_dir=tmp_path / "artifacts",
        max_repair_attempts=2,
        benchmark_runs=3,
        schedule_timeout_seconds=3,
    )


def test_no_key_stops_honestly_after_reproduction(tmp_path, database_url) -> None:
    root = Path(__file__).resolve().parents[1]
    report = RaceProofRunner(root, settings_for(tmp_path, database_url), UnavailableModel()).run()
    assert report.status == FinalStatus.MODEL_UNAVAILABLE
    assert report.baseline is not None and not report.baseline.invariant.passed
    assert report.final_diff is None


def test_generated_candidate_is_applied_and_verified(tmp_path, database_url) -> None:
    root = Path(__file__).resolve().parents[1]
    report = RaceProofRunner(
        root, settings_for(tmp_path, database_url), GeneratedRepairTestDouble()
    ).run()
    assert report.status == FinalStatus.VERIFIED_CANDIDATE
    assert report.final_diff and "available_stock > 0" in report.final_diff
    assert report.attempts[0].verification is not None
    assert report.attempts[0].verification.passed
