#!/usr/bin/env python3
"""Capture the safe first-run boundary of Hermes' standalone setup command."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_slash_commands import (
    COLUMNS,
    DEFAULT_REFERENCE,
    ROWS,
    SOURCE_COMMIT,
    ProbeFailure,
    safe_environment,
    safe_tail,
)
from probe_hermes_terminal_palette import (
    child_status,
    contains_marker,
    drain,
    read_available,
    set_window_size,
    stop,
    write_bytes,
)
from probe_tui_lifecycle import describe_status, terminal_flags


INITIAL_MARKERS = (
    "Hermes Agent Setup Wizard",
    "Let's configure your Hermes Agent installation.",
    "Press Ctrl+C at any time to exit.",
    "How would you like to set up Hermes?",
    "Quick Setup (Nous Portal)",
    "Full setup",
    "Blank Slate",
    "ESC cancel",
)
FALLBACK_MARKERS = (
    "How would you like to set up Hermes?",
    "Quick Setup (Nous Portal)",
    "Full setup",
    "Blank Slate",
    "Enter for default (1)",
    "Ctrl+C to exit",
    "Select [1-3] (1):",
)


def emit_report(report: dict[str, Any], path: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")


def file_inventory(home: Path) -> set[str]:
    return {str(path.relative_to(home)) for path in home.rglob("*") if path.is_file()}


def file_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "bytes": 0}
    return {"exists": True, "bytes": path.stat().st_size}


def artifact_classes(new_files: set[str]) -> list[str]:
    classes: set[str] = set()
    for name in new_files:
        if name == ".hermes_history":
            classes.add(".hermes_history")
        elif name.startswith("config.yaml.bak."):
            classes.add("config.yaml.bak.<timestamp>")
        elif name == "config.yaml":
            classes.add("config.yaml")
        else:
            classes.add("<other-file>")
    return sorted(classes)


def spawn_setup(reference: Path, home: Path) -> tuple[int, int, str]:
    import os
    import pty

    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(reference)
        environment = safe_environment(reference, home)
        os.execvpe("uv", ["uv", "run", "hermes", "setup"], environment)
    set_window_size(fd, COLUMNS, ROWS)
    os.set_blocking(fd, False)
    return pid, fd, os.readlink(f"/proc/{pid}/fd/0")


def wait_for_markers(
    pid: int,
    fd: int,
    buffer: bytes,
    case: str,
    step: str,
    markers: tuple[str, ...],
    timeout: float,
) -> bytes:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(contains_marker(buffer, marker) for marker in markers):
            return buffer
        exited, status = child_status(pid)
        if exited:
            buffer += read_available(fd)
            if all(contains_marker(buffer, marker) for marker in markers):
                return buffer
            raise ProbeFailure(
                case,
                step,
                "Hermes exited before the PTY assertion",
                {"exit_status": status, "screen_tail": safe_tail(buffer)},
            )
        buffer = drain(pid, fd, buffer, 0.05)
    raise ProbeFailure(
        case,
        step,
        f"timed out after {timeout:.1f}s",
        {"screen_tail": safe_tail(buffer)},
    )


def wait_for_exit(pid: int, fd: int, buffer: bytes, case: str, timeout: float) -> tuple[bytes, dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        exited, status = child_status(pid)
        if exited:
            buffer += read_available(fd)
            return buffer, describe_status(status) if status is not None else {"kind": "reaped"}
        buffer += read_available(fd)
        time.sleep(0.05)
    raise ProbeFailure(case, "cleanup", f"timed out after {timeout:.1f}s", {"screen_tail": safe_tail(buffer)})


def run_case(reference: Path, case: str, timeout: float) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix=f"hades-hermes-{case}-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        pid, fd, slave_path = spawn_setup(reference, home)
        files_before = file_inventory(home)
        config_before = file_state(home / "config.yaml")
        buffer = wait_for_markers(pid, fd, buffer, case, "initial-surface", INITIAL_MARKERS, timeout)
        startup_flags = terminal_flags(slave_path)
        initial_tail = safe_tail(buffer)

        write_bytes(fd, b"\x1b")
        buffer = wait_for_markers(
            pid,
            fd,
            buffer,
            case,
            "fallback-surface",
            FALLBACK_MARKERS,
            timeout,
        )
        fallback_flags = terminal_flags(slave_path)
        fallback_tail = safe_tail(buffer)

        write_bytes(fd, b"\x03")
        buffer, exit_status = wait_for_exit(pid, fd, buffer, case, timeout)
        cleanup_flags = terminal_flags(slave_path)
        files_after = file_inventory(home)
        config_after = file_state(home / "config.yaml")
        if exit_status != {"kind": "exit", "code": 1}:
            raise ProbeFailure(
                case,
                "cleanup",
                f"unexpected cancellation exit status: {exit_status}",
                {"screen_tail": safe_tail(buffer)},
            )
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeFailure(
                case,
                "cleanup",
                f"terminal was not restored: {cleanup_flags}",
                {"screen_tail": safe_tail(buffer)},
            )

        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "key", "value": "Escape"},
                {"kind": "key", "value": "Ctrl+C"},
            ],
            "initial_surface": {
                "markers": list(INITIAL_MARKERS),
                "screen_tail": initial_tail,
                "terminal_flags": startup_flags,
            },
            "fallback_surface": {
                "markers": list(FALLBACK_MARKERS),
                "screen_tail": fallback_tail,
                "terminal_flags": fallback_flags,
            },
            "config_before": config_before,
            "config_after": config_after,
            "config_changed": config_before != config_after,
            "artifact_classes": artifact_classes(files_after - files_before),
            "exit": exit_status,
            "cleanup": {
                "terminal_flags": cleanup_flags,
                "alternate_screen_entered": b"\x1b[?1049h" in buffer,
                "alternate_screen_left": b"\x1b[?1049l" in buffer,
            },
        }
    finally:
        if pid != -1:
            stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def safe_failure(error: BaseException) -> Any:
    if not isinstance(error, ProbeFailure):
        return str(error)
    details = dict(error.details)
    if "screen_tail" in details:
        details["screen_tail"] = safe_tail(str(details["screen_tail"]).encode())
    return {"case": error.case, "step": error.step, "message": error.message, **details}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0069",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY with normalized stable markers"},
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, PTY paths, credentials, timestamps, and raw redraw bytes are omitted or replaced by stable markers.",
            "Each case starts with a fresh synthetic home and no config, provider endpoint, credentials, OAuth action, external network, or platform selection.",
            "Screen tails are retained only as redacted diagnostics; the contract is limited to the named stable setup surfaces and cleanup state.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"].append(run_case(reference, "standalone-setup-escape-fallback", args.timeout))
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        report["failure"] = safe_failure(error)
    emit_report(report, args.report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
