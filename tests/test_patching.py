from pathlib import Path

from raceproof.patching import PatchGuard, WorkspaceManager

GUARD = PatchGuard(
    {"src/inventory_app/operations.py"},
    ("tests", "raceproof.json", "raceproof_adapter.py"),
)


def test_patch_guard_rejects_protected_test_file() -> None:
    diff = """diff --git a/tests/test_oracle.py b/tests/test_oracle.py
--- a/tests/test_oracle.py
+++ b/tests/test_oracle.py
@@ -1 +1 @@
-assert failed
+assert passed
"""
    result = GUARD.validate(diff)
    assert not result.accepted
    assert any("not editable" in error for error in result.errors)


def test_patch_guard_rejects_generated_sleeps() -> None:
    diff = """diff --git a/src/inventory_app/operations.py b/src/inventory_app/operations.py
--- a/src/inventory_app/operations.py
+++ b/src/inventory_app/operations.py
@@ -1 +1,2 @@
 from __future__ import annotations
+time.sleep(1)
"""
    result = GUARD.validate(diff)
    assert not result.accepted
    assert "forbidden addition: time.sleep(" in result.errors


def test_workspace_keeps_external_baseline_unchanged(tmp_path: Path) -> None:
    baseline = tmp_path / "target-app"
    baseline.mkdir()
    (baseline / "source.py").write_text("original", encoding="utf-8")
    manager = WorkspaceManager(baseline, tmp_path / "engine-artifacts")
    candidate = manager.create_candidate(1)
    (candidate / "source.py").write_text("candidate", encoding="utf-8")
    assert (baseline / "source.py").read_text(encoding="utf-8") == "original"
