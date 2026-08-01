#!/usr/bin/env python3
"""Replay Hades draft input and interrupt behavior without a provider."""

from __future__ import annotations

import argparse
import json
import os
import pty
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_tui_lifecycle import (
    ProbeError,
    clean_output,
    describe_status,
    read_available,
    set_window_size,
    terminal_flags,
    marker_present,
    wait_for,
    wait_for_exit,
)


COLUMNS = 120
ROWS = 40
STARTUP_MARKERS = (
    "Hermes Agent",
    "Nous Research",
    "Available Tools",
    "Available Skills",
    "glm-5.2 · Nous Research",
    "starting agent",
)
INPUT_TEXT = "queued hello"


def send(master: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        offset += os.write(master, payload[offset:])


def poll_exit(pid: int) -> tuple[bool, int | None]:
    try:
        waited_pid, status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True, None
    return waited_pid != 0, status if waited_pid else None


def spawn(binary: Path, arguments: list[str]) -> tuple[int, int, str, Path]:
    home = Path(tempfile.mkdtemp(prefix="hades-unconfigured-input-"))
    pid, master = pty.fork()
    if pid == 0:
        try:
            set_window_size(0, COLUMNS, ROWS)
            environment = os.environ.copy()
            environment.update(
                {
                    "TERM": "xterm-256color",
                    "COLUMNS": str(COLUMNS),
                    "LINES": str(ROWS),
                    "HOME": str(home),
                    "HERMES_HOME": str(home),
                }
            )
            for key in (
                "HADES_PROVIDER_BASE_URL",
                "HADES_PROVIDER_API_KEY",
                "HADES_MODEL",
                "OPENAI_BASE_URL",
                "OPENAI_API_KEY",
            ):
                environment.pop(key, None)
            os.execvpe(str(binary), [str(binary), *arguments], environment)
        except BaseException as error:
            os.write(2, f"unconfigured input child failed to start: {error}\n".encode())
            os._exit(127)

    set_window_size(master, COLUMNS, ROWS)
    return pid, master, os.readlink(f"/proc/{pid}/fd/0"), home


def cleanup_process(pid: int, master: int, home: Path, reaped: bool) -> None:
    if not reaped:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
    try:
        os.close(master)
    except OSError:
        pass
    shutil.rmtree(home, ignore_errors=True)


def run_input_case(binary: Path, arguments: list[str], timeout: float) -> dict[str, Any]:
    case = "unconfigured-input"
    pid, master, slave_path, home = spawn(binary, arguments)
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            master,
            output,
            f"{case}: startup",
            lambda text: all(marker in text or "".join(marker.split()) in "".join(text.split()) for marker in STARTUP_MARKERS),
            timeout,
        )
        startup_flags = terminal_flags(slave_path)
        if startup_flags["canonical"] or startup_flags["echo"]:
            raise ProbeError("unconfigured input startup did not enter raw mode")

        send(master, f"{INPUT_TEXT}\r".encode())
        wait_for(
            pid,
            master,
            output,
            f"{case}: draft",
            lambda text: INPUT_TEXT in text,
            timeout,
        )
        time.sleep(0.15)
        read_available(master, output)
        raw_with_draft = clean_output(output)
        if not marker_present(raw_with_draft[-1200:], "❯ queued hello"):
            raise ProbeError("unconfigured input did not render the Hermes composer marker")
        if not marker_present(raw_with_draft, "starting agent") or marker_present(raw_with_draft[-1200:], "─ ready │"):
            raise ProbeError("unconfigured input changed the startup boundary")
        if marker_present(raw_with_draft[-1200:], "Provider error"):
            raise ProbeError("unconfigured input rendered a provider error")

        send(master, b"\x03")
        time.sleep(0.15)
        read_available(master, output)
        raw_after_clear = clean_output(output)[-1200:]
        if not marker_present(raw_after_clear, "starting agent"):
            raise ProbeError("first Ctrl+C left the unconfigured startup surface")
        first_ctrl_c_exited, _ = poll_exit(pid)
        if first_ctrl_c_exited:
            raise ProbeError("first Ctrl+C exited instead of clearing the unconfigured draft")

        send(master, b"\x03")
        status = wait_for_exit(pid, master, output, timeout)
        reaped = True
        exit_status = describe_status(status)
        if exit_status != {"kind": "exit", "code": 0}:
            raise ProbeError(f"unexpected exit status: {exit_status}")
        raw_output = bytes(output)
        cleanup_flags = terminal_flags(slave_path)
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeError(f"terminal was not restored: {cleanup_flags}")
        if b"\x1b[?1049h" not in raw_output or b"\x1b[?1049l" not in raw_output:
            raise ProbeError("alternate-screen cleanup was incomplete")
        return {
            "case": case,
            "arguments": arguments,
            "status": "passed",
            "startup": {
                "markers": list(STARTUP_MARKERS),
                "raw_mode": startup_flags,
                "provider_endpoint": "absent",
            },
            "input": {
                "text": INPUT_TEXT,
                "enter_sent": True,
                "draft_marker": "❯ queued hello",
                "starting_agent_persisted": True,
                "ready_footer": False,
                "provider_error": False,
                "provider_request_started": False,
                "first_ctrl_c_kept_process_alive": True,
                "draft_clear_oracle": "focused app/TUI tests",
            },
            "cleanup": {
                "ctrl_c_presses": 2,
                "exit": exit_status,
                "alternate_screen_left": True,
                "terminal_flags": cleanup_flags,
            },
        }
    finally:
        cleanup_process(pid, master, home, reaped)


def run_empty_case(binary: Path, arguments: list[str], timeout: float) -> dict[str, Any]:
    case = "unconfigured-empty-exit"
    pid, master, slave_path, home = spawn(binary, arguments)
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            master,
            output,
            f"{case}: startup",
            lambda text: marker_present(text, "Hermes Agent") and marker_present(text, "starting agent"),
            timeout,
        )
        startup_flags = terminal_flags(slave_path)
        send(master, b"\x03")
        status = wait_for_exit(pid, master, output, timeout)
        reaped = True
        exit_status = describe_status(status)
        if exit_status != {"kind": "exit", "code": 0}:
            raise ProbeError(f"empty startup had unexpected exit status: {exit_status}")
        raw_output = bytes(output)
        cleanup_flags = terminal_flags(slave_path)
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeError(f"empty startup did not restore terminal: {cleanup_flags}")
        if b"\x1b[?1049l" not in raw_output:
            raise ProbeError("empty startup did not leave the alternate screen")
        return {
            "case": case,
            "arguments": arguments,
            "status": "passed",
            "startup": {"status": "starting agent", "raw_mode": startup_flags},
            "cleanup": {
                "ctrl_c_presses": 1,
                "exit": exit_status,
                "alternate_screen_left": True,
                "terminal_flags": cleanup_flags,
            },
        }
    finally:
        cleanup_process(pid, master, home, reaped)


def write_report(report: dict[str, Any], path: Path | None, code: int) -> int:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path("target/debug/hades"))
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    binary = args.binary.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "probe": "hades-unconfigured-input",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "cases": [],
        "passed": False,
    }
    if not binary.is_file():
        report["error"] = "Hades binary not found"
        return write_report(report, args.report, 2)
    try:
        report["cases"] = [
            run_input_case(binary, [], args.timeout),
            run_empty_case(binary, ["tui"], args.timeout),
        ]
        report["passed"] = True
    except (OSError, ProbeError, ValueError) as error:
        report["error"] = str(error)
        return write_report(report, args.report, 1)
    return write_report(report, args.report, 0)


if __name__ == "__main__":
    raise SystemExit(main())
