#!/usr/bin/env python3
"""Capture the stable Hermes /help panel without executing other commands."""

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
    SOURCE_COMMIT,
    ProbeFailure,
    clean_exit,
    contains_marker,
    safe_tail,
    start_ready,
    stop,
    wait_for,
    write_bytes,
)
from probe_hermes_terminal_palette import Screen, drain


HELP_PANEL_MARKERS = (
    "/help",
    "Show available commands",
    "/help for commands",
)
MAIN_SURFACE_MARKERS = (
    "Hermes Agent",
    "Available Tools",
    "Available Skills",
    "/help for commands",
)


def screen_lines(raw: bytes) -> list[str]:
    screen = Screen(columns=COLUMNS, rows=40)
    screen.feed(raw)
    return [line.rstrip() for line in screen.lines()]


def panel_state(raw: bytes) -> dict[str, str]:
    lines = screen_lines(raw)
    command_index = next(
        (index for index, line in enumerate(lines) if "Show available commands" in line),
        None,
    )
    command = lines[command_index] if command_index is not None else None
    top = lines[command_index - 1] if command_index is not None and command_index > 0 else None
    bottom = lines[command_index + 1] if command_index is not None and command_index + 1 < len(lines) else None
    composer = next((line for line in lines if "❯ /help" in line), None)
    if (
        top is None
        or command is None
        or bottom is None
        or composer is None
        or not top.lstrip().startswith("╔")
        or not bottom.lstrip().startswith("╚")
    ):
        raise ProbeFailure(
            "configured-help-catalog",
            "help-screen",
            "stable /help panel did not render its bordered command row and composer",
            {"screen_lines": lines},
        )
    return {
        "top_border": top.strip(),
        "command": "/help Show available commands",
        "bottom_border": bottom.strip(),
        "composer": "❯ /help",
        "command_row_present": "Show available commands" in command,
    }


def wait_for_stable_help(
    pid: int, fd: int, buffer: bytes, timeout: float
) -> tuple[bytes, dict[str, str], int]:
    deadline = time.monotonic() + timeout
    previous: tuple[tuple[str, str], ...] | None = None
    stable_samples = 0
    while time.monotonic() < deadline:
        try:
            state = panel_state(buffer)
        except ProbeFailure:
            state = None
        if state is not None:
            signature = tuple(sorted(state.items()))
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
        buffer = drain(pid, fd, buffer, 0.05)
    raise ProbeFailure(
        "configured-help-catalog",
        "help-screen",
        f"timed out after {timeout:.1f}s waiting for a stable /help panel",
        {"screen_lines": screen_lines(buffer)},
    )


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "configured-help-catalog"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-help-catalog-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        pid, fd, buffer = start_ready(reference, home, case, timeout)
        write_bytes(fd, b"/help\r")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "help-landmarks",
            lambda current: all(contains_marker(current, marker) for marker in HELP_PANEL_MARKERS),
            timeout,
        )
        buffer, panel, stable_samples = wait_for_stable_help(pid, fd, buffer, timeout)
        buffer = drain(pid, fd, buffer, 0.2)
        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)
        if not exited:
            raise ProbeFailure(case, "cleanup", "Hermes did not exit cleanly")
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "/help", "bytes_hex": "2f 68 65 6c 70"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "bounded cleanup"},
            ],
            "stable_samples": stable_samples,
            "main_surface_markers": list(MAIN_SURFACE_MARKERS),
            "help_panel": panel,
            "state": "ready",
            "provider_request": "not observed; the configured loopback endpoint was intentionally absent",
            "side_effects": "No other slash command, provider request, credential, OAuth flow, or external network was exercised",
            "clean_exit": exited,
        }
    finally:
        if pid != -1:
            stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def emit_report(report: dict[str, Any], path: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")


def safe_failure(error: BaseException) -> Any:
    if not isinstance(error, ProbeFailure):
        return str(error)
    details = dict(error.details)
    if "screen_lines" in details:
        details["screen_lines"] = [safe_tail(line.encode()) for line in details["screen_lines"]]
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
        "observation_id": "OBS-0098",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": 40,
                "capture": "fresh direct PTY with normalized stable landmarks and ANSI screen model",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, loopback URL, credentials, session IDs, timestamps, dynamic tool/skill inventories, and animated redraw bytes are omitted or represented by stable markers.",
            "The configured loopback endpoint is intentionally absent; /help is observed without a provider request, credential, OAuth action, or external network.",
            "The help panel is represented by its stable border, command row, composer row, and main-surface landmarks; dynamic counts and the complete slash-command catalog are not promoted into the contract.",
            "Ctrl+C is sent after the stable help panel and must restore the terminal and exit cleanly.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"].append(run_case(reference, args.timeout))
        report["unknowns"] = [
            "The complete slash-command catalog, aliases, arguments, command-specific state, and help pagination remain unknown.",
            "Provider/tool/skill counts, discovery timing, redraw ordering, and dynamic command inventory remain outside this stable help-panel contract.",
            "No side-effecting slash command, reachable provider, tool call, or external network behavior is claimed by this observation.",
        ]
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        report["failure"] = safe_failure(error)
    emit_report(report, args.report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
