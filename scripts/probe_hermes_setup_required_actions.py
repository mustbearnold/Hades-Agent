#!/usr/bin/env python3
"""Capture Hermes follow-up input semantics after delayed Setup Required."""

from __future__ import annotations

import argparse
import json
import os
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
    safe_tail,
)
from probe_hermes_terminal_palette import (
    child_status,
    contains_marker,
    Screen,
    write_bytes,
)
from probe_hermes_unconfigured_resolution import cleanup, drain_window, spawn_unconfigured
from probe_hermes_unconfigured_startup import artifact_classes, stable_surface
from probe_tui_lifecycle import terminal_flags


OBSERVATION_WINDOW_SECONDS = 3.0
SETUP_REQUIRED_TIMEOUT_SECONDS = 12.0
FOLLOW_UP_COMMANDS = ("/model", "/setup")
SURFACE_MARKERS = (
    "Setup Required",
    "/model",
    "/setup",
    "Ctrl+C",
    "Select provider",
    "Select model",
    "Hermes Agent Setup Wizard",
    "starting agent",
    "─ ready │",
    "Provider error",
)


def marker_flags(raw: bytes | str) -> dict[str, bool]:
    text = rendered_text(raw) if isinstance(raw, bytes) else raw
    return {marker: marker in text for marker in SURFACE_MARKERS}


def rendered_text(raw: bytes) -> str:
    screen = Screen(columns=COLUMNS, rows=ROWS)
    screen.feed(raw)
    return "\n".join(line.rstrip() for line in screen.lines())


def action_surface(raw: bytes, command: str | None = None) -> dict[str, Any]:
    text = rendered_text(raw)
    return {
        "markers": marker_flags(raw),
        "command_visible": command is not None and command in text,
        "composer_marker_visible": command is not None and f"❯ {command}" in text,
        "completion_visible": "completions" in text.lower(),
        "overlay_visible": "Setup Required" in text,
        "setup_wizard_visible": "Hermes Agent Setup Wizard" in text,
        "provider_picker_visible": "Select provider" in text,
        "model_picker_visible": "Select model" in text,
        "ready_visible": "─ ready │" in text or "ready │" in text,
        "starting_agent_visible": "starting agent" in text.lower(),
    }


def wait_for_setup_required(
    pid: int, fd: int, buffer: bytes, case: str, timeout: float
) -> tuple[bytes, int]:
    started = time.monotonic()
    deadline = started + timeout
    while time.monotonic() < deadline:
        if all(contains_marker(buffer, marker) for marker in ("Setup Required", "/model", "/setup", "Ctrl+C")):
            return buffer, round((time.monotonic() - started) * 1000)
        if child_status(pid)[0]:
            buffer += bytes()
            raise ProbeFailure(case, "setup-required", "Hermes exited before Setup Required appeared")
        buffer = drain_window(fd, buffer, 0.1)
    raise ProbeFailure(
        case,
        "setup-required",
        f"Setup Required did not appear within {timeout:.1f}s",
        {"screen_tail": safe_tail(buffer)},
    )


