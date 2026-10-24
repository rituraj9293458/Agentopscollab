from __future__ import annotations

import ast
import difflib
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

ALLOWED_SUFFIXES = {".py", ".sql"}
MAX_FILES = 200
MAX_FILE_BYTES = 512_000
MAX_TOTAL_BYTES = 5_000_000
BLOCKED_IMPORTS = {"ctypes", "multiprocessing", "os", "shutil", "socket", "subprocess"}
INVARIANT_PLACEHOLDER = "Human must replace this with an executable application-owned invariant."


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
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = {
            call.func.attr if isinstance(call.func, ast.Attribute) else call.func.id
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, (ast.Attribute, ast.Name))
        }
        source_segment = ast.get_source_segment(text, node) or ""
        sql_text = " ".join(
            item.value
            for item in ast.walk(node)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        )
        read_calls = {"execute", "scalar", "scalars", "get", "filter", "first", "one", "exists"}
        write_calls = {
            "add", "add_all", "commit", "create", "delete", "flush", "save", "update",
            "bulk_create", "bulk_update", "executemany",
        }
        signals = sorted(calls & (read_calls | write_calls))
        has_sql_read = bool(re.search(r"\bSELECT\b", sql_text, re.IGNORECASE))
        has_sql_write = bool(re.search(r"\b(INSERT|UPDATE|DELETE)\b", sql_text, re.IGNORECASE))
        has_read = bool(calls & read_calls) or has_sql_read
        has_write = bool(calls & write_calls) or has_sql_write
        if not signals:
            continue
        framework = (
            "django"
            if calls & {"save", "bulk_create", "bulk_update"}
            else "sqlalchemy"
            if calls & {"scalar", "scalars", "add", "flush"} or "select(" in source_segment
            else "raw_sql"
            if has_sql_read or has_sql_write
            else "database_api"
        )
        suggested_patch = (
            _suggest_static_patch(path, text, node, framework)
            if has_read and has_write
            else None
        )
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
                "suggested_invariant": _suggested_invariant(node.name),
                "framework": framework,
                "suggested_patch": suggested_patch,
                "patch_status": "UNVERIFIED_STATIC_SUGGESTION" if suggested_patch else "GUIDANCE_ONLY",
            }
        )
    warnings = [f"Blocked import detected: {name}" for name in sorted(blocked)]
    return candidates, warnings


def _offset(text: str, line: int, column: int) -> int:
    lines = text.splitlines(keepends=True)
    return sum(len(item) for item in lines[: line - 1]) + column


def _unified_suggestion(path: str, before: str, after: str) -> str | None:
    if before == after:
        return None
    body = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    return f"diff --git a/{path} b/{path}\n{body}"


def _suggest_static_patch(
    path: str,
    text: str,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    framework: str,
) -> str | None:
    """Create only narrow mechanical suggestions. These are never marked verified."""
    if "with_for_update" in (ast.get_source_segment(text, function) or ""):
        return None
    if framework == "sqlalchemy":
        select_call = next(
            (
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "select"
                and node.end_lineno is not None
                and node.end_col_offset is not None
            ),
            None,
        )
        if select_call is not None:
            position = _offset(text, select_call.end_lineno, select_call.end_col_offset)
            return _unified_suggestion(
                path, text, text[:position] + ".with_for_update()" + text[position:]
            )
    if framework == "django":
        read_call = next(
            (
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"get", "first"}
                and node.func.value.end_lineno is not None
                and node.func.value.end_col_offset is not None
            ),
            None,
        )
        if read_call is not None:
            position = _offset(
                text, read_call.func.value.end_lineno, read_call.func.value.end_col_offset
            )
            return _unified_suggestion(
                path, text, text[:position] + ".select_for_update()" + text[position:]
            )
    if framework == "raw_sql":
        select_literal = next(
            (
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and re.search(r"\bSELECT\b", node.value, re.IGNORECASE)
                and "FOR UPDATE" not in node.value.upper()
                and node.end_lineno is not None
                and node.end_col_offset is not None
            ),
            None,
        )
        if select_literal is not None:
            replacement = select_literal.value.rstrip().rstrip(";") + " FOR UPDATE"
            literal_source = ast.get_source_segment(text, select_literal)
            if literal_source is not None:
                start = _offset(text, select_literal.lineno, select_literal.col_offset)
                end = _offset(text, select_literal.end_lineno, select_literal.end_col_offset)
                quote = '"' if literal_source.startswith('"') else "'"
                return _unified_suggestion(
                    path, text, text[:start] + quote + replacement + quote + text[end:]
                )
    return None


