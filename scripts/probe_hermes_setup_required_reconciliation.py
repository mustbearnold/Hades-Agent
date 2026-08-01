#!/usr/bin/env python3
"""Reconcile Hermes early setup-required input with stable startup input."""

from __future__ import annotations

import argparse
import json
import os
import select
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from probe_hermes_setup_config_shape import config_shape, file_inventory
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
    normalized,
    read_available,
    set_window_size,
    stop,
)
from probe_hermes_unconfigured_resolution import (
    cleanup,
    drain_window,
    spawn_unconfigured,
)
from probe_hermes_unconfigured_startup import artifact_classes, stable_surface, surface_state
from probe_tui_lifecycle import terminal_flags


BASE_MARKERS = ("Hermes Agent", "Nous Research", "Available Tools", "Available Skills")
OBSERVATION_SECONDS = 15.0
MARKERS = (
    "Hermes Agent",
    "starting agent",
    "Setup Required",
    "setup required",
    "model provider",
    "/model",
    "/setup",
    "─ ready │",
    "Provider error",
)
Predicate = Callable[[str], bool]


def wait_for_direct_marker(
    pid: int, fd: int, buffer: bytes, marker: str, case: str, timeout: float
) -> tuple[bytes, int]:
    started = time.monotonic()
    deadline = started + timeout
    while time.monotonic() < deadline:
        if marker in normalized(buffer):
            return buffer, round((time.monotonic() - started) * 1000)
        exited, status = child_status(pid)
        if exited:
            buffer += read_available(fd)
            raise ProbeFailure(
                case,
                "early-startup",
                "Hermes exited before the early marker",
                {"exit_status": status, "screen_tail": safe_tail(buffer)},
            )
        readable, _, _ = select.select([fd], [], [], min(0.05, max(0.0, deadline - time.monotonic())))
        if readable:
            buffer += read_available(fd)
    raise ProbeFailure(
        case,
        "early-startup",
        f"timed out after {timeout:.1f}s waiting for {marker!r}",
        {"screen_tail": safe_tail(buffer)},
    )


def marker_flags(raw: bytes | str) -> dict[str, bool]:
    text = normalized(raw) if isinstance(raw, bytes) else raw
    return {marker: marker in text for marker in MARKERS}


def status_sequence(raw: bytes) -> list[str]:
    text = normalized(raw)
    statuses: list[str] = []
    for status in ("starting agent", "setup required", "ready"):
        if status in text.lower():
            statuses.append(status)
    return statuses


def outcome_kind(raw: bytes | str) -> str:
    text = normalized(raw) if isinstance(raw, bytes) else raw
    lowered = text.lower()
    if "setup required" in lowered:
        return "setup-required"
    if "starting agent" in lowered:
        return "starting-agent-boundary"
    if "─ ready │" in text or "ready │" in text:
        return "ready"
    return "other"


