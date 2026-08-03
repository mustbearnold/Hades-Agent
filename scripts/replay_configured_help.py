#!/usr/bin/env python3
"""Replay Hades' configured /help panel against the OBS-0098 contract."""

from __future__ import annotations

import argparse
import json
import os
import pty
import select
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_terminal_palette import Screen
from probe_tui_lifecycle import retain_slave_descriptor, slave_path_for_pid
from replay_vertical_slice import (
    COLUMNS,
    DEFAULT_BINARY,
    ROOT,
    ReplayFailure,
    child_done,
    clean_output,
    marker_present,
    read_available,
    send,
    set_window_size,
    stop_process,
    terminal_flags,
    wait_for,
    wait_for_exit,
)


ROWS = 40
HELP_COMMAND = "/help Show available commands"
HELP_TOP_BORDER = f"╔{'═' * 116}╗"
HELP_BOTTOM_BORDER = f"╚{'═' * 116}╝"
MAIN_SURFACE_MARKERS = (
    "Hades Agent",
    "Available Tools",
    "Available Skills",
    "/help for commands",
)


def screen_lines(raw: bytes) -> list[str]:
    screen = Screen(columns=COLUMNS, rows=ROWS)
    screen.feed(raw)
    return [line.rstrip() for line in screen.lines()]


def help_state(raw: bytes) -> dict[str, Any] | None:
    lines = screen_lines(raw)
    command_index = next(
        (index for index, line in enumerate(lines) if "Show available commands" in line),
        None,
    )
    if command_index is None or command_index == 0 or command_index + 1 >= len(lines):
        return None
    top = lines[command_index - 1].strip()
    command = lines[command_index].strip()
    bottom = lines[command_index + 1].strip()
    composer = next((line.strip() for line in lines if "❯ /help" in line), None)
    if top != HELP_TOP_BORDER or bottom != HELP_BOTTOM_BORDER or composer != "❯ /help":
        return None
    return {
        "top_border": top,
        "command": HELP_COMMAND,
        "bottom_border": bottom,
        "composer": composer,
    }


def spawn_configured(binary: Path, home: Path) -> tuple[int, int, str]:
    pid, master = pty.fork()
    if pid == 0:
        try:
            set_window_size(0)
            environment = os.environ.copy()
            environment.update(
                {
                    "TERM": "xterm-256color",
                    "COLUMNS": str(COLUMNS),
                    "LINES": str(ROWS),
                    "HOME": str(home),
                    "HERMES_HOME": str(home),
                    "HADES_PROVIDER_BASE_URL": "http://127.0.0.1:1/v1",
                    "HADES_MODEL": "help-model",
                }
            )
            environment.pop("HADES_PROVIDER_API_KEY", None)
            os.execve(str(binary), [str(binary)], environment)
        except BaseException as error:
            os.write(2, f"configured-help child failed to start: {error}\n".encode())
            os._exit(127)
    set_window_size(master)
    os.set_blocking(master, False)
    slave_path = slave_path_for_pid(pid)
    retain_slave_descriptor(slave_path)
    return pid, master, slave_path


def wait_for_stable_help(
    pid: int, fd: int, output: bytearray, timeout: float
) -> tuple[dict[str, Any], int]:
    deadline = time.monotonic() + timeout
    previous: str | None = None
    stable_samples = 0
    while time.monotonic() < deadline:
        read_available(fd, output)
        state = help_state(bytes(output))
        if state is not None:
            signature = json.dumps(state, ensure_ascii=False, sort_keys=True)
            if signature == previous:
                stable_samples += 1
            else:
                previous = signature
                stable_samples = 1
            if stable_samples >= 3:
                return state, stable_samples
        else:
            previous = None
            stable_samples = 0
        done, _ = child_done(pid)
        if done:
            raise ReplayFailure(
                "configured-help-panel",
                "Hades exited before the help panel stabilized",
                bytes(output),
            )
        select.select([fd], [], [], 0.05)
    raise ReplayFailure(
        "configured-help-panel",
        f"timed out after {timeout:.1f}s waiting for the exact help panel",
        bytes(output),
    )


def run_case(binary: Path, timeout: float) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="hades-configured-help-"))
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
            lambda text: marker_present(text, "Hades Agent") and marker_present(text, "ready"),
            timeout,
        )
        send(fd, b"/help\r")
        panel, stable_samples = wait_for_stable_help(pid, fd, output, timeout)
        lines = screen_lines(bytes(output))
        for marker in MAIN_SURFACE_MARKERS:
            if not any(marker_present(line, marker) for line in lines):
                raise ReplayFailure("configured-help-panel", f"missing stable marker: {marker}")
        if any(marker_present(line, "Setup Required") for line in lines):
            raise ReplayFailure("configured-help-panel", "configured /help entered setup-required state")
        send(fd, b"\x03")
        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
            raise ReplayFailure("cleanup", f"unexpected exit status: {status}", bytes(output))
        raw = bytes(output)
        flags = terminal_flags(slave_path)
        if b"\x1b[?1049l" not in raw or not flags["canonical"] or not flags["echo"]:
            raise ReplayFailure("cleanup", f"terminal restoration failed: {flags}", raw)
        return {
            "id": "configured-help-panel",
            "status": "passed",
            "input": [
                {"kind": "text", "value": "/help", "bytes_hex": "2f 68 65 6c 70"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "bounded cleanup"},
            ],
            "main_surface_markers": list(MAIN_SURFACE_MARKERS),
            "help_panel": panel,
            "stable_samples": stable_samples,
            "state": "configured ready state; the bottom help panel covers the visible ready footer",
            "provider_request": "not observed; configured endpoint was an absent loopback port",
            "side_effects": "No provider request, credential, OAuth flow, external network, or other slash command was exercised",
            "clean_exit": True,
            "terminal_restored": flags,
        }
    finally:
        if pid != -1:
            stop_process(pid, fd, reaped)
        shutil.rmtree(root, ignore_errors=True)


def safe_failure(error: BaseException) -> dict[str, Any] | str:
    if not isinstance(error, ReplayFailure):
        return str(error)
    details: dict[str, Any] = error.as_dict()
    details["screen_tail"] = clean_output(error.output)[-2000:]
    return details


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    binary = args.binary.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0099",
        "contract_observation": "OBS-0098",
        "reference": {
            "product": "Hermes TUI",
            "version": "0.19.1 (2026.7.30)",
            "source_commit": "e444d165807f489b5c1ab8e4a612c8d09c2e67a2",
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "emulator": "direct PTY with normalized stable landmarks",
            },
            "capture": "Hades configured /help replay against the OBS-0098 stable panel contract",
        },
        "normalization": [
            "Binary paths, synthetic HOME/HERMES_HOME paths, loopback ports, timestamps, ANSI redraw bytes, and runtime identifiers are omitted or represented by stable markers.",
            "The configured provider endpoint is an absent loopback port; the replay uses no credential and must not issue a provider request.",
            "The implementation oracle checks only the OBS-0098 stable bordered command row, main-surface landmarks, ready state, composer, and terminal cleanup.",
            "The complete slash-command catalog, aliases, arguments, dynamic inventories, and command-specific behavior remain outside this replay.",
        ],
        "steps": [],
        "unknowns": [
            "The complete slash-command catalog, aliases, arguments, command-specific state, and help pagination remain unknown.",
            "Provider/tool/skill counts, discovery timing, redraw ordering, and dynamic command inventory remain outside the stable help-panel contract.",
            "Escape-to-close is an implementation convenience; only the observed Ctrl+C cleanup route is claimed by this replay.",
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
        report["failure"] = safe_failure(error)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized, encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
