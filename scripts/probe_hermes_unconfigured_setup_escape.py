#!/usr/bin/env python3
"""Capture bounded /setup and /model behavior during Hermes startup."""

from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_setup_config_shape import config_shape, file_inventory
from probe_hermes_slash_commands import (
    COLUMNS,
    DEFAULT_REFERENCE,
    ROWS,
    SOURCE_COMMIT,
    ProbeFailure,
    contains_marker,
    safe_environment,
    safe_tail,
)
from probe_hermes_terminal_palette import (
    child_status,
    normalized,
    read_available,
    set_window_size,
    stop,
    write_bytes,
)
from probe_hermes_unconfigured_startup import artifact_classes, stable_surface, surface_state
from probe_tui_lifecycle import retain_slave_descriptor, slave_path_for_pid, terminal_flags


COMMANDS = ("/setup", "/model")
OBSERVATION_WINDOW_SECONDS = 3.0


def drain_window(fd: int, buffer: bytes, duration: float) -> bytes:
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        readable, _, _ = select.select(
            [fd], [], [], max(0.0, min(0.05, deadline - time.monotonic()))
        )
        if readable:
            buffer += read_available(fd)
    return buffer + read_available(fd)


def spawn_unconfigured(reference: Path, home: Path) -> tuple[int, int, str]:
    environment = safe_environment(reference, home)
    for key in (
        "HADES_PROVIDER_BASE_URL",
        "HADES_PROVIDER_API_KEY",
        "HADES_MODEL",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
    ):
        environment.pop(key, None)

    pid, fd = os.forkpty()
    if pid == 0:
        os.chdir(reference)
        os.execvpe("uv", ["uv", "run", "hermes", "--tui"], environment)
    set_window_size(fd, COLUMNS, ROWS)
    os.set_blocking(fd, False)
    slave_path = slave_path_for_pid(pid)
    retain_slave_descriptor(slave_path)
    return pid, fd, slave_path


def status_value(status: int | None) -> dict[str, int | str]:
    if status is None:
        return {"kind": "unknown"}
    if os.WIFEXITED(status):
        return {"kind": "exit", "code": os.WEXITSTATUS(status)}
    if os.WIFSIGNALED(status):
        return {"kind": "signal", "number": os.WTERMSIG(status)}
    return {"kind": "other", "raw": status}


def visible_outcome(raw: bytes, command: str) -> dict[str, Any]:
    text = normalized(raw)
    state = surface_state(raw)
    markers = (
        "Hermes Agent Setup Wizard",
        "How would you like to set up Hermes?",
        "Select provider",
        "Select model",
        "starting agent",
        "─ ready │",
        "Provider error",
    )
    return {
        "command_visible": contains_marker(raw, command),
        "composer_marker_visible": contains_marker(raw, f"❯ {command}"),
        "state": state,
        "markers": {marker: marker in text for marker in markers},
        "provider_request_or_error_visible": "Provider error" in text,
    }


def cleanup(
    pid: int, fd: int, buffer: bytes, case: str, timeout: float
) -> tuple[bytes, dict[str, Any]]:
    presses = 0
    exit_status: int | None = None
    press_window = min(0.75, max(0.25, timeout / 4))
    while presses < 3:
        exited, status = child_status(pid)
        if exited:
            exit_status = status
            break
        write_bytes(fd, b"\x03")
        presses += 1
        buffer = drain_window(fd, buffer, press_window)
        exited, status = child_status(pid)
        if exited:
            exit_status = status
            break
    if exit_status is None:
        stop(pid, fd)
        raise ProbeFailure(
            case,
            "cleanup",
            f"Hermes did not exit after {presses} Ctrl+C presses",
            {"screen_tail": safe_tail(buffer)},
        )
    return buffer, {
        "ctrl_c_presses": presses,
        "exit": status_value(exit_status),
        "alternate_screen_entered": b"\x1b[?1049h" in buffer,
        "alternate_screen_left": b"\x1b[?1049l" in buffer,
    }


def run_case(reference: Path, command: str, timeout: float) -> dict[str, Any]:
    case = f"unconfigured-{command.removeprefix('/')}"
    root = Path(tempfile.mkdtemp(prefix=f"hades-hermes-{case}-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        files_before = file_inventory(home)
        pid, fd, slave_path = spawn_unconfigured(reference, home)
        buffer, startup, stable_samples, startup_ms = stable_surface(
            pid, fd, buffer, case, timeout
        )
        startup_flags = terminal_flags(slave_path)
        if startup_flags["canonical"] or startup_flags["echo"]:
            raise ProbeFailure(case, "startup", "Hermes did not enter raw mode")

        files_at_start = file_inventory(home)
        config_at_start = config_shape(home / "config.yaml")
        write_bytes(fd, f"{command}\r".encode())
        deadline = time.monotonic() + OBSERVATION_WINDOW_SECONDS
        while time.monotonic() < deadline:
            buffer = drain_window(fd, buffer, 0.1)
        outcome = visible_outcome(buffer, command)
        files_after_input = file_inventory(home)
        config_after_input = config_shape(home / "config.yaml")
        buffer, cleanup_result = cleanup(pid, fd, buffer, case, timeout)
        cleanup_flags = terminal_flags(slave_path)
        if cleanup_result["exit"] != {"kind": "exit", "code": 0}:
            raise ProbeFailure(case, "cleanup", f"unexpected exit: {cleanup_result['exit']}")
        if not cleanup_result["alternate_screen_entered"] or not cleanup_result["alternate_screen_left"]:
            raise ProbeFailure(case, "cleanup", "alternate-screen cleanup was incomplete")
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeFailure(case, "cleanup", f"terminal was not restored: {cleanup_flags}")
        return {
            "id": case,
            "status": "passed",
            "input": {
                "command": command,
                "enter_sent": True,
                "observation_window_seconds": OBSERVATION_WINDOW_SECONDS,
            },
            "startup": {
                "surface": startup,
                "stable_samples": stable_samples,
                "time_to_first_stable_ms": startup_ms,
                "raw_mode": startup_flags,
            },
            "outcome": outcome,
            "cleanup": {**cleanup_result, "terminal_flags": cleanup_flags},
            "config_at_start": config_at_start,
            "config_after_input": config_after_input,
            "config_changed_during_input": config_at_start != config_after_input,
            "artifact_classes_at_start": artifact_classes(files_at_start - files_before),
            "artifact_classes_during_input": artifact_classes(files_after_input - files_at_start),
        }
    except ProbeFailure:
        raise
    finally:
        if pid != -1 and not child_status(pid)[0]:
            stop(pid, fd)
        elif fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
        shutil.rmtree(root, ignore_errors=True)


def safe_failure(error: BaseException) -> dict[str, Any] | str:
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
        "observation_id": "OBS-0063",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY"},
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, provider endpoints, credentials, session identifiers, timestamps, and raw redraw bytes are omitted or replaced by placeholders.",
            "Both cases start with no config and no Hades/OpenAI provider environment; only /setup or /model plus Enter is sent, with no credentials, OAuth, external network, or later setup/model value entered.",
            "The bounded report records visible command/setup/model markers, normalized config/artifact changes, cleanup, and terminal restoration without inferring eventual startup or queue delivery.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"] = [run_case(reference, command, args.timeout) for command in COMMANDS]
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        report["failure"] = safe_failure(error)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized, encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