def run_direct_case(
    reference: Path, timing: str, timeout: float, observation_seconds: float
) -> dict[str, Any]:
    case = f"direct-{timing}-help"
    root = Path(tempfile.mkdtemp(prefix=f"hades-hermes-{case}-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        files_before = file_inventory(home)
        pid, fd, slave_path = spawn_unconfigured(reference, home)
        if timing == "early":
            buffer, input_ms = wait_for_direct_marker(pid, fd, buffer, "Hermes Agent", case, timeout)
            startup_surface = surface_state(buffer)
        elif timing == "stable":
            buffer, startup_surface, stable_samples, input_ms = stable_surface(
                pid, fd, buffer, case, timeout
            )
        else:
            raise ProbeFailure(case, "precondition", f"unsupported timing variant: {timing}")

        startup_flags = terminal_flags(slave_path)
        if startup_flags["canonical"] or startup_flags["echo"]:
            raise ProbeFailure(case, "startup", "Hermes did not enter raw mode")
        files_before_input = file_inventory(home)
        config_before_input = config_shape(home / "config.yaml")
        os.write(fd, b"/help\r")
        observation_started = time.monotonic()
        observation_deadline = observation_started + observation_seconds
        while time.monotonic() < observation_deadline and not child_status(pid)[0]:
            buffer = drain_window(fd, buffer, 0.15)
        buffer += read_available(fd)
        files_after_input = file_inventory(home)
        config_after_input = config_shape(home / "config.yaml")
        observed_outcome = outcome_kind(buffer)
        cleanup_buffer, cleanup_result = cleanup(pid, fd, buffer, case, timeout)
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
            "capture": "direct PTY",
            "input_timing": timing,
            "input": {"command": "/help", "enter_sent": True},
            "startup": {
                "surface": startup_surface,
                "stable_samples": stable_samples if timing == "stable" else None,
                "time_to_input_marker_ms": input_ms,
                "raw_mode": startup_flags,
            },
            "observation": {
                "seconds": observation_seconds,
                "outcome": observed_outcome,
                "marker_flags": marker_flags(buffer),
                "status_sequence": status_sequence(buffer),
            },
            "cleanup": {**cleanup_result, "terminal_flags": cleanup_flags},
            "config_before_input": config_before_input,
            "config_after_input": config_after_input,
            "config_changed": config_before_input != config_after_input,
            "artifact_classes_before_input": artifact_classes(files_before_input - files_before),
            "artifact_classes_during_input": artifact_classes(files_after_input - files_before_input),
            "cleanup_screen_tail_present": bool(safe_tail(cleanup_buffer)),
        }
    finally:
        if pid != -1 and not child_status(pid)[0]:
            stop(pid, fd)
        elif fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
        shutil.rmtree(root, ignore_errors=True)


def tmux_run(reference: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["tmux", *arguments], cwd=reference, capture_output=True, text=True, check=False
    )


def tmux_capture(reference: Path, session: str) -> str:
    result = tmux_run(reference, "capture-pane", "-p", "-t", session)
    return result.stdout if result.returncode == 0 else ""


def tmux_exists(reference: Path, session: str) -> bool:
    return tmux_run(reference, "has-session", "-t", session).returncode == 0


def tmux_wait(
    reference: Path, session: str, predicate: Predicate, case: str, timeout: float
) -> tuple[str, int]:
    started = time.monotonic()
    deadline = started + timeout
    latest = ""
    while time.monotonic() < deadline:
        latest = tmux_capture(reference, session)
        if predicate(latest):
            return latest, round((time.monotonic() - started) * 1000)
        if not tmux_exists(reference, session):
            raise ProbeFailure(case, "tmux", "tmux session exited before the assertion")
        time.sleep(0.05)
    raise ProbeFailure(case, "tmux", f"timed out after {timeout:.1f}s", {"screen_tail": latest[-2000:]})


def tmux_wait_stable(
    reference: Path, session: str, case: str, timeout: float
) -> tuple[str, int]:
    started = time.monotonic()
    deadline = started + timeout
    previous = ""
    stable = 0
    latest = ""
    while time.monotonic() < deadline:
        latest = tmux_capture(reference, session)
        if all(marker in latest for marker in BASE_MARKERS) and "starting agent" in latest.lower():
            if latest == previous:
                stable += 1
            else:
                previous = latest
                stable = 1
            if stable >= 3:
                return latest, round((time.monotonic() - started) * 1000)
        if not tmux_exists(reference, session):
            raise ProbeFailure(case, "tmux-stable", "tmux session exited before stable startup")
        time.sleep(0.05)
    raise ProbeFailure(case, "tmux-stable", f"timed out after {timeout:.1f}s", {"screen_tail": latest[-2000:]})


def run_tmux_case(
    reference: Path, timing: str, timeout: float, observation_seconds: float
) -> dict[str, Any]:
    case = f"tmux-{timing}-help"
    root = Path(tempfile.mkdtemp(prefix=f"hades-hermes-{case}-"))
    home = root / "home"
    home.mkdir()
    session = f"hades-reconcile-{os.getpid()}-{int(time.time() * 1000)}"
    environment = safe_environment(reference, home)
    for key in (
        "HADES_PROVIDER_BASE_URL",
        "HADES_PROVIDER_API_KEY",
        "HADES_MODEL",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
    ):
        environment.pop(key, None)
    command = shlex.join(
        ["env", *(f"{key}={value}" for key, value in environment.items()), "uv", "run", "hermes", "--tui"]
    )
    try:
        started = tmux_run(
            reference,
            "new-session",
            "-d",
            "-s",
            session,
            "-x",
            str(COLUMNS),
            "-y",
            str(ROWS),
            "-c",
            str(reference),
            command,
        )
        if started.returncode != 0:
            raise ProbeFailure(case, "tmux-start", started.stderr.strip() or "tmux failed to start")
        files_before = file_inventory(home)
        if timing == "early":
            before_input, input_ms = tmux_wait(
                reference, session, lambda screen: "Hermes Agent" in screen, case, timeout
            )
        elif timing == "stable":
            before_input, input_ms = tmux_wait_stable(reference, session, case, timeout)
        else:
            raise ProbeFailure(case, "precondition", f"unsupported timing variant: {timing}")
        files_at_input = file_inventory(home)
        config_before = config_shape(home / "config.yaml")
        tmux_run(reference, "send-keys", "-t", session, "-l", "/help")
        tmux_run(reference, "send-keys", "-t", session, "C-m")
        observation_started = time.monotonic()
        deadline = observation_started + observation_seconds
        latest = before_input
        while time.monotonic() < deadline and tmux_exists(reference, session):
            latest = tmux_capture(reference, session)
            time.sleep(0.15)
        files_after = file_inventory(home)
        config_after = config_shape(home / "config.yaml")
        tmux_run(reference, "send-keys", "-t", session, "C-c")
        time.sleep(0.25)
        tmux_run(reference, "send-keys", "-t", session, "C-c")
        exit_deadline = time.monotonic() + timeout
        while time.monotonic() < exit_deadline and tmux_exists(reference, session):
            time.sleep(0.05)
        clean_exit = not tmux_exists(reference, session)
        if not clean_exit:
            raise ProbeFailure(case, "cleanup", "tmux session did not exit after two Ctrl+C presses")
        files_after_cleanup = file_inventory(home)
        return {
            "id": case,
            "status": "passed",
            "capture": "tmux capture-pane -p",
            "input_timing": timing,
            "input": {"command": "/help", "enter_sent": True},
            "startup": {"screen_markers": marker_flags(before_input), "time_to_input_marker_ms": input_ms},
            "observation": {
                "seconds": observation_seconds,
                "outcome": outcome_kind(latest),
                "marker_flags": marker_flags(latest),
                "status_sequence": status_sequence(latest.encode()),
            },
            "cleanup": {"ctrl_c_presses": 2, "tmux_session_exited": clean_exit},
            "config_before_input": config_before,
            "config_after_input": config_after,
            "config_changed": config_before != config_after,
            "artifact_classes_before_input": artifact_classes(files_at_input - files_before),
            "artifact_classes_during_input": artifact_classes(files_after - files_at_input),
            "artifact_classes_during_cleanup": artifact_classes(files_after_cleanup - files_after),
        }
    finally:
        tmux_run(reference, "kill-session", "-t", session)
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
    parser.add_argument("--observation-window", type=float, default=OBSERVATION_SECONDS)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0065",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {"columns": COLUMNS, "rows": ROWS},
            "capture": "direct PTY and tmux capture-pane with bounded timing variants",
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, provider endpoints, credentials, session identifiers, timestamps, and raw redraw bytes are omitted or replaced by placeholders.",
            "All cases use no config and no Hades/OpenAI provider environment; only /help plus Enter is sent, with no credentials, OAuth, external network, provider value, or model request.",
            "The early variant sends /help after the first Hermes Agent banner marker; the stable variant waits for repeated starting-agent surface samples. This timing distinction is the subject of the observation.",
            "Behavior beyond each bounded observation window is unknown. Tmux cleanup is represented by session exit; direct PTY cleanup additionally verifies canonical input and echo restoration.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"] = [
            run_direct_case(reference, "early", args.timeout, args.observation_window),
            run_direct_case(reference, "stable", args.timeout, args.observation_window),
            run_tmux_case(reference, "early", args.timeout, args.observation_window),
            run_tmux_case(reference, "stable", args.timeout, args.observation_window),
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
