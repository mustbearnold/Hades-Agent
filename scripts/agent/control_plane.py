#!/usr/bin/env python3
"""Validate and mutate the small, checked-in Hades development control plane."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
TASKS_PATH = ROOT / ".hades" / "tasks.json"
CONFIG_PATH = ROOT / ".hades" / "config.toml"
LOCK_PATH = ROOT / ".hades" / "locks" / "tasks.lock"

REQUIRED_FILES = (
    "AGENTS.md",
    "README.md",
    "SECURITY.md",
    "Cargo.toml",
    "rust-toolchain.toml",
    "specs/constitution.md",
    "specs/conventions.md",
    "specs/001-parity-contract/spec.md",
    "specs/001-parity-contract/matrix.md",
    "docs/runbooks/agent-contracts.md",
    ".hades/protocol/task.schema.json",
)

STATUSES = {"queued", "ready", "in_progress", "blocked", "complete", "cancelled"}
RISKS = {"low", "medium", "high"}


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"missing control-plane file: {path.relative_to(ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected an object in {path.relative_to(ROOT)}")
    return value


def validate(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append(".hades/tasks.json must use schema_version 1")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        errors.append(".hades/tasks.json must contain a non-empty tasks array")
        return errors

    by_id: dict[str, dict[str, Any]] = {}
    for index, task in enumerate(tasks):
        prefix = f"task[{index}]"
        if not isinstance(task, dict):
            errors.append(f"{prefix} must be an object")
            continue
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id.startswith("HAD-"):
            errors.append(f"{prefix} has an invalid id")
        elif task_id in by_id:
            errors.append(f"duplicate task id: {task_id}")
        else:
            by_id[task_id] = task

        if not isinstance(task.get("title"), str) or not task["title"].strip():
            errors.append(f"{prefix} needs a non-empty title")
        if not isinstance(task.get("priority"), int) or task["priority"] < 0:
            errors.append(f"{prefix} needs a non-negative integer priority")
        if task.get("status") not in STATUSES:
            errors.append(f"{prefix} has an invalid status")
        if task.get("risk") not in RISKS:
            errors.append(f"{prefix} has an invalid risk")
        for field in ("depends_on", "oracle", "acceptance", "evidence"):
            value = task.get(field)
            if not isinstance(value, list):
                errors.append(f"{prefix}.{field} must be an array")
            elif field in {"oracle", "acceptance"} and not value:
                errors.append(f"{prefix}.{field} must not be empty")
            elif not all(isinstance(item, str) and item.strip() for item in value):
                errors.append(f"{prefix}.{field} must contain non-empty strings")

        if task.get("status") == "in_progress":
            if not isinstance(task.get("claimed_by"), str) or not task["claimed_by"].strip():
                errors.append(f"{task_id or prefix} in_progress task needs claimed_by")
            if not isinstance(task.get("claimed_at"), str) or not task["claimed_at"].strip():
                errors.append(f"{task_id or prefix} in_progress task needs claimed_at")

        if task.get("status") == "complete":
            evidence = task.get("evidence", [])
            if not evidence:
                errors.append(f"{task_id or prefix} complete task needs evidence")
            for evidence_path in evidence:
                if isinstance(evidence_path, str):
                    errors.extend(validate_evidence_path(task_id or prefix, evidence_path))
            result = task.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("summary"), str):
                errors.append(f"{task_id or prefix} complete task needs a result summary")
            elif not result["summary"].strip():
                errors.append(f"{task_id or prefix} complete task needs a non-empty result summary")
            if isinstance(result, dict) and result.get("evidence") != evidence:
                errors.append(f"{task_id or prefix} result evidence must match task evidence")

    for task_id, task in by_id.items():
        dependencies = task.get("depends_on", [])
        if not isinstance(dependencies, list):
            continue
        for dependency in dependencies:
            if dependency == task_id:
                errors.append(f"{task_id} cannot depend on itself")
            elif dependency not in by_id:
                errors.append(f"{task_id} depends on unknown task {dependency}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            errors.append(f"task dependency cycle includes {task_id}")
            return
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in by_id[task_id].get("depends_on", []):
            if dependency in by_id:
                visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in by_id:
        visit(task_id)

    for required_file in REQUIRED_FILES:
        path = ROOT / required_file
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"missing or empty required file: {required_file}")

    try:
        import tomllib

        with CONFIG_PATH.open("rb") as handle:
            config = tomllib.load(handle)
        if config.get("schema_version") != 1:
            errors.append(".hades/config.toml must use schema_version 1")
        if not config.get("required_gates"):
            errors.append(".hades/config.toml must declare required_gates")
    except (FileNotFoundError, tomllib.TOMLDecodeError) as exc:
        errors.append(f"invalid .hades/config.toml: {exc}")

    return errors


def validate_evidence_path(task_id: str, value: str) -> list[str]:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return [f"{task_id} evidence path must stay relative to the repository: {value}"]
    if not (ROOT / path).exists():
        return [f"{task_id} evidence path does not exist: {value}"]
    return []


def read_validated() -> dict[str, Any]:
    data = load_json(TASKS_PATH)
    errors = validate(data)
    if errors:
        raise ValueError("\n".join(errors))
    return data


def write_locked(mutator: Callable[[dict[str, Any]], Any]) -> Any:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        data = read_validated()
        result = mutator(data)
        promote_unblocked(data)
        data["updated_at"] = now()
        temporary = TASKS_PATH.with_name(f".{TASKS_PATH.name}.{os.getpid()}.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, TASKS_PATH)
        return result


def task_map(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {task["id"]: task for task in data["tasks"]}


def promote_unblocked(data: dict[str, Any]) -> None:
    """Make queued tasks ready as soon as every declared dependency completes."""
    by_id = task_map(data)
    for task in data["tasks"]:
        if task["status"] == "queued" and all(
            by_id[dependency]["status"] == "complete" for dependency in task["depends_on"]
        ):
            task["status"] = "ready"
            task["ready_at"] = now()


def eligible_tasks(data: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = task_map(data)
    return sorted(
        (
            task
            for task in data["tasks"]
            if task["status"] == "ready"
            and all(by_id[dependency]["status"] == "complete" for dependency in task["depends_on"])
        ),
        key=lambda task: (-task["priority"], task["id"]),
    )


def command_validate(_: argparse.Namespace) -> int:
    data = load_json(TASKS_PATH)
    errors = validate(data)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"valid": True, "task_count": len(data["tasks"])}, sort_keys=True))
    return 0


def command_next(_: argparse.Namespace) -> int:
    data = read_validated()
    eligible = eligible_tasks(data)
    if not eligible:
        print(json.dumps({"task": None, "reason": "no unblocked ready task"}, sort_keys=True))
    else:
        print(json.dumps({"task": eligible[0]}, indent=2, sort_keys=True))
    return 0


def find_task(data: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in data["tasks"]:
        if task["id"] == task_id:
            return task
    raise ValueError(f"unknown task: {task_id}")


def command_show(args: argparse.Namespace) -> int:
    data = read_validated()
    print(json.dumps(find_task(data, args.task_id), indent=2, sort_keys=True))
    return 0


def command_claim(args: argparse.Namespace) -> int:
    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        task = find_task(data, args.task_id)
        by_id = task_map(data)
        if task["status"] != "ready":
            raise ValueError(f"{args.task_id} is {task['status']}, not ready")
        blocked_by = [
            dependency
            for dependency in task["depends_on"]
            if by_id[dependency]["status"] != "complete"
        ]
        if blocked_by:
            raise ValueError(f"{args.task_id} is blocked by: {', '.join(blocked_by)}")
        task["status"] = "in_progress"
        task["claimed_by"] = args.agent
        task["claimed_at"] = now()
        task["attempts"] = int(task.get("attempts", 0)) + 1
        return task

    task = write_locked(mutate)
    print(json.dumps({"claimed": task}, indent=2, sort_keys=True))
    return 0


def command_complete(args: argparse.Namespace) -> int:
    evidence = list(dict.fromkeys(args.evidence))
    path_errors = [error for path in evidence for error in validate_evidence_path(args.task_id, path)]
    if path_errors:
        raise ValueError("\n".join(path_errors))

    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        task = find_task(data, args.task_id)
        if task["status"] != "in_progress":
            raise ValueError(f"{args.task_id} is {task['status']}; claim it before completing")
        task["status"] = "complete"
        task["evidence"] = evidence
        task["result"] = {"summary": args.summary, "completed_at": now(), "evidence": evidence}
        return task

    task = write_locked(mutate)
    print(json.dumps({"completed": task}, indent=2, sort_keys=True))
    return 0


def command_block(args: argparse.Namespace) -> int:
    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        task = find_task(data, args.task_id)
        if task["status"] not in {"in_progress", "ready"}:
            raise ValueError(f"{args.task_id} is {task['status']}; only active work can be blocked")
        task["status"] = "blocked"
        task["result"] = {"reason": args.reason, "blocked_at": now()}
        if args.next_action:
            task["result"]["next_action"] = args.next_action
        return task

    task = write_locked(mutate)
    print(json.dumps({"blocked": task}, indent=2, sort_keys=True))
    return 0


def command_cancel(args: argparse.Namespace) -> int:
    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        task = find_task(data, args.task_id)
        if task["status"] not in {"in_progress", "ready", "queued"}:
            raise ValueError(f"{args.task_id} is {task['status']}; only unfinished work can be cancelled")
        task["status"] = "cancelled"
        task["result"] = {"reason": args.reason, "cancelled_at": now()}
        return task

    task = write_locked(mutate)
    print(json.dumps({"cancelled": task}, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate", help="validate the checked-in control plane").set_defaults(
        handler=command_validate
    )
    subparsers.add_parser("next", help="select the highest-priority eligible task").set_defaults(
        handler=command_next
    )

    show = subparsers.add_parser("show", help="show one task")
    show.add_argument("task_id")
    show.set_defaults(handler=command_show)

    claim = subparsers.add_parser("claim", help="claim one ready task")
    claim.add_argument("task_id")
    claim.add_argument("agent")
    claim.set_defaults(handler=command_claim)

    complete = subparsers.add_parser("complete", help="complete a claimed task with evidence")
    complete.add_argument("task_id")
    complete.add_argument("--summary", required=True)
    complete.add_argument("--evidence", action="append", required=True)
    complete.set_defaults(handler=command_complete)

    block = subparsers.add_parser("block", help="mark active work blocked")
    block.add_argument("task_id")
    block.add_argument("--reason", required=True)
    block.add_argument("--next-action")
    block.set_defaults(handler=command_block)

    cancel = subparsers.add_parser("cancel", help="mark unfinished work cancelled")
    cancel.add_argument("task_id")
    cancel.add_argument("--reason", required=True)
    cancel.set_defaults(handler=command_cancel)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
