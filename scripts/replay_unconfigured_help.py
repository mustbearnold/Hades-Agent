#!/usr/bin/env python3
"""Replay Hades' delayed unconfigured /help setup-required route."""

from __future__ import annotations

import argparse
import json
import os
import pty
import shutil
import tempfile
import termios
import time
from pathlib import Path
from typing import Any

from probe_tui_lifecycle import (
    ProbeError,
    clean_output,
    describe_status,
    marker_present,
    read_available,
    retain_slave_descriptor,
    slave_path_for_pid,
    set_window_size,
    terminal_flags,
    wait_for,
    wait_for_exit,
)


COLUMNS = 120
ROWS = 40
HELP_SETUP_REQUIRED_DELAY_MS = 8_000
STARTUP_MARKERS = (
    "Hermes Agent",
    "Nous Research",
    "Available Tools",
    "Available Skills",
    "glm-5.2 · Nous Research",
    "starting agent",
)


def send(master: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(master, view)
        view = view[written:]


def poll_exit(pid: int) -> tuple[bool, int | None]:
    try:
        waited_pid, status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True, None
    return waited_pid != 0, status if waited_pid else None


def spawn(binary: Path, arguments: list[str]) -> tuple[int, int, str, Path]:
    home = Path(tempfile.mkdtemp(prefix="hades-unconfigured-help-"))
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
            os.write(2, f"unconfigured help child failed to start: {error}\n".encode())
            os._exit(127)

    set_window_size(master, COLUMNS, ROWS)
    slave_path = slave_path_for_pid(pid)
    retain_slave_descriptor(slave_path)
    return pid, master, slave_path, home


def recent_output(output: bytearray, lines: int = 48) -> str:
    return "\n".join(clean_output(output).splitlines()[-lines:])


def stable_terminal_flags(slave_path: str) -> dict[str, bool]:
    """Read PTY state across the short post-exec ioctl race seen on release runs."""
    last_error: termios.error | None = None
    for _ in range(20):
        try:
            return terminal_flags(slave_path)
        except termios.error as error:
            if not error.args or error.args[0] != 25:
                raise
            last_error = error
            time.sleep(0.01)
    raise ProbeError(f"terminal flags stayed unavailable: {last_error}")


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


def run_case(binary: Path, arguments: list[str], timeout: float) -> dict[str, Any]:
    case = "explicit-tui" if arguments else "default-tui"
    pid, master, slave_path, home = spawn(binary, arguments)
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
        submitted_at = time.monotonic()
        wait_for(
            pid,
            master,
            output,
            f"{case}: retained help input",
            lambda text: marker_present(text, "/help")
            and marker_present(text, "starting agent")
            and not marker_present(recent_output(output), "Setup Required"),
            min(timeout, 3.0),
        )
        time.sleep(0.5)
        read_available(master, output)
        before_delay = recent_output(output)
        before_delay_ms = round((time.monotonic() - submitted_at) * 1000)
        if before_delay_ms >= HELP_SETUP_REQUIRED_DELAY_MS:
            raise ProbeError(f"{case}: pre-delay assertion ran too late: {before_delay_ms} ms")
        if not marker_present(before_delay, "/help"):
            raise ProbeError(f"{case}: /help draft was not visible before the deadline")
        if not marker_present(before_delay, "starting agent"):
            raise ProbeError(f"{case}: starting-agent surface was not retained before the deadline")
        if marker_present(before_delay, "Setup Required"):
            raise ProbeError(f"{case}: Setup Required appeared before the deadline")

        wait_for(
            pid,
            master,
            output,
            f"{case}: delayed setup-required overlay",
            lambda text: all(
                marker_present(recent_output(output), marker)
                for marker in ("Setup Required", "/model", "/setup", "Ctrl+C")
            ),
            timeout,
        )
        transition_ms = round((time.monotonic() - submitted_at) * 1000)
        after_delay = recent_output(output)
        if not 7_000 <= transition_ms <= 11_000:
            raise ProbeError(f"{case}: delayed transition outside bounded timing: {transition_ms} ms")
        if marker_present(after_delay, "Provider error") or marker_present(after_delay, "─ ready │"):
            raise ProbeError(f"{case}: delayed route left the unconfigured startup boundary")
        if (home / "config.yaml").exists():
            raise ProbeError(f"{case}: delayed route created config.yaml")

        send(master, b"\x03")
        time.sleep(0.15)
        read_available(master, output)
        after_clear = recent_output(output)
        if not marker_present(after_clear, "Setup Required"):
            raise ProbeError(f"{case}: first Ctrl+C removed the setup-required overlay")
        first_ctrl_c_exited, _ = poll_exit(pid)
        if first_ctrl_c_exited:
            raise ProbeError(f"{case}: first Ctrl+C exited instead of clearing the draft")

        send(master, b"\x03")
        status = wait_for_exit(pid, master, output, timeout)
        reaped = True
        exit_status = describe_status(status)
        if exit_status != {"kind": "exit", "code": 0}:
            raise ProbeError(f"{case}: unexpected exit status: {exit_status}")
        raw_output = bytes(output)
        cleanup_flags = stable_terminal_flags(slave_path)
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeError(f"{case}: terminal was not restored: {cleanup_flags}")
        if b"\x1b[?1049h" not in raw_output or b"\x1b[?1049l" not in raw_output:
            raise ProbeError(f"{case}: alternate-screen cleanup was incomplete")
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
                "command": "/help",
                "enter_sent": True,
                "pre_delay_ms": before_delay_ms,
                "setup_required_delay_ms": HELP_SETUP_REQUIRED_DELAY_MS,
                "observed_transition_ms": transition_ms,
                "draft_marker": "/help visible in the pre-delay PTY stream",
                "starting_agent_before_delay": True,
                "setup_required_markers": ["Setup Required", "/model", "/setup", "Ctrl+C"],
                "provider_request_started": False,
                "config_created": False,
                "first_ctrl_c_kept_process_alive": True,
                "first_ctrl_c_cleared_draft": "focused app/TUI oracle",
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
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()
    binary = args.binary.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0067",
        "probe": "hades-unconfigured-help-setup-required",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "delay_ms": HELP_SETUP_REQUIRED_DELAY_MS,
        "cases": [],
        "passed": False,
    }
    if not binary.is_file():
        report["error"] = "Hades binary not found"
        return write_report(report, args.report, 2)
    try:
        report["cases"] = [
            run_case(binary, [], args.timeout),
            run_case(binary, ["tui"], args.timeout),
        ]
        report["passed"] = True
    except (OSError, ProbeError, ValueError) as error:
        report["error"] = str(error)
        return write_report(report, args.report, 1)
    return write_report(report, args.report, 0)


if __name__ == "__main__":
    raise SystemExit(main())