def _suggested_invariant(operation_name: str) -> dict[str, str]:
    """Provide a review suggestion only. It is never treated as executable proof."""
    name = operation_name.lower()
    if any(word in name for word in ("withdraw", "transfer", "debit", "payment")):
        return {
            "name": "non_negative_balance",
            "assertion": "account.balance >= 0 AND total_withdrawals <= initial_balance",
            "description": "Concurrent withdrawals must not exceed the initial account balance.",
        }
    if any(word in name for word in ("sell", "inventory", "stock", "purchase", "decrement")):
        return {
            "name": "non_negative_stock",
            "assertion": "product.stock >= 0 AND stock = initial_stock - accepted_quantity",
            "description": "Remaining stock must equal initial stock minus accepted sales.",
        }
    if any(word in name for word in ("reserve", "book", "claim", "allocate")):
        return {
            "name": "exclusive_resource",
            "assertion": "active_records_per_resource <= 1",
            "description": "A resource that is exclusive must not be successfully claimed twice.",
        }
    return {
        "name": "application_invariant_required",
        "assertion": "Human review required: define the protected business state.",
        "description": "RaceProof found shared database access but cannot infer the domain rule safely.",
    }


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
            "assertion": "",
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
    assertion = str(invariant.get("assertion", "")).strip()
    if (
        not assertion
        or assertion == INVARIANT_PLACEHOLDER
        or assertion.lower().startswith("human must replace")
        or not invariant.get("description")
    ):
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
    return prepare_custom_executable(custom_root, target_id)


def _instrument_operation(source: str, function_name: str) -> str:
    """Add scheduler hooks to a disposable copy without changing the uploaded baseline."""
    tree = ast.parse(source)
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ),
        None,
    )
    if function is None or function.end_lineno is None:
        raise UploadValidationError("selected operation could not be instrumented")
    if function.args.vararg or function.args.kwarg:
        raise UploadValidationError("variadic operations require a manual adapter")

    lines = source.splitlines()
    signature_end = function.body[0].lineno - 1
    signature_text = "\n".join(lines[function.lineno - 1 : signature_end])
    close = signature_text.rfind(")")
    if close < 0:
        raise UploadValidationError("selected operation signature could not be instrumented")
    signature_text = signature_text[:close] + ", actor_id: str, checkpoint" + signature_text[close:]
    lines[function.lineno - 1 : signature_end] = signature_text.splitlines()

    # Reparse after the signature edit so line positions remain correct.
    updated = "\n".join(lines) + "\n"
    function = next(
        node
        for node in ast.parse(updated).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    )
    insertions: list[tuple[int, str]] = []
    for statement in function.body:
        calls = [node for node in ast.walk(statement) if isinstance(node, ast.Call)]
        attributes = {
            call.func.attr for call in calls if isinstance(call.func, ast.Attribute)
        }
        if "scalar" in attributes or "scalars" in attributes or "execute" in attributes:
            insertions.append((statement.end_lineno or statement.lineno, '    checkpoint(actor_id, "after_read")'))
            break
    for statement in function.body:
        calls = [node for node in ast.walk(statement) if isinstance(node, ast.Call)]
        attributes = {
            call.func.attr for call in calls if isinstance(call.func, ast.Attribute)
        }
        if "flush" in attributes:
            insertions.append((statement.end_lineno or statement.lineno, '    checkpoint(actor_id, "after_write")'))
            break
    if len(insertions) != 2:
        raise UploadValidationError("operation needs a recognizable database read and flush")
    output = updated.splitlines()
    for line_number, content in sorted(insertions, reverse=True):
        output.insert(line_number, content)
    instrumented = "\n".join(output) + "\n"
    ast.parse(instrumented)
    return instrumented


