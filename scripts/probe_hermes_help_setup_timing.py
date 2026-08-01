#!/usr/bin/env python3
"""Measure Hermes' delayed /help to Setup Required transition."""

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
    normalized,
    safe_tail,
)
from probe_hermes_terminal_palette import child_status, write_bytes
from probe_hermes_unconfigured_resolution import cleanup, drain_window, spawn_unconfigured
from probe_hermes_unconfigured_startup import artifact_classes, stable_surface, surface_state
from probe_tui_lifecycle import terminal_flags


OBSERVATION_WINDOW_SECONDS = 15.0
REPEAT_COUNT = 2


def surface_kind(raw: bytes) -> str:
    text = normalized(raw)
    lowered = text.lower()
    if "Setup Required" in text:
        return "setup-required"
    if "─ ready │" in text or "ready │" in text:
        return "ready"
    if "starting agent" in lowered:
        return "starting-agent"
    return "other"


def marker_flags(raw: bytes) -> dict[str, bool]:
    text = normalized(raw)
    return {
        "Setup Required": "Setup Required" in text,
        "model provider": "model provider" in text.lower(),
        "/model": "/model" in text,
        "/setup": "/setup" in text,
        "Ctrl+C": "Ctrl+C" in text,
        "starting agent": "starting agent" in text.lower(),
        "ready": "─ ready │" in text or "ready │" in text,
    }


def run_case(reference: Path, case_number: int, timeout: float, observation_window: float) -> dict[str, Any]:
    case = f"help-setup-required-timing-{case_number}"
    root = Path(tempfile.mkdtemp(prefix=f"hades-hermes-{case}-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    process_started = time.monotonic()
    try:
        files_before = file_inventory(home)
        pid, fd, slave_path = spawn_unconfigured(reference, home)
        buffer, startup_surface, stable_samples, startup_ms = stable_surface(
            pid, fd, buffer, case, timeout
        )
        stable_at_ms = round((time.monotonic() - process_started) * 1000)
        startup_flags = terminal_flags(slave_path)
        if startup_flags["canonical"] or startup_flags["echo"]:
            raise ProbeFailure(case, "startup", "Hermes did not enter raw mode")
        if startup_surface["status"] != "starting agent":
            raise ProbeFailure(case, "startup", f"unexpected startup status: {startup_surface}")

        files_at_submit = file_inventory(home)
        config_at_submit = config_shape(home / "config.yaml")
        submit_at_ms = round((time.monotonic() - process_started) * 1000)
        write_bytes(fd, b"/help\r")
        transition_trace: list[dict[str, int | str]] = [
            {"elapsed_ms": stable_at_ms, "surface": "starting-agent"}
        ]
        previous_surface = "starting-agent"
        setup_required_at_ms: int | None = None
        observation_deadline = time.monotonic() + observation_window
        while time.monotonic() < observation_deadline and not child_status(pid)[0]:
            current_surface = surface_kind(buffer)
            elapsed_ms = round((time.monotonic() - process_started) * 1000)
            if current_surface != previous_surface:
                transition_trace.append({"elapsed_ms": elapsed_ms, "surface": current_surface})
                previous_surface = current_surface
            if current_surface == "setup-required" and setup_required_at_ms is None:
                setup_required_at_ms = elapsed_ms
            buffer = drain_window(fd, buffer, 0.1)
        buffer += drain_window(fd, buffer, 0.0)
        final_surface = surface_kind(buffer)
        if final_surface != previous_surface:
            elapsed_ms = round((time.monotonic() - process_started) * 1000)
            transition_trace.append({"elapsed_ms": elapsed_ms, "surface": final_surface})
            previous_surface = final_surface
        if setup_required_at_ms is None and final_surface == "setup-required":
            setup_required_at_ms = round((time.monotonic() - process_started) * 1000)
        if setup_required_at_ms is None:
            raise ProbeFailure(
                case,
                "setup-required-transition",
                "Setup Required did not appear in the bounded observation window",
                {"screen_tail": safe_tail(buffer)},
            )

        files_after_submit = file_inventory(home)
        config_after_submit = config_shape(home / "config.yaml")
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
            "environment": {
                "provider_endpoint": "absent",
                "config": "absent",
                "startup_timeout_ms": 8000,
                "terminal": {"columns": COLUMNS, "rows": ROWS},
            },
            "input": {
                "command": "/help",
                "enter_sent": True,
                "cleanup": ["Ctrl+C", "Ctrl+C"],
            },
            "timing": {
                "process_start_to_stable_ms": stable_at_ms,
                "stable_surface_reported_ms": startup_ms,
                "stable_to_submit_ms": submit_at_ms - stable_at_ms,
                "process_start_to_setup_required_ms": setup_required_at_ms,
                "submit_to_setup_required_ms": setup_required_at_ms - submit_at_ms,
                "observation_window_seconds": observation_window,
            },
            "surfaces": {
                "startup": startup_surface,
                "transition_trace": transition_trace,
                "after_submit": {
                    "surface": final_surface,
                    "markers": marker_flags(buffer),
                    "retained_input_actions_visible": marker_flags(buffer)["/model"]
                    and marker_flags(buffer)["/setup"],
                },
            },
            "cleanup": {**cleanup_result, "terminal_flags": cleanup_flags},
            "config_at_submit": config_at_submit,
            "config_after_submit": config_after_submit,
            "config_changed": config_at_submit != config_after_submit,
            "artifact_classes_at_submit": artifact_classes(files_at_submit - files_before),
            "artifact_classes_during_submit": artifact_classes(files_after_submit - files_at_submit),
            "fresh_home_config_exists_after_cleanup": config_shape(home / "config.yaml")["exists"],
        }
    finally:
        if pid != -1 and not child_status(pid)[0]:
            try:
                cleanup(pid, fd, buffer, case, timeout)
            except (OSError, ProbeFailure):
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
        "observation_id": "OBS-0066",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with timed transition samples",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, provider endpoints, credentials, session identifiers, and raw redraw bytes are omitted or replaced by placeholders.",
            "Both fresh cases start with no config and no Hades/OpenAI provider environment; only /help plus Enter is sent, followed by two Ctrl+C cleanup presses. No /model, /setup, credentials, OAuth, external network, provider value, or model request is entered.",
            "The startup timeout environment is retained as 8000 ms because it is part of the observed runtime setup; measured timings describe these runs and are not generalized into a universal timeout contract.",
            "Config evidence is reduced to normalized existence/shape and artifact evidence to normalized classes; behavior after the bounded observation remains unknown.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"] = [
            run_case(reference, index, args.timeout, args.observation_window)
            for index in range(1, REPEAT_COUNT + 1)
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
