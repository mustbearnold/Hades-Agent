#!/usr/bin/env python3
"""Capture Hermes' bounded eventual behavior without a provider configuration."""

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
from probe_tui_lifecycle import terminal_flags


COMMANDS: tuple[str | None, ...] = (None, "/setup", "/model")
OBSERVATION_WINDOW_SECONDS = 15.0
STARTUP_PHASES = ("summoning hermes", "forging session", "starting agent")
SURFACE_MARKERS = (
    "Hermes Agent Setup Wizard",
    "How would you like to set up Hermes?",
    "Select provider",
    "Select model",
    "starting agent",
    "─ ready │",
    "Provider error",
)


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
    return pid, fd, os.readlink(f"/proc/{pid}/fd/0")


def status_value(status: int | None) -> dict[str, int | str]:
    if status is None:
        return {"kind": "unknown"}
    if os.WIFEXITED(status):
        return {"kind": "exit", "code": os.WEXITSTATUS(status)}
    if os.WIFSIGNALED(status):
        return {"kind": "signal", "number": os.WTERMSIG(status)}
    return {"kind": "other", "raw": status}


def visible_markers(raw: bytes) -> dict[str, bool]:
    text = normalized(raw)
    return {marker: marker in text for marker in SURFACE_MARKERS}


def visible_outcome(raw: bytes, command: str | None) -> dict[str, Any]:
    text = normalized(raw)
    return {
        "command": command,
        "command_visible": command is not None and contains_marker(raw, command),
        "composer_marker_visible": command is not None and contains_marker(raw, f"❯ {command}"),
        "state": surface_state(raw),
        "markers": visible_markers(raw),
        "provider_request_or_error_visible": "Provider error" in text,
    }


def observe_window(
    pid: int, fd: int, buffer: bytes, duration: float
) -> tuple[bytes, dict[str, Any]]:
    started = time.monotonic()
    deadline = started + duration
    states: list[dict[str, Any]] = []
    status_transitions: list[str] = []
    previous_signature: str | None = None
    phase_seen: set[str] = set()

    while time.monotonic() < deadline:
        text = normalized(buffer).lower()
        phase_seen.update(phase for phase in STARTUP_PHASES if phase in text)
        state = surface_state(buffer)
        if state is not None:
            signature = json.dumps(state, ensure_ascii=False, sort_keys=True)
            if signature != previous_signature:
                states.append(
                    {
                        "elapsed_ms": round((time.monotonic() - started) * 1000),
                        "state": state,
                    }
                )
                previous_signature = signature
                status = str(state["status"])
                if status not in status_transitions:
                    status_transitions.append(status)
        if child_status(pid)[0]:
            break
        buffer = drain_window(fd, buffer, 0.15)

    buffer += read_available(fd)
    text = normalized(buffer).lower()
    phase_seen.update(phase for phase in STARTUP_PHASES if phase in text)
    final_state = surface_state(buffer)
    if final_state is not None:
        signature = json.dumps(final_state, ensure_ascii=False, sort_keys=True)
        if signature != previous_signature:
            states.append(
                {
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                    "state": final_state,
                }
            )
        status = str(final_state["status"])
        if status not in status_transitions:
            status_transitions.append(status)

    return buffer, {
        "observation_window_seconds": duration,
        "startup_phases_seen": {phase: phase in phase_seen for phase in STARTUP_PHASES},
        "state_transitions": states,
        "status_transitions": status_transitions,
        "ready_seen": any(item["state"]["status"] == "ready" for item in states),
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


def run_case(
    reference: Path, command: str | None, timeout: float, observation_window: float
) -> dict[str, Any]:
    label = "no-input" if command is None else command.removeprefix("/")
    case = f"unconfigured-resolution-{label}"
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
        if command is not None:
            write_bytes(fd, f"{command}\r".encode())
        buffer, observed = observe_window(pid, fd, buffer, observation_window)
        outcome = visible_outcome(buffer, command)
        if outcome["state"] is None and observed["state_transitions"]:
            outcome["state"] = observed["state_transitions"][-1]["state"]
        files_after_observation = file_inventory(home)
        config_after_observation = config_shape(home / "config.yaml")
        buffer, cleanup_result = cleanup(pid, fd, buffer, case, timeout)
        cleanup_flags = terminal_flags(slave_path)
        config_after_cleanup = config_shape(home / "config.yaml")
        files_after_cleanup = file_inventory(home)

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
                "enter_sent": command is not None,
            },
            "startup": {
                "surface": startup,
                "stable_samples": stable_samples,
                "time_to_first_stable_ms": startup_ms,
                "raw_mode": startup_flags,
            },
            "observation": observed,
            "outcome": outcome,
            "cleanup": {**cleanup_result, "terminal_flags": cleanup_flags},
            "config_at_start": config_at_start,
            "config_after_observation": config_after_observation,
            "config_after_cleanup": config_after_cleanup,
            "config_changed_during_observation": config_at_start != config_after_observation,
            "config_changed_during_cleanup": config_after_observation != config_after_cleanup,
            "artifact_classes_at_start": artifact_classes(files_at_start - files_before),
            "artifact_classes_during_observation": artifact_classes(
                files_after_observation - files_at_start
            ),
            "artifact_classes_during_cleanup": artifact_classes(
                files_after_cleanup - files_after_observation
            ),
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
    parser.add_argument("--observation-window", type=float, default=OBSERVATION_WINDOW_SECONDS)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0064",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with bounded temporal window",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, provider endpoints, credentials, session identifiers, timestamps, and raw redraw bytes are omitted or replaced by placeholders.",
            "Every case starts with no config and no Hades/OpenAI provider environment; only the sanitized /setup or /model command may be entered, with no credentials, OAuth, external network, later setup value, or model request.",
            "The report records bounded startup/status transitions, visible setup/model/provider markers, normalized config/artifact changes, cleanup, and terminal restoration; behavior outside the observation window remains unknown.",
            "Timing values describe this bounded probe run and are not generalized into a Hermes timeout or readiness contract.",
        ],
        "observation_window_seconds": args.observation_window,
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"] = [
            run_case(reference, command, args.timeout, args.observation_window)
            for command in COMMANDS
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
