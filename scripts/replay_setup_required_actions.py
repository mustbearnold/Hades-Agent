#!/usr/bin/env python3
"""Replay Hades' safe post-delay Setup Required action boundary."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from probe_hermes_terminal_palette import Screen
from probe_tui_lifecycle import (
    ProbeError,
    describe_status,
    marker_present,
    read_available,
    wait_for,
    wait_for_exit,
)
from replay_unconfigured_help import (
    COLUMNS,
    HELP_SETUP_REQUIRED_DELAY_MS,
    STARTUP_MARKERS,
    cleanup_process,
    poll_exit,
    recent_output,
    spawn,
    stable_terminal_flags,
)


ROWS = 40
ACTION_COMMANDS = ("/model", "/setup")
SETUP_MARKERS = ("Setup Required", "/model", "/setup", "Ctrl+C")


def send(master: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(master, view)
        view = view[written:]


def assert_setup_surface(output: bytearray, case: str) -> str:
    text = recent_output(output, lines=64)
    for marker in SETUP_MARKERS:
        if not marker_present(text, marker):
            raise ProbeError(f"{case}: missing Setup Required marker: {marker}")
    for marker in ("Select provider", "Select model", "Hermes Agent Setup Wizard"):
        if marker_present(text, marker):
            raise ProbeError(f"{case}: unexpected actionable surface: {marker}")
    if marker_present(text, "Provider error"):
        raise ProbeError(f"{case}: provider error appeared on the no-provider boundary")
    return text


def latest_screen_text(output: bytearray) -> str:
    screen = Screen(columns=COLUMNS, rows=ROWS)
    screen.feed(bytes(output))
    return "\n".join(screen.lines())


def run_case(binary: Path, command: str | None, timeout: float) -> dict[str, Any]:
    label = "ctrl-c" if command is None else command.removeprefix("/")
    case = f"post-delay-{label}"
    pid, master, slave_path, home = spawn(binary, [])
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            master,
            output,
            f"{case}: startup",
            lambda text: all(marker_present(text, marker) for marker in STARTUP_MARKERS),
            timeout,
        )
        startup_flags = stable_terminal_flags(slave_path)
        if startup_flags["canonical"] or startup_flags["echo"]:
            raise ProbeError(f"{case}: startup did not enter raw mode: {startup_flags}")

        send(master, b"/help\r")
        wait_for(
            pid,
            master,
            output,
            f"{case}: delayed Setup Required",
            lambda text: all(marker_present(recent_output(output), marker) for marker in SETUP_MARKERS),
            max(timeout, 10.0),
        )
        transition_text = assert_setup_surface(output, case)

        if command is not None:
            send(master, f"{command}\r\r".encode())
            time.sleep(0.35)
            read_available(master, output)
            action_text = assert_setup_surface(output, case)
            if marker_present(action_text, f"❯ {command}"):
                raise ProbeError(f"{case}: follow-up command became an active composer draft")
        else:
            action_text = transition_text

        send(master, b"\x03")
        time.sleep(0.15)
        read_available(master, output)
        after_first_ctrl_c = assert_setup_surface(output, case)
        first_exited, first_status = poll_exit(pid)
        if first_exited:
            raise ProbeError(
                f"{case}: first Ctrl+C exited before the bounded second press: {describe_status(first_status or 0)}"
            )
        if marker_present(latest_screen_text(output), "❯ /help"):
            raise ProbeError(f"{case}: first Ctrl+C did not clear the retained /help draft")
        if (home / "config.yaml").exists():
            raise ProbeError(f"{case}: no-provider action created config.yaml")

        send(master, b"\x03")
        status = wait_for_exit(pid, master, output, timeout)
        reaped = True
        exit_status = describe_status(status)
        if exit_status != {"kind": "exit", "code": 0}:
            raise ProbeError(f"{case}: unexpected exit status: {exit_status}")
        cleanup_flags = stable_terminal_flags(slave_path)
        raw = bytes(output)
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeError(f"{case}: terminal was not restored: {cleanup_flags}")
        if b"\x1b[?1049h" not in raw or b"\x1b[?1049l" not in raw:
            raise ProbeError(f"{case}: alternate-screen cleanup was incomplete")
        return {
            "id": case,
            "status": "passed",
            "input": {
                "initial_command": "/help",
                "follow_up_command": command,
                "follow_up_enter_count": 2 if command is not None else 0,
                "cleanup_sequence": ["Ctrl+C", "Ctrl+C"],
            },
            "setup_required": {
                "markers": list(SETUP_MARKERS),
                "follow_up_remained_on_overlay": command is not None,
                "model_picker_visible": False,
                "setup_wizard_visible": False,
                "provider_request_started": False,
                "config_created": False,
            },
            "first_ctrl_c": {
                "process_alive": True,
                "overlay_remained_visible": True,
                "retained_help_draft_cleared": True,
            },
            "cleanup": {
                "exit": exit_status,
                "alternate_screen_left": True,
                "terminal_flags": cleanup_flags,
            },
            "reference_delay_ms": HELP_SETUP_REQUIRED_DELAY_MS,
        }
    finally:
        cleanup_process(pid, master, home, reaped)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path("target/debug/hades"))
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    binary = args.binary.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0105",
        "contract_observation": "OBS-0104",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "cases": [],
        "passed": False,
        "unknowns": [
            "No provider, credential, OAuth, network, model selection, or setup persistence behavior was exercised.",
            "The replay covers only the observed no-provider Setup Required boundary at 120x40.",
        ],
    }
    if not binary.is_file():
        report["error"] = "Hades binary not found"
        serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        print(serialized, end="")
        return 2
    try:
        report["cases"] = [run_case(binary, command, args.timeout) for command in (*ACTION_COMMANDS, None)]
        report["passed"] = True
    except (OSError, ProbeError, ValueError) as error:
        report["error"] = str(error)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized, encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
