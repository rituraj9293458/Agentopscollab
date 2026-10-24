from __future__ import annotations

import json

import pytest

from raceproof.events import EventRecorder
from raceproof.scheduler import ControlledScheduler
from raceproof.upload import (
    UploadValidationError,
    UploadedSource,
    analyze_approved_custom_target,
    approve_custom_contract,
    synthesize_custom_target,
)
from raceproof.target import load_adapter, load_target_config


SOURCE = b"""
from sqlalchemy import select

def reserve_resource(session, resource_id):
    existing = session.scalar(select(Booking).where(Booking.resource_id == resource_id))
    if existing is None:
        session.add(Booking(resource_id=resource_id))
        session.flush()
"""


def test_upload_synthesizes_static_contract_without_execution(tmp_path):
    proposal = synthesize_custom_target(
        [UploadedSource("src/app/operations.py", SOURCE)], tmp_path
    )
    assert proposal["status"] == "PENDING_CONTRACT_APPROVAL"
    assert proposal["analysis_mode"] == "AST_ONLY"
    assert proposal["execution_ready"] is False
    assert proposal["selected_operation"]["function"] == "reserve_resource"
    assert proposal["selected_operation"]["risk"] == "check_then_act"
    assert proposal["selected_operation"]["patch_status"] == "UNVERIFIED_STATIC_SUGGESTION"
    assert ".with_for_update()" in proposal["selected_operation"]["suggested_patch"]
    assert (tmp_path / proposal["target_id"] / "src/app/operations.py").is_file()


def test_upload_rejects_path_traversal(tmp_path):
    with pytest.raises(UploadValidationError, match="unsafe upload path"):
        synthesize_custom_target([UploadedSource("../escape.py", SOURCE)], tmp_path)


def test_contract_approval_stays_analysis_only(tmp_path):
    proposal = synthesize_custom_target(
        [UploadedSource("src/app/operations.py", SOURCE)], tmp_path
    )
    approved = approve_custom_contract(
        tmp_path,
        proposal["target_id"],
        {
            "name": "exclusive_resource",
            "description": "Only one active booking is allowed.",
            "assertion": "active_bookings_per_resource <= 1",
        },
        proposal["actors"],
        proposal["editable_paths"],
    )
    assert approved["status"] == "CONTRACT_APPROVED_ANALYSIS_ONLY"
    assert approved["proposed_invariant"]["approved"] is True
    persisted = json.loads(
        (tmp_path / proposal["target_id"] / "proposal.json").read_text(encoding="utf-8")
    )
    assert persisted["proposed_invariant"]["assertion"] == (
        "active_bookings_per_resource <= 1"
    )


def test_blocked_import_is_reported(tmp_path):
    proposal = synthesize_custom_target(
        [UploadedSource("danger.py", b"import subprocess\n" + SOURCE)], tmp_path
    )
    assert "Blocked import detected: subprocess" in proposal["warnings"]


def test_universal_scan_finds_django_class_method_and_suggests_patch(tmp_path):
    source = b"""
class AccountService:
    def withdraw(self, account_id, amount):
        account = Account.objects.get(id=account_id)
        if account.balance >= amount:
            account.balance -= amount
            account.save()
"""
    proposal = synthesize_custom_target([UploadedSource("service.py", source)], tmp_path)
    finding = proposal["selected_operation"]
    assert finding["function"] == "withdraw"
    assert finding["framework"] == "django"
    assert finding["risk"] == "check_then_act"
    assert ".select_for_update().get" in finding["suggested_patch"]


def test_universal_scan_finds_raw_sql_read_write_and_suggests_patch(tmp_path):
    source = b'''def reserve(cursor, item_id):
    cursor.execute("SELECT available FROM items WHERE id = %s", (item_id,))
    if cursor.fetchone()[0]:
        cursor.execute("UPDATE items SET available = false WHERE id = %s", (item_id,))
'''
    proposal = synthesize_custom_target([UploadedSource("queries.py", source)], tmp_path)
    finding = proposal["selected_operation"]
    assert finding["framework"] == "raw_sql"
    assert finding["risk"] == "check_then_act"
    assert "FOR UPDATE" in finding["suggested_patch"]


def test_approved_custom_analysis_reviews_every_uploaded_file(tmp_path):
    proposal = synthesize_custom_target(
        [
            UploadedSource("first.py", SOURCE),
            UploadedSource(
                "second.py",
                b"def update_name(session, item):\n    session.execute(item)\n",
            ),
            UploadedSource("queries.sql", b"SELECT * FROM bookings FOR UPDATE;"),
        ],
        tmp_path,
    )
    approve_custom_contract(
        tmp_path,
        proposal["target_id"],
        {
            "name": "exclusive_resource",
            "description": "Only one active booking is allowed.",
            "assertion": "active_bookings_per_resource <= 1",
        },
        proposal["actors"],
        proposal["editable_paths"],
    )

    result = analyze_approved_custom_target(tmp_path, proposal["target_id"])

    assert result["status"] == "CUSTOM_ANALYSIS_COMPLETE"
    assert result["files_scanned"] == 3
    assert result["operations_reviewed"] == 2
    assert result["high_risk_operations"] == 1
    assert result["execution_performed"] is False
    assert all(
        finding["invariant_assertion"] == "active_bookings_per_resource <= 1"
        for finding in result["findings"]
    )
    sql_result = next(item for item in result["file_results"] if item["kind"] == "sql")
    assert sql_result["uses_for_update"] is True


