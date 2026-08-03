#!/usr/bin/env python3
"""Replay Hades' configured /help Escape lifecycle against OBS-0100."""

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

from replay_configured_help import (
    COLUMNS,
    DEFAULT_BINARY,
    MAIN_SURFACE_MARKERS,
    ROWS,
    help_state,
    screen_lines,
    spawn_configured,
    wait_for_stable_help,
)
from replay_vertical_slice import (
    ReplayFailure,
    child_done,
    clean_output,
    marker_present,
    read_available,
    send,
    stop_process,
    terminal_flags,
    wait_for,
    wait_for_exit,
)


def read_for(pid: int, fd: int, output: bytearray, duration: float) -> None:
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        read_available(fd, output)
        if child_done(pid)[0]:
            return
        select.select([fd], [], [], min(0.05, max(0.0, deadline - time.monotonic())))


def run_case(binary: Path, timeout: float) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="hades-configured-help-lifecycle-"))
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
        before, stable_samples = wait_for_stable_help(pid, fd, output, timeout)
        if not all(
            any(marker in line for line in screen_lines(bytes(output)))
            for marker in MAIN_SURFACE_MARKERS
        ):
            raise ReplayFailure(
                "before-escape surface",
                "stable help surface lost a main marker",
                bytes(output),
            )

        send(fd, b"\x1b")
        read_for(pid, fd, output, 0.5)
        after = help_state(bytes(output))
        if after is None:
            raise ReplayFailure(
                "after-escape help-panel",
                "Escape did not preserve the stable help panel",
                bytes(output),
            )
        if child_done(pid)[0]:
            raise ReplayFailure(
                "after-escape lifecycle",
                "Escape exited the ready Hades process",
                bytes(output),
            )
        if after.get("composer") != "❯ /help":
            raise ReplayFailure(
                "after-escape composer",
                "Escape did not preserve the /help composer",
                bytes(output),
            )

        send(fd, b"\x03")
        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
            raise ReplayFailure("cleanup exit", f"unexpected exit status: {status}", bytes(output))
        flags = terminal_flags(slave_path)
        raw = bytes(output)
        if b"\x1b[?1049l" not in raw or not flags["canonical"] or not flags["echo"]:
            raise ReplayFailure("cleanup terminal", f"terminal restoration failed: {flags}", raw)
        return {
            "id": "configured-help-escape-lifecycle",
            "status": "passed",
            "input": [
                {"kind": "text", "value": "/help", "bytes_hex": "2f 68 65 6c 70"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {"kind": "key", "value": "Escape", "bytes_hex": "1b", "meaning": "safe lifecycle probe"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "bounded cleanup"},
            ],
            "before_escape": {"help_panel": before, "stable_samples": stable_samples, "state": "ready"},
            "after_escape": {
                "help_panel_preserved": True,
                "composer_preserved": True,
                "process_alive_before_cleanup": True,
            },
            "provider_request": "not observed; configured endpoint was an absent loopback port",
            "side_effects": "Only /help, Escape, and bounded Ctrl+C cleanup were exercised; no provider request or external network was used",
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
        "observation_id": "OBS-0101",
        "contract_observation": "OBS-0100",
        "reference": {
            "product": "Hermes TUI",
            "version": "0.19.1 (2026.7.30)",
            "source_commit": "e444d165807f489b5c1ab8e4a612c8d09c2e67a2",
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "emulator": "direct PTY with normalized stable landmarks",
            },
            "capture": "Hades configured /help Escape lifecycle replay against OBS-0100",
        },
        "normalization": [
            "Binary paths, synthetic HOME/HERMES_HOME paths, loopback ports, timestamps, ANSI redraw bytes, and runtime identifiers are omitted or represented by stable markers.",
            "The configured endpoint is an absent loopback port; the replay must not issue a provider request or use credentials.",
            "The oracle checks only the OBS-0100 stable help panel/composer preservation, live process boundary, and Ctrl+C cleanup.",
            "Other focus, navigation, close, repeated-help, catalog, and dynamic inventory behavior remains unknown.",
        ],
        "steps": [],
        "unknowns": [
            "The complete slash-command catalog, aliases, arguments, command-specific state, and help pagination remain unknown.",
            "Provider/tool/skill counts, discovery timing, redraw ordering, and dynamic command inventory remain outside this lifecycle boundary.",
            "Only the observed Escape preservation and Ctrl+C cleanup route are claimed.",
        ],
        "passed": False,
    }
    try:
        if not binary.is_file():
            raise ReplayFailure("precondition", "binary", f"Hades binary does not exist: {binary}")
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
