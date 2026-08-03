#!/usr/bin/env python3
"""Replay configured Hades /help geometry across safe PTY resizes."""

from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import signal
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_terminal_palette import Screen
from probe_tui_lifecycle import set_slave_window_size, set_window_size
from replay_configured_help import (
    COLUMNS,
    DEFAULT_BINARY,
    spawn_configured,
)
from replay_vertical_slice import (
    ReplayFailure,
    child_done,
    read_available,
    send,
    stop_process,
    terminal_flags,
    wait_for,
    wait_for_exit,
    marker_present,
)


ROWS = 40
RESIZE_CASES = ((120, 40), (100, 30), (160, 50))
HELP_COMMAND = "/help Show available commands"
MAIN_SURFACE_MARKERS = (
    "Hermes Agent",
    "Available Tools",
    "Available Skills",
    "/help for commands",
)


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
    top = lines[command_index - 1].strip()
    command = lines[command_index].strip()
    bottom = lines[command_index + 1].strip()
    composer_index = next((index for index, line in enumerate(lines) if "❯ /help" in line), None)
    if (
        not top.startswith("╔")
        or not top.endswith("╗")
        or not bottom.startswith("╚")
        or not bottom.endswith("╝")
        or "Show available commands" not in command
        or composer_index is None
    ):
        return None
    return {
        "x": len(lines[command_index - 1]) - len(lines[command_index - 1].lstrip()),
        "y": command_index - 1,
        "width": len(top),
        "height": 3,
        "top_border": top,
        "command": HELP_COMMAND,
        "bottom_border": bottom,
        "composer": "❯ /help",
        "composer_y": composer_index,
    }


def wait_for_panel(
    pid: int,
    fd: int,
    output: bytearray,
    columns: int,
    rows: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    previous: str | None = None
    stable_samples = 0
    while time.monotonic() < deadline:
        read_available(fd, output)
        state = panel_state(bytes(output), columns, rows)
        if state is not None:
            signature = json.dumps(state, ensure_ascii=False, sort_keys=True)
            if signature == previous:
                stable_samples += 1
            else:
                previous = signature
                stable_samples = 1
            if stable_samples >= 3:
                state["stable_samples"] = stable_samples
                return state
        else:
            previous = None
            stable_samples = 0
        if child_done(pid)[0]:
            raise ReplayFailure(
                f"help-panel-{columns}x{rows}",
                "Hades exited before the resized Help panel stabilized",
                bytes(output),
            )
        select.select([fd], [], [], 0.05)
    read_available(fd, output)
    raise ReplayFailure(
        f"help-panel-{columns}x{rows}",
        f"timed out after {timeout:.1f}s waiting for the resized Help panel",
        bytes(output),
    )


def resize_pty(pid: int, fd: int, slave_path: str, columns: int, rows: int) -> None:
    set_window_size(fd, columns, rows)
    set_slave_window_size(slave_path, columns, rows)
    os.kill(pid, signal.SIGWINCH)


def run_case(binary: Path, timeout: float) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="hades-configured-help-resize-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    slave_path = ""
    reaped = False
    output = bytearray()
    try:
        pid, fd, slave_path = spawn_configured(binary, home)
        wait_for(
            pid,
            fd,
            output,
            "startup",
            lambda text: all(marker_present(text, marker) for marker in MAIN_SURFACE_MARKERS)
            and marker_present(text, "ready"),
            timeout,
        )
        send(fd, b"/help\r")
        observations: list[dict[str, Any]] = []
        for index, (columns, rows) in enumerate(RESIZE_CASES):
            if index:
                resize_pty(pid, fd, slave_path, columns, rows)
            state = wait_for_panel(pid, fd, output, columns, rows, timeout)
            expected = {
                "x": 1,
                "y": rows - 4,
                "width": columns - 2,
                "height": 3,
                "composer_y": rows - 1,
            }
            for key, value in expected.items():
                if state[key] != value:
                    raise ReplayFailure(
                        f"help-panel-{columns}x{rows}",
                        f"observed {key}={state[key]!r}, expected {value!r}",
                        bytes(output),
                    )
            observations.append({"columns": columns, "rows": rows, "panel": state})

        send(fd, b"\x03")
        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
            raise ReplayFailure("cleanup", f"unexpected exit status: {status}", bytes(output))
        flags = terminal_flags(slave_path)
        raw = bytes(output)
        if b"\x1b[?1049l" not in raw or not flags["canonical"] or not flags["echo"]:
            raise ReplayFailure("cleanup-terminal", f"terminal restoration failed: {flags}", raw)
        return {
            "id": "configured-help-resize",
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
            "provider_request": "not observed; configured endpoint was an absent loopback port",
            "side_effects": "Only /help, PTY resize, and bounded Ctrl+C cleanup were exercised; no provider request or external network was used",
            "clean_exit": True,
            "terminal_restored": flags,
        }
    finally:
        if pid != -1:
            stop_process(pid, fd, reaped)
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    binary = args.binary.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0103",
        "contract_observation": "OBS-0102",
        "reference": {
            "product": "Hermes TUI",
            "version": "0.19.1 (2026.7.30)",
            "source_commit": "e444d165807f489b5c1ab8e4a612c8d09c2e67a2",
            "terminal": {
                "initial_columns": COLUMNS,
                "initial_rows": ROWS,
                "resize_cases": ["100x30", "160x50"],
                "emulator": "direct PTY with normalized ANSI screen geometry",
            },
            "capture": "Hades configured /help resize replay against OBS-0102",
        },
        "normalization": [
            "Binary paths, synthetic HOME/HERMES_HOME paths, loopback ports, timestamps, ANSI redraw bytes, and runtime identifiers are omitted or represented by stable markers.",
            "The configured endpoint is an absent loopback port; the replay must not issue a provider request or use credentials.",
            "The oracle checks only the observed Help geometry, composer retention, process liveness, and Ctrl+C terminal cleanup at the three requested sizes.",
            "Minimum-size clipping, focus/navigation, repeated-help behavior, dynamic catalog behavior, and provider behavior remain unknown.",
        ],
        "steps": [],
        "unknowns": [
            "Only the OBS-0102 120x40, 100x30, and 160x50 geometry boundaries are claimed.",
            "No provider request, credential, OAuth flow, external network, or side-effecting command was exercised.",
        ],
        "passed": False,
    }
    try:
        if not binary.is_file():
            raise ReplayFailure("precondition", f"Hades binary does not exist: {binary}")
        result = run_case(binary, args.timeout)
        report["steps"].append(
            {
                "id": result["id"],
                "precondition": "Fresh configured Hades process at 120x40 with an absent loopback endpoint and no credentials.",
                "input_sequence": result["input"],
                "output": result,
            }
        )
        report["passed"] = True
    except (OSError, ReplayFailure, RuntimeError, ValueError) as error:
        report["failure"] = error.as_dict() if isinstance(error, ReplayFailure) else str(error)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized, encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
