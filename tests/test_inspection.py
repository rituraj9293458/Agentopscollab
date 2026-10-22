from pathlib import Path

from raceproof.inspection import inspect_python_file


def test_inspector_flags_read_check_write_shape() -> None:
    root = Path(__file__).resolve().parents[1]
    findings = inspect_python_file(root / "src/raceproof/sample/inventory.py", root)
    assert len(findings) == 1
    assert "check then act" in findings[0].signals
    assert "absolute update derived from observed value" in findings[0].signals
    assert "hypothesis only" in findings[0].explanation
