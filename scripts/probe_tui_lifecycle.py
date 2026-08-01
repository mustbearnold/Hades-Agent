#!/usr/bin/env python3
"""Probe Hades terminal ownership through a real pseudo-terminal."""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import pty
import re
import select
import signal
import struct
import sys
import termios
import time
from pathlib import Path
from typing import Callable


TIOCSWINSZ = getattr(termios, "TIOCSWINSZ", 0x5414)
ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
Predicate = Callable[[str], bool]


class ProbeError(RuntimeError):
    """Raised when a lifecycle assertion fails."""


def set_window_size(fd: int, columns: int, rows: int) -> None:
    fcntl.ioctl(fd, TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))


def set_slave_window_size(slave_path: str, columns: int, rows: int) -> None:
    slave = os.open(slave_path, os.O_RDWR | os.O_NOCTTY)
    try:
        set_window_size(slave, columns, rows)
    finally:
        os.close(slave)


def read_available(master: int, output: bytearray) -> None:
    while True:
        readable, _, _ = select.select([master], [], [], 0)
        if not readable:
            return
        try:
            chunk = os.read(master, 65_536)
        except OSError as error:
            if error.errno == errno.EIO:
                return
            raise
        if not chunk:
            return
        output.extend(chunk)


def clean_output(output: bytearray) -> str:
    text = bytes(output).decode("utf-8", errors="replace").replace("\r", "")
    return ANSI_ESCAPE.sub("", text)


def output_tail(output: bytearray) -> str:
    return "\n".join(clean_output(output).splitlines()[-12:])


def wait_for(
    pid: int,
    master: int,
    output: bytearray,
    description: str,
    predicate: Predicate,
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        read_available(master, output)
        cleaned = clean_output(output)
        if predicate(cleaned):
            return
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            raise ProbeError(
                f"{description}: process exited early with {describe_status(status)}\n"
                f"{output_tail(output)}"
            )
        remaining = deadline - time.monotonic()
        if remaining > 0:
            select.select([master], [], [], min(0.05, remaining))
    read_available(master, output)
    raise ProbeError(f"{description}: timed out\n{output_tail(output)}")


def wait_for_exit(pid: int, master: int, output: bytearray, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        read_available(master, output)
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            for _ in range(5):
                read_available(master, output)
                time.sleep(0.01)
            return status
        remaining = deadline - time.monotonic()
        if remaining > 0:
            select.select([master], [], [], min(0.05, remaining))
    raise ProbeError(f"process did not exit within {timeout:.1f}s\n{output_tail(output)}")


def send(master: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(master, view)
        view = view[written:]


def spawn(binary: Path, columns: int, rows: int) -> tuple[int, int, str]:
    pid, master = pty.fork()
    if pid == 0:
        try:
            set_window_size(0, columns, rows)
            os.environ["TERM"] = "xterm-256color"
            os.environ["COLUMNS"] = str(columns)
            os.environ["LINES"] = str(rows)
            os.execv(str(binary), [str(binary)])
        except BaseException as error:
            os.write(2, f"probe child failed to start: {error}\n".encode())
            os._exit(127)

    set_window_size(master, columns, rows)
    return pid, master, os.readlink(f"/proc/{pid}/fd/0")


def terminal_flags(slave_path: str) -> dict[str, bool]:
    slave = os.open(slave_path, os.O_RDWR | os.O_NOCTTY)
    try:
        attributes = termios.tcgetattr(slave)
    finally:
        os.close(slave)
    local_flags = attributes[3]
    return {
        "canonical": bool(local_flags & termios.ICANON),
        "echo": bool(local_flags & termios.ECHO),
    }


def describe_status(status: int) -> dict[str, int | str]:
    if os.WIFEXITED(status):
        return {"kind": "exit", "code": os.WEXITSTATUS(status)}
    if os.WIFSIGNALED(status):
        return {"kind": "signal", "number": os.WTERMSIG(status)}
    return {"kind": "other", "raw": status}


def run_case(
    binary: Path,
    name: str,
    exit_key: bytes,
    *,
    submit_before_exit: bool,
    resize_before_exit: bool,
    timeout: float,
) -> dict[str, object]:
    pid, master, slave_path = spawn(binary, 80, 24)
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            master,
            output,
            f"{name}: startup",
            lambda text: all(
                marker in text
                for marker in (
                    "HADES AGENT",
                    "session",
                    "transcript",
                    "input",
                )
            ),
            timeout,
        )
        startup_flags = terminal_flags(slave_path)
        if startup_flags["canonical"] or startup_flags["echo"]:
            raise ProbeError(f"{name}: startup did not enter raw mode: {startup_flags}")

        resized = False
        if resize_before_exit:
            set_slave_window_size(slave_path, 100, 30)
            wait_for(
                pid,
                master,
                output,
                f"{name}: resize",
                lambda text: "Terminal size: 100x30." in text,
                timeout,
            )
            resized = True

        submitted = False
        if submit_before_exit:
            send(master, b"hello")
            wait_for(
                pid,
                master,
                output,
                f"{name}: text input",
                lambda text: "Editing input." in text,
                timeout,
            )
            send(master, b"\r")
            wait_for(
                pid,
                master,
                output,
                f"{name}: submit",
                lambda text: "response adapter not connected." in text,
                timeout,
            )
            submitted = True

        send(master, exit_key)
        status = wait_for_exit(pid, master, output, timeout)
        reaped = True
        exit_status = describe_status(status)
        if exit_status != {"kind": "exit", "code": 0}:
            raise ProbeError(f"{name}: unexpected exit status: {exit_status}")

        raw_output = bytes(output)
        if b"\x1b[?1049h" not in raw_output:
            raise ProbeError(f"{name}: alternate-screen enter sequence was not observed")
        if b"\x1b[?1049l" not in raw_output:
            raise ProbeError(f"{name}: alternate-screen leave sequence was not observed")

        cleanup_flags = terminal_flags(slave_path)
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeError(f"{name}: terminal was not restored: {cleanup_flags}")

        return {
            "case": name,
            "startup": {
                "frame_landmarks": [
                    "HADES AGENT",
                    "session",
                    "transcript",
                    "input",
                ],
                "raw_mode": startup_flags,
                "alternate_screen_entered": True,
            },
            "interaction": {
                "resized": resized,
                "submitted": submitted,
                "exit_input": exit_key.decode("ascii", errors="replace"),
            },
            "exit": exit_status,
            "cleanup": {
                "alternate_screen_left": True,
                "cursor_restore_observed": b"\x1b[?25h" in raw_output,
                "terminal_flags": cleanup_flags,
            },
        }
    finally:
        if not reaped:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        os.close(master)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--binary",
        default="target/debug/hades",
        help="path to the already-built Hades binary (default: target/debug/hades)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="seconds allowed for each lifecycle assertion (default: 5)",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    binary = Path(arguments.binary).resolve()
    if not binary.is_file():
        print(json.dumps({"passed": False, "error": f"binary not found: {binary}"}))
        return 2

    try:
        cases = [
            run_case(
                binary,
                "normal-exit",
                b"q",
                submit_before_exit=False,
                resize_before_exit=True,
                timeout=arguments.timeout,
            ),
            run_case(
                binary,
                "interrupt-exit",
                b"\x03",
                submit_before_exit=True,
                resize_before_exit=False,
                timeout=arguments.timeout,
            ),
        ]
    except (OSError, ProbeError) as error:
        print(
            json.dumps(
                {"probe": "hades-tui-lifecycle", "passed": False, "error": str(error)},
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "probe": "hades-tui-lifecycle",
                "passed": True,
                "cases": cases,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
