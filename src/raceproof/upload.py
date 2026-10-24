from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

ALLOWED_SUFFIXES = {".py", ".sql"}
MAX_FILES = 200
MAX_FILE_BYTES = 512_000
MAX_TOTAL_BYTES = 5_000_000
BLOCKED_IMPORTS = {"ctypes", "multiprocessing", "os", "shutil", "socket", "subprocess"}


class UploadValidationError(ValueError):
    pass


@dataclass(frozen=True)
class UploadedSource:
    path: str
    content: bytes


def safe_upload_path(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/").lstrip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise UploadValidationError(f"unsafe upload path: {value}")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise UploadValidationError(f"unsupported file type: {value}")
    if any(part.startswith(".") for part in path.parts):
        raise UploadValidationError(f"hidden paths are not accepted: {value}")
    return path


def _function_candidates(path: str, text: str) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        return [], [f"{path}: syntax error at line {exc.lineno}"]
    blocked: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            blocked.update(alias.name.split(".")[0] for alias in node.names if alias.name.split(".")[0] in BLOCKED_IMPORTS)
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in BLOCKED_IMPORTS:
                blocked.add(root)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = {
            call.func.attr if isinstance(call.func, ast.Attribute) else call.func.id
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, (ast.Attribute, ast.Name))
        }
        signals = sorted(calls & {"add", "commit", "delete", "execute", "flush", "scalar", "scalars"})
        has_read = bool(calls & {"execute", "scalar", "scalars"})
        has_write = bool(calls & {"add", "commit", "delete", "flush", "update"})
        if not signals:
            continue
        module = path[:-3].replace("/", ".") if path.endswith(".py") else path
        candidates.append(
            {
                "entrypoint": f"{module}:{node.name}",
                "file": path,
                "function": node.name,
                "line": node.lineno,
                "signals": signals,
                "risk": "check_then_act" if has_read and has_write else "database_operation",
                "score": len(signals) + (4 if has_read and has_write else 0),
            }
        )
    warnings = [f"Blocked import detected: {name}" for name in sorted(blocked)]
    return candidates, warnings


def synthesize_custom_target(
    sources: list[UploadedSource],
    destination_root: Path,
    entrypoint: str | None = None,
) -> dict[str, Any]:
    if not sources or len(sources) > MAX_FILES:
        raise UploadValidationError(f"upload must contain 1 to {MAX_FILES} source files")
    total = sum(len(source.content) for source in sources)
    if total > MAX_TOTAL_BYTES:
        raise UploadValidationError("uploaded source exceeds the 5 MB limit")
    paths: list[PurePosixPath] = []
    for source in sources:
        path = safe_upload_path(source.path)
        if len(source.content) > MAX_FILE_BYTES:
            raise UploadValidationError(f"file exceeds 500 KB limit: {source.path}")
        paths.append(path)
    if len(paths) != len(set(paths)):
        raise UploadValidationError("upload contains duplicate paths")

    digest = hashlib.sha256()
    for path, source in sorted(zip(paths, sources), key=lambda item: str(item[0])):
        digest.update(str(path).encode())
        digest.update(source.content)
    target_id = f"custom_{digest.hexdigest()[:12]}"
    target_root = (destination_root / target_id).resolve()
    if not target_root.is_relative_to(destination_root.resolve()):
        raise UploadValidationError("custom target path escaped the artifact root")
    target_root.mkdir(parents=True, exist_ok=True)

    candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    sql_files: list[str] = []
    for path, source in zip(paths, sources):
        destination = target_root.joinpath(*path.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.content)
        if path.suffix.lower() == ".py":
            found, found_warnings = _function_candidates(
                str(path), source.content.decode("utf-8", errors="replace")
            )
            candidates.extend(found)
            warnings.extend(found_warnings)
        else:
            sql_files.append(str(path))
    candidates.sort(key=lambda item: (-item["score"], item["file"], item["line"]))
    selected = next((item for item in candidates if item["entrypoint"] == entrypoint), None)
    selected = selected or (candidates[0] if candidates else None)
    operation_name = selected["function"] if selected else "database_operation"
    resource = re.sub(r"^(create|reserve|book|update|decrement|transfer)_?", "", operation_name) or "resource"
    proposal = {
        "target_id": target_id,
        "status": "PENDING_CONTRACT_APPROVAL",
        "analysis_mode": "AST_ONLY",
        "execution_ready": False,
        "selected_operation": selected,
        "operation_candidates": candidates,
        "sql_files": sql_files,
        "actors": [
            {"id": "A", "input": {"resource_id": 1}},
            {"id": "B", "input": {"resource_id": 1}},
        ],
        "proposed_invariant": {
            "name": f"exclusive_{resource}",
            "description": f"Concurrent execution must preserve the approved business rule for {resource}.",
            "assertion": "Human must replace this with an executable application-owned invariant.",
            "approved": False,
        },
        "reproduction_schedule": {
            "name": "proposed_parallel_interleaving",
            "description": "Pause both actors after the candidate read before allowing writes.",
            "checkpoints": ["before_operation", "after_read", "after_write"],
        },
        "editable_paths": [selected["file"]] if selected else [],
        "protected_paths": ["tests", "migrations", "raceproof.json", "raceproof_adapter.py"],
        "warnings": sorted(set(warnings)),
        "files": [str(path) for path in paths],
        "execution_blocker": (
            "Custom execution is disabled until an executable human-approved invariant, adapter, "
            "and OS-level sandbox are available. Static analysis is safe to review now."
        ),
    }
    (target_root / "proposal.json").write_text(json.dumps(proposal, indent=2), encoding="utf-8")
    return proposal


def approve_custom_contract(
    custom_root: Path,
    target_id: str,
    invariant: dict[str, Any],
    actors: list[dict[str, Any]],
    editable_paths: list[str],
) -> dict[str, Any]:
    if re.fullmatch(r"custom_[0-9a-f]{12}", target_id) is None:
        raise UploadValidationError("invalid custom target id")
    proposal_path = (custom_root / target_id / "proposal.json").resolve()
    if not proposal_path.is_relative_to(custom_root.resolve()) or not proposal_path.is_file():
        raise UploadValidationError("custom target proposal not found")
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    if not invariant.get("assertion") or not invariant.get("description"):
        raise UploadValidationError("an explicit invariant assertion and description are required")
    if len(actors) < 2:
        raise UploadValidationError("at least two actor inputs are required")
    known_files = set(proposal["files"])
    approved_paths = [str(safe_upload_path(path)) for path in editable_paths]
    if not approved_paths or any(path not in known_files for path in approved_paths):
        raise UploadValidationError("editable paths must reference uploaded source files")
    proposal.update(
        {
            "status": "CONTRACT_APPROVED_ANALYSIS_ONLY",
            "actors": actors,
            "proposed_invariant": {**invariant, "approved": True},
            "editable_paths": approved_paths,
        }
    )
    proposal_path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
    return proposal