def run_case(reference: Path, command: str, timeout: float, observation_window: float) -> dict[str, Any]:
    case = f"post-delay-{command.removeprefix('/')}"
    root = Path(tempfile.mkdtemp(prefix=f"hades-hermes-{case}-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        files_before = file_inventory(home)
        pid, fd, slave_path = spawn_unconfigured(reference, home)
        buffer, startup_surface, stable_samples, startup_ms = stable_surface(
            pid, fd, buffer, case, timeout
        )
        startup_flags = terminal_flags(slave_path)
        if startup_flags["canonical"] or startup_flags["echo"]:
            raise ProbeFailure(case, "startup", "Hermes did not enter raw mode")

        files_at_submit = file_inventory(home)
        config_at_submit = config_shape(home / "config.yaml")
        write_bytes(fd, b"/help\r")
        buffer, setup_required_ms = wait_for_setup_required(
            pid, fd, buffer, case, min(timeout, SETUP_REQUIRED_TIMEOUT_SECONDS)
        )
        setup_required_at = time.monotonic()
        setup_required_surface = action_surface(buffer)
        if not setup_required_surface["overlay_visible"]:
            raise ProbeFailure(case, "setup-required", "setup-required marker was not visible")

        phases: list[dict[str, Any]] = []
        write_bytes(fd, command.encode())
        buffer = drain_window(fd, buffer, 0.5)
        phases.append(
            {
                "id": "type-command",
                "input": {"kind": "text", "value": command},
                "output": action_surface(buffer, command),
            }
        )

        write_bytes(fd, b"\r")
        buffer = drain_window(fd, buffer, observation_window)
        phases.append(
            {
                "id": "first-enter",
                "input": {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                "output": action_surface(buffer, command),
            }
        )

        first_enter_surface = phases[-1]["output"]
        second_enter_sent = not any(
            first_enter_surface[key]
            for key in ("setup_wizard_visible", "provider_picker_visible", "model_picker_visible")
        )
        if second_enter_sent and not child_status(pid)[0]:
            write_bytes(fd, b"\r")
            buffer = drain_window(fd, buffer, observation_window)
            phases.append(
                {
                    "id": "second-enter",
                    "input": {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                    "output": action_surface(buffer, command),
                }
            )

        files_after_action = file_inventory(home)
        config_after_action = config_shape(home / "config.yaml")
        buffer, cleanup_result = cleanup(pid, fd, buffer, case, timeout)
        cleanup_flags = terminal_flags(slave_path)
        if cleanup_result["exit"] != {"kind": "exit", "code": 0}:
            raise ProbeFailure(case, "cleanup", f"unexpected cleanup result: {cleanup_result}")
        if not cleanup_result["alternate_screen_entered"] or not cleanup_result["alternate_screen_left"]:
            raise ProbeFailure(case, "cleanup", "alternate-screen cleanup was incomplete")
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeFailure(case, "cleanup", f"terminal was not restored: {cleanup_flags}")

        return {
            "id": case,
            "status": "passed",
            "input": {
                "initial_command": "/help",
                "follow_up_command": command,
                "enter_count_after_follow_up": 2 if second_enter_sent else 1,
            },
            "timing": {
                "process_start_to_stable_ms": startup_ms,
                "stable_samples": stable_samples,
                "submit_to_setup_required_ms": setup_required_ms,
                "observation_window_seconds": observation_window,
                "setup_required_to_follow_up_ms": round((time.monotonic() - setup_required_at) * 1000),
            },
            "startup": {"surface": startup_surface, "raw_mode": startup_flags},
            "setup_required": setup_required_surface,
            "phases": phases,
            "action_surface": action_surface(buffer, command),
            "config_at_submit": config_at_submit,
            "config_after_action": config_after_action,
            "config_changed": config_at_submit != config_after_action,
            "artifact_classes_at_submit": artifact_classes(files_at_submit - files_before),
            "artifact_classes_during_action": artifact_classes(files_after_action - files_at_submit),
            "provider_endpoint": "absent",
            "provider_request_started": False,
            "cleanup": {**cleanup_result, "terminal_flags": cleanup_flags},
        }
    finally:
        if pid != -1 and not child_status(pid)[0]:
            try:
                cleanup(pid, fd, buffer, case, timeout)
            except (OSError, ProbeFailure):
                pass
        elif fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
        shutil.rmtree(root, ignore_errors=True)


def run_ctrl_c_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "post-delay-ctrl-c"
    root = Path(tempfile.mkdtemp(prefix=f"hades-hermes-{case}-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        files_before = file_inventory(home)
        pid, fd, slave_path = spawn_unconfigured(reference, home)
        buffer, startup_surface, stable_samples, startup_ms = stable_surface(
            pid, fd, buffer, case, timeout
        )
        startup_flags = terminal_flags(slave_path)
        if startup_flags["canonical"] or startup_flags["echo"]:
            raise ProbeFailure(case, "startup", "Hermes did not enter raw mode")
        files_at_submit = file_inventory(home)
        config_at_submit = config_shape(home / "config.yaml")
        write_bytes(fd, b"/help\r")
        buffer, setup_required_ms = wait_for_setup_required(
            pid, fd, buffer, case, min(timeout, SETUP_REQUIRED_TIMEOUT_SECONDS)
        )
        write_bytes(fd, b"\x03")
        buffer = drain_window(fd, buffer, 0.5)
        first_ctrl_c_exited, first_ctrl_c_status = child_status(pid)
        first_ctrl_c_surface = action_surface(buffer)
        if first_ctrl_c_exited:
            raise ProbeFailure(
                case,
                "first-ctrl-c",
                "first Ctrl+C exited before the second cleanup press",
                {"exit_status": first_ctrl_c_status},
            )
        if not first_ctrl_c_surface["overlay_visible"]:
            raise ProbeFailure(case, "first-ctrl-c", "first Ctrl+C removed the setup-required surface")

        files_after_first_ctrl_c = file_inventory(home)
        config_after_first_ctrl_c = config_shape(home / "config.yaml")
        buffer, cleanup_result = cleanup(pid, fd, buffer, case, timeout)
        cleanup_flags = terminal_flags(slave_path)
        if cleanup_result["exit"] != {"kind": "exit", "code": 0}:
            raise ProbeFailure(case, "cleanup", f"unexpected cleanup result: {cleanup_result}")
        if not cleanup_result["alternate_screen_entered"] or not cleanup_result["alternate_screen_left"]:
            raise ProbeFailure(case, "cleanup", "alternate-screen cleanup was incomplete")
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeFailure(case, "cleanup", f"terminal was not restored: {cleanup_flags}")
        return {
            "id": case,
            "status": "passed",
            "input": {
                "initial_command": "/help",
                "cleanup_sequence": ["Ctrl+C", "Ctrl+C"],
            },
            "timing": {
                "process_start_to_stable_ms": startup_ms,
                "stable_samples": stable_samples,
                "submit_to_setup_required_ms": setup_required_ms,
            },
            "startup": {"surface": startup_surface, "raw_mode": startup_flags},
            "first_ctrl_c": {
                "process_alive": True,
                "surface": first_ctrl_c_surface,
                "config_changed": config_at_submit != config_after_first_ctrl_c,
                "artifact_classes_during_input": artifact_classes(
                    files_after_first_ctrl_c - files_at_submit
                ),
            },
            "config_at_submit": config_at_submit,
            "config_after_first_ctrl_c": config_after_first_ctrl_c,
            "config_after_cleanup": config_shape(home / "config.yaml"),
            "artifact_classes_at_submit": artifact_classes(files_at_submit - files_before),
            "provider_endpoint": "absent",
            "provider_request_started": False,
            "cleanup": {**cleanup_result, "terminal_flags": cleanup_flags},
        }
    finally:
        if pid != -1 and not child_status(pid)[0]:
            try:
                cleanup(pid, fd, buffer, case, timeout)
            except (OSError, ProbeFailure):
                pass
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
    parser.add_argument("--observation-window", type=float, default=OBSERVATION_WINDOW_SECONDS)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0068",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {"columns": COLUMNS, "rows": ROWS},
            "capture": "fresh direct PTYs after delayed /help Setup Required transition",
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, PTY paths, session identifiers, timestamps, config values, credentials, and raw redraw bytes are omitted or represented by placeholders.",
            "Each fresh case starts without config or a provider endpoint, submits /help, waits for the delayed Setup Required surface, then probes only one visible follow-up command. No credentials, OAuth, external network, provider value, or model choice is entered.",
            "Follow-up output is measured from the PTY bytes written after the action; the original overlay is recorded separately so retained overlay copy is not mistaken for a newly opened surface.",
            "The report records bounded action semantics and cleanup. It does not infer behavior for commands, keys, or setup stages not exercised here.",
        ],
        "cases": [],
        "unknowns": [
            "No provider setup, credential, OAuth, external network, model selection, or configured prompt was exercised.",
            "Behavior after selecting a provider or model, and any setup persistence beyond the bounded config readback, remains unknown.",
            "Exact full-screen ANSI equivalence and terminal-dependent behavior outside the 120x40 direct PTY remain unknown.",
        ],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"] = [
            run_case(reference, command, args.timeout, args.observation_window)
            for command in FOLLOW_UP_COMMANDS
        ]
        report["cases"].append(run_ctrl_c_case(reference, args.timeout))
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