def test_static_analysis_needs_no_human_invariant_before_scanning(tmp_path):
    proposal = synthesize_custom_target(
        [UploadedSource("withdrawals.py", SOURCE.replace(b"reserve_resource", b"withdraw_funds"))],
        tmp_path,
    )

    result = analyze_approved_custom_target(tmp_path, proposal["target_id"])

    assert result["status"] == "STATIC_ANALYSIS_COMPLETE"
    assert result["findings"][0]["invariant_source"] == "suggested"
    assert result["findings"][0]["invariant_assertion"] == (
        "account.balance >= 0 AND total_withdrawals <= initial_balance"
    )
    assert "suggested invariant" in result["limitations"][1].lower()


def test_placeholder_cannot_be_approved_as_an_invariant(tmp_path):
    proposal = synthesize_custom_target(
        [UploadedSource("src/app/operations.py", SOURCE)], tmp_path
    )
    with pytest.raises(UploadValidationError, match="explicit invariant"):
        approve_custom_contract(
            tmp_path,
            proposal["target_id"],
            {
                "name": "exclusive_resource",
                "description": "Only one active booking is allowed.",
                "assertion": "Human must replace this with an executable application-owned invariant.",
            },
            proposal["actors"],
            proposal["editable_paths"],
        )


def test_supported_withdrawal_upload_builds_executable_target(tmp_path):
    withdrawal_source = (
        __import__("pathlib").Path("custom_upload_samples/account_double_withdrawal.py")
        .read_bytes()
    )
    proposal = synthesize_custom_target(
        [UploadedSource("withdrawal.py", withdrawal_source)], tmp_path
    )
    prepared = approve_custom_contract(
        tmp_path,
        proposal["target_id"],
        {
            "name": "withdrawals_within_balance",
            "description": "Withdrawals cannot exceed the initial balance.",
            "assertion": "account.balance >= 0 AND total_withdrawals <= initial_balance",
        },
        proposal["actors"],
        proposal["editable_paths"],
    )

    assert prepared["execution_ready"] is True
    config_path = tmp_path / proposal["target_id"] / prepared["executable_config"]
    target = load_target_config(config_path, allowed_roots=[tmp_path])
    adapter = load_adapter(target)
    assert adapter.config.id == proposal["target_id"]
    instrumented = (
        config_path.parent / target.config.operation.source_files[0]
    ).read_text(encoding="utf-8")
    assert 'checkpoint(actor_id, "after_read")' in instrumented
    assert 'checkpoint(actor_id, "after_write")' in instrumented


@pytest.mark.integration
def test_generated_withdrawal_adapter_reproduces_real_postgres_failure(
    tmp_path, postgres_engine
):
    withdrawal_source = (
        __import__("pathlib").Path("custom_upload_samples/account_double_withdrawal.py")
        .read_bytes()
    )
    proposal = synthesize_custom_target(
        [UploadedSource("withdrawal.py", withdrawal_source)], tmp_path
    )
    prepared = approve_custom_contract(
        tmp_path,
        proposal["target_id"],
        {
            "name": "withdrawals_within_balance",
            "description": "Withdrawals cannot exceed the initial balance.",
            "assertion": "account.balance >= 0 AND total_withdrawals <= initial_balance",
        },
        proposal["actors"],
        proposal["editable_paths"],
    )
    target = load_target_config(
        tmp_path / proposal["target_id"] / prepared["executable_config"],
        allowed_roots=[tmp_path],
    )

    result = ControlledScheduler(
        postgres_engine, EventRecorder(), timeout_seconds=3
    ).execute(
        load_adapter(target),
        target.config.actors,
        target.config.reproduction_schedule,
        exact=True,
    )

    assert result.completed
    assert result.reproduced_failure
    assert result.invariant is not None and not result.invariant.passed
    assert result.invariant.evidence["total_withdrawals"] == 160.0


@pytest.mark.integration
def test_generated_inventory_adapter_reproduces_real_postgres_failure(
    tmp_path, postgres_engine
):
    inventory_source = (
        __import__("pathlib").Path("custom_upload_samples/inventory_lost_update.py")
        .read_bytes()
    )
    proposal = synthesize_custom_target(
        [UploadedSource("inventory.py", inventory_source)], tmp_path
    )
    prepared = approve_custom_contract(
        tmp_path,
        proposal["target_id"],
        {
            "name": "inventory_conservation",
            "description": "Stock must match accepted sales.",
            "assertion": "product.stock >= 0 AND stock = initial_stock - accepted_quantity",
        },
        proposal["actors"],
        proposal["editable_paths"],
    )
    target = load_target_config(
        tmp_path / proposal["target_id"] / prepared["executable_config"],
        allowed_roots=[tmp_path],
    )

    result = ControlledScheduler(
        postgres_engine, EventRecorder(), timeout_seconds=3
    ).execute(
        load_adapter(target),
        target.config.actors,
        target.config.reproduction_schedule,
        exact=True,
    )

    assert result.completed
    assert result.reproduced_failure
    assert result.invariant is not None and not result.invariant.passed
    assert result.invariant.evidence["accepted_quantity"] == 13
