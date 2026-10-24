from __future__ import annotations

import json

import pytest

from raceproof.upload import (
    UploadValidationError,
    UploadedSource,
    approve_custom_contract,
    synthesize_custom_target,
)


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
