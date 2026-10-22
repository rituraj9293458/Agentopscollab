from raceproof.contracts import FinalStatus, InvariantResult, RunReport


def test_report_requires_human_approval_by_default() -> None:
    report = RunReport(
        run_id="test-run",
        target_operation="sample.purchase",
        status=FinalStatus.REPRODUCED,
    )
    assert report.human_approval_required is True


def test_invariant_is_explicit_evidence() -> None:
    result = InvariantResult(
        passed=False,
        initial_stock=1,
        successful_orders=2,
        final_stock=0,
        explanation="oversold",
    )
    assert not result.passed
    assert result.successful_orders > result.initial_stock
