#!/usr/bin/env python3
"""Capture configured Hermes /help geometry across safe PTY resizes."""

from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_slash_commands import (
    DEFAULT_REFERENCE,
    ProbeFailure,
    child_status,
    clean_exit,
    safe_tail,
    start_ready,
    stop,
    write_bytes,
)
from probe_hermes_terminal_palette import Screen, drain, set_window_size
from probe_tui_lifecycle import set_slave_window_size, slave_path_for_pid


SOURCE_COMMIT = "e444d165807f489b5c1ab8e4a612c8d09c2e67a2"
INITIAL_COLUMNS = 120
INITIAL_ROWS = 40
RESIZE_CASES = ((120, 40), (100, 30), (160, 50))


def screen_lines(raw: bytes, columns: int, rows: int) -> list[str]:
    screen = Screen(columns=columns, rows=rows)
    screen.feed(raw)
    return [line.rstrip() for line in screen.lines()]


def panel_state(raw: bytes, columns: int, rows: int) -> dict[str, Any] | None:
    lines = screen_lines(raw, columns, rows)
    command_index = next(
        (index for index, line in enumerate(lines) if "Show available commands" in line),
        None,
    )
    if command_index is None or command_index == 0 or command_index + 1 >= len(lines):
        return None
    top = lines[command_index - 1]
    command = lines[command_index]
    bottom = lines[command_index + 1]
    composer_index = next((index for index, line in enumerate(lines) if "❯ /help" in line), None)
    top_border = top.strip()
    bottom_border = bottom.strip()
    if (
        not top_border.startswith("╔")
        or not bottom_border.startswith("╚")
        or not top_border.endswith("╗")
        or not bottom_border.endswith("╝")
        or "Show available commands" not in command
        or composer_index is None
    ):
        return None
    return {
        "x": len(top) - len(top.lstrip()),
        "y": command_index - 1,
        "width": len(top_border),
        "height": 3,
        "top_border": top_border,
        "command": "/help Show available commands",
        "bottom_border": bottom_border,
        "composer": "❯ /help",
        "composer_y": composer_index,
        "ready_marker_present": any("─ ready │" in line for line in lines),
    }


def wait_for_panel(
    pid: int,
    fd: int,
    buffer: bytes,
    columns: int,
    rows: int,
    timeout: float,
) -> tuple[bytes, dict[str, Any], int]:
    deadline = time.monotonic() + timeout
    previous: str | None = None
    stable_samples = 0
    while time.monotonic() < deadline:
        state = panel_state(buffer, columns, rows)
        if state is not None:
            signature = json.dumps(state, ensure_ascii=False, sort_keys=True)
            if signature == previous:
                stable_samples += 1
            else:
                previous = signature
                stable_samples = 1
            if stable_samples >= 3:
                return buffer, state, stable_samples
        else:
            previous = None
            stable_samples = 0
        if child_status(pid)[0]:
            raise ProbeFailure(
                "configured-help-resize",
                f"panel-{columns}x{rows}",
                "Hermes exited before the resized Help panel stabilized",
                {"screen_tail": safe_tail(buffer)},
            )
        buffer = drain(pid, fd, buffer, 0.05)
    raise ProbeFailure(
        "configured-help-resize",
        f"panel-{columns}x{rows}",
        f"timed out after {timeout:.1f}s waiting for a stable resized Help panel",
        {"screen_tail": safe_tail(buffer)},
    )


def resize_pty(pid: int, fd: int, slave_path: str, columns: int, rows: int) -> None:
    set_window_size(fd, columns, rows)
    set_slave_window_size(slave_path, columns, rows)
    os.kill(pid, signal.SIGWINCH)


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "configured-help-resize"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-help-resize-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        pid, fd, buffer = start_ready(reference, home, case, timeout)
        slave_path = slave_path_for_pid(pid)
        write_bytes(fd, b"/help\r")
        observations: list[dict[str, Any]] = []
        for index, (columns, rows) in enumerate(RESIZE_CASES):
            if index:
                resize_pty(pid, fd, slave_path, columns, rows)
            buffer, panel, stable_samples = wait_for_panel(
                pid, fd, buffer, columns, rows, timeout
            )
            observations.append(
                {
                    "columns": columns,
                    "rows": rows,
                    "stable_samples": stable_samples,
                    "panel": panel,
                }
            )

        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)
        if not exited:
            raise ProbeFailure(case, "cleanup", "Hermes did not exit after bounded Ctrl+C cleanup")
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "/help", "bytes_hex": "2f 68 65 6c 70"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {
                    "kind": "resize",
                    "values": ["100x30", "160x50"],
                    "meaning": "safe PTY geometry probes",
                },
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "bounded cleanup"},
            ],
            "observations": observations,
            "provider_request": "not observed; the configured loopback endpoint was intentionally absent",
            "side_effects": "Only /help, PTY resize, and bounded Ctrl+C cleanup were exercised; no provider request or external network was used",
            "clean_exit": True,
            "alternate_screen_left": b"\x1b[?1049l" in buffer,
        }
    finally:
        if pid != -1:
            stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def safe_failure(error: BaseException) -> dict[str, Any] | str:
    if not isinstance(error, ProbeFailure):
        return str(error)
    failure = {"case": error.case, "step": error.step, "message": error.message}
    failure.update(error.details)
    return failure


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0102",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "initial_columns": INITIAL_COLUMNS,
                "initial_rows": INITIAL_ROWS,
                "resize_cases": [f"{columns}x{rows}" for columns, rows in RESIZE_CASES[1:]],
                "capture": "fresh direct PTY with normalized ANSI screen geometry",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, loopback URL, credentials, session IDs, timestamps, and raw redraw bytes are omitted or represented by stable markers.",
            "The configured loopback endpoint is intentionally absent; only /help, PTY geometry changes, and bounded Ctrl+C cleanup are exercised.",
            "Panel geometry is measured from the final normalized ANSI screen at each requested size; dynamic inventories, focus, and command semantics are not inferred.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"].append(run_case(reference, args.timeout))
        report["unknowns"] = [
            "Minimum terminal geometry, clipping below the tested sizes, focus/navigation, repeated-help behavior, and dynamic catalog behavior remain unknown.",
            "The observations claim only stable panel geometry, composer retention, liveness, and bounded cleanup at 120x40, 100x30, and 160x50.",
            "No provider request, credential, OAuth flow, external network, or side-effecting command was exercised.",
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