def _adapter_source(profile: str, package_name: str) -> str:
    if profile == "withdrawal":
        source = '''from __future__ import annotations

from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from custom_app.operations import Account, Base, Withdrawal, withdraw_funds
from raceproof.contracts import InvariantResult
from raceproof.database import actor_session
from raceproof.target import TargetAdapter


class CustomAdapter(TargetAdapter):
    def reset(self, engine):
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine, expire_on_commit=False).begin() as session:
            session.add(Account(id=1, owner="RaceProof", balance=100))

    def run_actor(self, engine, actor, checkpoint, recorder):
        checkpoint(actor.id, "before_operation")
        with actor_session(engine, actor.id) as session:
            accepted = withdraw_funds(
                session, int(actor.input["account_id"]), Decimal(str(actor.input["amount"])),
                actor.id, checkpoint,
            )
        return "accepted" if accepted else "rejected"

    def evaluate_invariant(self, engine):
        with sessionmaker(bind=engine, expire_on_commit=False)() as session:
            account = session.get(Account, 1)
            total = session.scalar(
                select(func.coalesce(func.sum(Withdrawal.amount), 0)).where(Withdrawal.account_id == 1)
            )
        balance = float(account.balance)
        withdrawals = float(total)
        passed = balance >= 0 and withdrawals <= 100
        return InvariantResult(
            name=self.config.invariant.name, passed=passed,
            assertion="account.balance >= 0 AND total_withdrawals <= initial_balance",
            evidence={"initial_balance": 100, "remaining_balance": balance, "total_withdrawals": withdrawals},
            explanation="Withdrawals stayed within the initial balance." if passed else "Concurrent withdrawals exceeded the initial balance.",
        )

    def schema_ddl(self):
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.schema import CreateTable
        return "\\n\\n".join(str(CreateTable(table).compile(dialect=postgresql.dialect())) for table in Base.metadata.sorted_tables)


def create_adapter(repository_root, config):
    return CustomAdapter(repository_root, config)
'''
        return source.replace("custom_app", package_name)
    source = '''from __future__ import annotations

import threading
from sqlalchemy.orm import sessionmaker
from custom_app.operations import Base, Product, sell_product
from raceproof.contracts import InvariantResult
from raceproof.database import actor_session
from raceproof.target import TargetAdapter


class CustomAdapter(TargetAdapter):
    def __init__(self, repository_root, config):
        super().__init__(repository_root, config)
        self._accepted = []
        self._lock = threading.Lock()

    def reset(self, engine):
        self._accepted = []
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine, expire_on_commit=False).begin() as session:
            session.add(Product(id=1, name="RaceProof item", stock=10))

    def run_actor(self, engine, actor, checkpoint, recorder):
        checkpoint(actor.id, "before_operation")
        quantity = int(actor.input["quantity"])
        with actor_session(engine, actor.id) as session:
            accepted = sell_product(session, int(actor.input["product_id"]), quantity, actor.id, checkpoint)
        if accepted:
            with self._lock:
                self._accepted.append(quantity)
        return "accepted" if accepted else "rejected"

    def evaluate_invariant(self, engine):
        with sessionmaker(bind=engine, expire_on_commit=False)() as session:
            product = session.get(Product, 1)
        stock = int(product.stock)
        accepted_quantity = sum(self._accepted)
        passed = stock >= 0 and stock == 10 - accepted_quantity
        return InvariantResult(
            name=self.config.invariant.name, passed=passed,
            assertion="product.stock >= 0 AND stock = initial_stock - accepted_quantity",
            evidence={"initial_stock": 10, "remaining_stock": stock, "accepted_quantity": accepted_quantity},
            explanation="Stock matches accepted sales." if passed else "Concurrent sales lost an update or oversold stock.",
        )

    def schema_ddl(self):
        from sqlalchemy.dialects import postgresql
        from sqlalchemy.schema import CreateTable
        return "\\n\\n".join(str(CreateTable(table).compile(dialect=postgresql.dialect())) for table in Base.metadata.sorted_tables)


def create_adapter(repository_root, config):
    return CustomAdapter(repository_root, config)
'''
    return source.replace("custom_app", package_name)


