from __future__ import annotations

import ast
from pathlib import Path

from raceproof.contracts import StaticFinding


class ConcurrencyInspector(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.findings: list[StaticFinding] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        source_signals: list[str] = []
        has_select = any(
            isinstance(child, ast.Call) and _call_name(child.func) == "select"
            for child in ast.walk(node)
        )
        has_if = any(isinstance(child, ast.If) for child in ast.walk(node))
        has_subtract_assignment = any(
            isinstance(child, ast.Assign)
            and isinstance(child.value, ast.BinOp)
            and isinstance(child.value.op, ast.Sub)
            for child in ast.walk(node)
        )
        has_order_insert = any(
            isinstance(child, ast.Call) and _call_name(child.func) == "Order"
            for child in ast.walk(node)
        )
        if has_select:
            source_signals.append("row read")
        if has_if:
            source_signals.append("check then act")
        if has_subtract_assignment:
            source_signals.append("absolute update derived from observed value")
        if has_order_insert:
            source_signals.append("dependent insert")
        if len(source_signals) >= 3:
            self.findings.append(
                StaticFinding(
                    file=self.relative_path,
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno),
                    severity="high",
                    signals=source_signals,
                    explanation=(
                        "Static analysis found a read/check/write transaction shape. This is a "
                        "hypothesis only until a real schedule violates the approved invariant."
                    ),
                )
            )
        self.generic_visit(node)


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def inspect_python_file(path: Path, repository_root: Path) -> list[StaticFinding]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    inspector = ConcurrencyInspector(path.relative_to(repository_root).as_posix())
    inspector.visit(tree)
    return inspector.findings
