#!/usr/bin/env python3
"""Capture Hermes input behavior while a fresh session is starting."""

from __future__ import annotations

import argparse
import json
import os
import pty
import re
import select
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_full_setup import rendered_lines
from probe_hermes_setup_config_shape import config_shape, file_inventory
from probe_hermes_slash_commands import (
    COLUMNS,
    DEFAULT_REFERENCE,
    ROWS,
    SOURCE_COMMIT,
    ProbeFailure,
    contains_marker,
    safe_environment,
)
from probe_hermes_terminal_palette import (
    child_status,
    normalized,
    read_available,
    set_window_size,
    stop,
    wait_for,
    write_bytes,
)
from probe_hermes_unconfigured_startup import artifact_classes, stable_surface, surface_state
from probe_tui_lifecycle import retain_slave_descriptor, slave_path_for_pid, terminal_flags


INPUT_TEXT = "queued hello"
INPUT_WINDOW_SECONDS = 3.0
SOURCE_PHASE = "starting agent"
PRIVATE_TAIL = re.compile(r"(?:/tmp|/home)/[^\s\r\n]+|Session:\s+\S+", re.IGNORECASE)


def redacted_tail(raw: bytes) -> str:
    text = normalized(raw)[-2400:]
    return PRIVATE_TAIL.sub("<redacted>", text)


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

    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(reference)
        os.execvpe("uv", ["uv", "run", "hermes", "--tui"], environment)
    set_window_size(fd, COLUMNS, ROWS)
    os.set_blocking(fd, False)
    slave_path = slave_path_for_pid(pid)
    retain_slave_descriptor(slave_path)
    return pid, fd, slave_path


def draft_visible(raw: bytes) -> bool:
    return any(INPUT_TEXT in line and "❯" in line for line in rendered_lines(raw))


def final_state(raw: bytes) -> dict[str, Any] | None:
    return surface_state(raw)


def drain_window(pid: int, fd: int, buffer: bytes, duration: float) -> bytes:
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        readable, _, _ = select.select([fd], [], [], min(0.05, deadline - time.monotonic()))
        if readable:
            buffer += read_available(fd)
    return buffer + read_available(fd)


def status_value(status: int | None) -> dict[str, int | str]:
    if status is None:
        return {"kind": "unknown"}
    if os.WIFEXITED(status):
        return {"kind": "exit", "code": os.WEXITSTATUS(status)}
    if os.WIFSIGNALED(status):
        return {"kind": "signal", "number": os.WTERMSIG(status)}
    return {"kind": "other", "raw": status}


def finish_with_ctrl_c(
    pid: int, fd: int, buffer: bytes, case: str, timeout: float
) -> tuple[bytes, dict[str, Any]]:
    press_window = min(0.75, max(0.25, timeout / 4))
    exit_status: int | None = None
    write_bytes(fd, b"\x03")
    buffer = drain_window(pid, fd, buffer, press_window)
    first_exited, first_status = child_status(pid)
    if first_exited:
        exit_status = first_status
    first_interrupt = {
        "exited": first_exited,
        "status": final_state(buffer),
        "draft_visible": draft_visible(buffer),
    }
    interrupt_count = 1
    while exit_status is None and interrupt_count < 3:
        write_bytes(fd, b"\x03")
        interrupt_count += 1
        buffer = drain_window(pid, fd, buffer, press_window)
        exited, status = child_status(pid)
        if exited:
            exit_status = status
    if exit_status is None:
        stop(pid, fd)
        raise ProbeFailure(case, "cleanup", f"Hermes did not exit after {interrupt_count} Ctrl+C presses")
    return buffer, {
        "ctrl_c_presses": interrupt_count,
        "first_interrupt": first_interrupt,
        "exit": status_value(exit_status),
        "alternate_screen_entered": b"\x1b[?1049h" in buffer,
        "alternate_screen_left": b"\x1b[?1049l" in buffer,
    }


def run_case(reference: Path, timing: str, timeout: float) -> dict[str, Any]:
    case = f"unconfigured-input-{timing}"
    root = Path(tempfile.mkdtemp(prefix=f"hades-hermes-{case}-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        files_before = file_inventory(home)
        pid, fd, slave_path = spawn_unconfigured(reference, home)
        if timing == "after-starting-marker":
            buffer = wait_for(
                pid,
                fd,
                buffer,
                case,
                "starting-surface",
                lambda raw: contains_marker(raw, "Hermes Agent")
                and contains_marker(raw, SOURCE_PHASE),
                timeout,
            )
        else:
            buffer, _, _, _ = stable_surface(pid, fd, buffer, case, timeout)

        startup_flags = terminal_flags(slave_path)
        first_files = file_inventory(home)
        first_config = config_shape(home / "config.yaml")
        write_bytes(fd, f"{INPUT_TEXT}\r".encode())
        buffer = drain_window(pid, fd, buffer, INPUT_WINDOW_SECONDS)
        state_after_input = final_state(buffer)
        input_result = {
            "text": INPUT_TEXT,
            "enter_sent": True,
            "draft_visible": draft_visible(buffer),
            "status_after_input": state_after_input["status"] if state_after_input else "unknown",
            "ready_footer_seen": contains_marker(buffer, "─ ready │"),
            "provider_error_seen": contains_marker(buffer, "No LLM provider")
            or contains_marker(buffer, "Provider error"),
            "assistant_output_seen": contains_marker(buffer, "assistant"),
        }
        buffer, cleanup = finish_with_ctrl_c(pid, fd, buffer, case, timeout)
        cleanup_flags = terminal_flags(slave_path)
        files_after = file_inventory(home)
        after_config = config_shape(home / "config.yaml")
        if cleanup["exit"] != {"kind": "exit", "code": 0}:
            raise ProbeFailure(case, "cleanup", f"unexpected exit status: {cleanup['exit']}")
        if not cleanup["alternate_screen_entered"] or not cleanup["alternate_screen_left"]:
            raise ProbeFailure(case, "cleanup", "alternate-screen cleanup was incomplete")
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeFailure(case, "cleanup", f"terminal was not restored: {cleanup_flags}")
        return {
            "id": case,
            "status": "passed",
            "timing": timing,
            "startup": {
                "status": SOURCE_PHASE,
                "model_provider": "glm-5.2 · Nous Research",
                "raw_mode": startup_flags,
            },
            "input_result": input_result,
            "cleanup": {**cleanup, "terminal_flags": cleanup_flags},
            "config_at_start": first_config,
            "config_after_cleanup": after_config,
            "config_changed": first_config != after_config,
            "artifact_classes_at_start": artifact_classes(first_files - files_before),
            "artifact_classes_during_cleanup": artifact_classes(files_after - first_files),
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
        details["screen_tail"] = redacted_tail(str(details["screen_tail"]).encode())
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
        "observation_id": "OBS-0061",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY"},
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, provider endpoints, credentials, session identifiers, timestamps, and raw redraw bytes are omitted or replaced by placeholders.",
            "Both cases start with no config and no Hades/OpenAI provider environment; input is the sanitized text queued hello followed by Enter, with no setup, credentials, OAuth, external provider, or model response exercised.",
            "The report records only stable startup/input/cleanup markers, normalized config shape, and artifact classes; it does not claim that the visible draft was sent to a model.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"] = [
            run_case(reference, "after-starting-marker", args.timeout),
            run_case(reference, "after-stable-surface", args.timeout),
        ]
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