def prepare_custom_executable(custom_root: Path, target_id: str) -> dict[str, Any]:
    """Build a constrained executable target for supported standalone SQLAlchemy demos."""
    target_root = (custom_root / target_id).resolve()
    proposal_path = target_root / "proposal.json"
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    selected = proposal.get("selected_operation") or {}
    function_name = str(selected.get("function", ""))
    profile = (
        "withdrawal"
        if function_name == "withdraw_funds"
        else "inventory" if function_name == "sell_product" else None
    )
    if not profile:
        proposal.update(
            {
                "execution_ready": False,
                "execution_blocker": "This operation needs a manually reviewed RaceProof adapter before execution.",
            }
        )
        proposal_path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
        return proposal
    if proposal.get("warnings"):
        raise UploadValidationError("uploaded code with blocked imports cannot become executable")
    expected_assertion = (
        "account.balance >= 0 AND total_withdrawals <= initial_balance"
        if profile == "withdrawal"
        else "product.stock >= 0 AND stock = initial_stock - accepted_quantity"
    )
    approved_assertion = str(proposal.get("proposed_invariant", {}).get("assertion", "")).strip()
    if approved_assertion != expected_assertion:
        proposal.update(
            {
                "execution_ready": False,
                "execution_blocker": (
                    "The approved invariant does not match the supported executable invariant: "
                    + expected_assertion
                ),
            }
        )
        proposal_path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
        return proposal

    uploaded_path = target_root.joinpath(*safe_upload_path(str(selected["file"])).parts)
    source = uploaded_path.read_text(encoding="utf-8")
    instrumented = _instrument_operation(source, function_name)
    executable = target_root / "executable"
    if executable.exists():
        shutil.rmtree(executable)
    package_name = f"custom_app_{target_id.removeprefix('custom_')}"
    package = executable / "src" / package_name
    tests = executable / "tests"
    package.mkdir(parents=True)
    tests.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "operations.py").write_text(instrumented, encoding="utf-8")
    (executable / "raceproof_adapter.py").write_text(
        _adapter_source(profile, package_name), encoding="utf-8"
    )
    (tests / "test_domain.py").write_text(
        f"from {package_name}.operations import {function_name}\n\n"
        f"def test_operation_is_callable():\n    assert callable({function_name})\n",
        encoding="utf-8",
    )
    if profile == "withdrawal":
        actors = [
            {"id": "A", "input": {"account_id": 1, "amount": 80}},
            {"id": "B", "input": {"account_id": 1, "amount": 80}},
        ]
        invariant_name = "withdrawals_within_balance"
        invariant_description = "Concurrent withdrawals cannot exceed the initial account balance."
        allowed = {"accepted": 1, "rejected": 1}
    else:
        actors = [
            {"id": "A", "input": {"product_id": 1, "quantity": 7}},
            {"id": "B", "input": {"product_id": 1, "quantity": 6}},
        ]
        invariant_name = "inventory_conservation"
        invariant_description = "Remaining stock must equal initial stock minus accepted sales."
        allowed = {"accepted": 1, "rejected": 1}
    schedule = {
        "name": "custom_parallel_interleaving",
        "description": "Both actors complete the protected read before either write proceeds.",
        "actions": [
            {"kind": "wait_checkpoint", "actors": ["A", "B"], "checkpoint": "after_read"},
            {"kind": "release", "actors": ["A"], "checkpoint": "after_read"},
            {"kind": "wait_completion", "actors": ["A"]},
            {"kind": "release", "actors": ["B"], "checkpoint": "after_read"},
            {"kind": "wait_completion", "actors": ["B"]},
        ],
    }
    config = {
        "config_version": 1,
        "id": target_id,
        "name": f"Uploaded {function_name}",
        "description": f"Constrained executable analysis of uploaded operation {function_name}.",
        "repository": ".",
        "python_paths": ["src"],
        "adapter_path": "raceproof_adapter.py",
        "adapter_factory": "create_adapter",
        "database_url_env": "RACEPROOF_DATABASE_URL",
        "operation": {
            "display_name": function_name,
            "callable": f"{package_name}.operations:{function_name}",
            "source_files": [f"src/{package_name}/operations.py"],
            "editable_paths": [f"src/{package_name}/operations.py"],
            "protected_paths": ["raceproof.json", "raceproof_adapter.py", "tests"],
        },
        "actors": actors,
        "invariant": {"name": invariant_name, "description": invariant_description, "approved": True},
        "reproduction_schedule": schedule,
        "investigation_schedules": [],
        "verification_schedules": [
            schedule,
            {
                "name": "adapted_parallel_start",
                "description": "Run both complete operations concurrently after repair.",
                "actions": [
                    {"kind": "wait_checkpoint", "actors": ["A", "B"], "checkpoint": "before_operation"},
                    {"kind": "release_all", "actors": ["A", "B"]},
                    {"kind": "wait_completion", "actors": ["A", "B"]},
                ],
            },
        ],
        "verification": {
            "allowed_outcomes": allowed,
            "regression": {"argv": ["python", "-m", "pytest", "-q", "tests"], "cwd": ".", "timeout_seconds": 60},
            "replay_count": 3,
            "benchmark_runs": 5,
            "performance_regression_limit": 2.5,
        },
        "limitations": ["Executable auto-adaptation is limited to the recognized SQLAlchemy demo profile."],
    }
    (executable / "raceproof.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    proposal.update(
        {
            "execution_ready": True,
            "executable_config": "executable/raceproof.json",
            "execution_blocker": "",
            "actors": actors,
        }
    )
    proposal_path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
    return proposal


def analyze_approved_custom_target(custom_root: Path, target_id: str) -> dict[str, Any]:
    """Review every uploaded source file against an approved invariant without execution."""
    if re.fullmatch(r"custom_[0-9a-f]{12}", target_id) is None:
        raise UploadValidationError("invalid custom target id")
    target_root = (custom_root / target_id).resolve()
    proposal_path = (target_root / "proposal.json").resolve()
    if not target_root.is_relative_to(custom_root.resolve()) or not proposal_path.is_file():
        raise UploadValidationError("custom target proposal not found")
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    if proposal.get("status") not in {
        "PENDING_CONTRACT_APPROVAL",
        "CONTRACT_APPROVED_ANALYSIS_ONLY",
        "CUSTOM_ANALYSIS_COMPLETE",
    }:
        raise UploadValidationError("custom target is not ready for static analysis")

    approved_invariant = proposal.get("proposed_invariant", {})
    assertion = str(approved_invariant.get("assertion", "")).strip()
    invariant_is_approved = bool(
        approved_invariant.get("approved")
        and assertion
        and assertion != INVARIANT_PLACEHOLDER
        and not assertion.lower().startswith("human must replace")
    )
    if approved_invariant.get("approved") and not invariant_is_approved:
        approved_invariant["approved"] = False
        approved_invariant["assertion"] = ""
        proposal["proposed_invariant"] = approved_invariant
        proposal["status"] = "PENDING_CONTRACT_APPROVAL"
    invariant = (
        approved_invariant
        if invariant_is_approved
        else {
            "name": "per_operation_suggestions",
            "description": "Each finding includes an inferred invariant suggestion for human review.",
            "assertion": "Review the suggested invariant attached to each finding.",
            "approved": False,
        }
    )
    operation_findings: list[dict[str, Any]] = []
    for candidate in proposal.get("operation_candidates", []):
        check_then_act = candidate.get("risk") == "check_then_act"
        operation_findings.append(
            {
                **candidate,
                "severity": "high" if check_then_act else "review",
                "invariant_assertion": (
                    invariant["assertion"]
                    if invariant_is_approved
                    else candidate["suggested_invariant"]["assertion"]
                ),
                "invariant_source": "human_approved" if invariant_is_approved else "suggested",
                "assessment": (
                    "This read-then-write operation can violate the review invariant when two "
                    "actors observe the same pre-write state."
                    if check_then_act
                    else "This database operation participates in shared state and needs an "
                    "application adapter before the invariant can be executed."
                ),
                "recommended_control": (
                    "Use an atomic conditional write, a database constraint, or locking scoped to "
                    "the protected resource, then verify the invariant on PostgreSQL."
                ),
            }
        )

    file_results: list[dict[str, Any]] = []
    candidates_by_file: dict[str, list[dict[str, Any]]] = {}
    for finding in operation_findings:
        candidates_by_file.setdefault(str(finding["file"]), []).append(finding)
    for raw_path in proposal.get("files", []):
        path = safe_upload_path(raw_path)
        source_path = target_root.joinpath(*path.parts).resolve()
        if not source_path.is_relative_to(target_root) or not source_path.is_file():
            raise UploadValidationError(f"uploaded source is missing: {raw_path}")
        if path.suffix.lower() == ".sql":
            sql = source_path.read_text(encoding="utf-8", errors="replace")
            statements = {
                keyword: len(re.findall(rf"\b{keyword}\b", sql, flags=re.IGNORECASE))
                for keyword in ("select", "insert", "update", "delete")
            }
            file_results.append(
                {
                    "file": raw_path,
                    "kind": "sql",
                    "database_operations": sum(statements.values()),
                    "statements": statements,
                    "uses_for_update": bool(re.search(r"\bFOR\s+UPDATE\b", sql, re.IGNORECASE)),
                    "finding_count": 0,
                }
            )
        else:
            findings = candidates_by_file.get(raw_path, [])
            file_results.append(
                {
                    "file": raw_path,
                    "kind": "python",
                    "finding_count": len(findings),
                    "operations": [finding["entrypoint"] for finding in findings],
                }
            )

    result = {
        "target_id": target_id,
        "status": "CUSTOM_ANALYSIS_COMPLETE" if invariant_is_approved else "STATIC_ANALYSIS_COMPLETE",
        "analysis_mode": "STATIC_INVARIANT_REVIEW",
        "execution_performed": False,
        "invariant": invariant,
        "files_scanned": len(file_results),
        "operations_reviewed": len(operation_findings),
        "high_risk_operations": sum(
            finding["severity"] == "high" for finding in operation_findings
        ),
        "file_results": file_results,
        "findings": operation_findings,
        "limitations": [
            "Uploaded code was not imported or executed.",
            (
                "The human-approved invariant was used as the review contract but was not executable."
                if invariant_is_approved
                else "Each finding uses a suggested invariant only. Human approval is required before any future executable run."
            ),
            "No PostgreSQL reproduction or verified repair is claimed without an application adapter.",
        ],
    }
    (target_root / "analysis.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if invariant_is_approved:
        proposal["status"] = "CUSTOM_ANALYSIS_COMPLETE"
    proposal_path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
    return result
