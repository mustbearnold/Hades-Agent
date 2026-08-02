#!/usr/bin/env python3
"""Replay the supported no-argument and explicit-tui Hades launch forms."""

from __future__ import annotations

import argparse
import json
import os
import pty
import shutil
import tempfile
from pathlib import Path

from probe_tui_lifecycle import (
    ProbeError,
    describe_status,
    retain_slave_descriptor,
    slave_path_for_pid,
    set_window_size,
    terminal_flags,
    wait_for,
    wait_for_exit,
)


def spawn(binary: Path, arguments: list[str]) -> tuple[int, int, str, Path]:
    history_home = Path(tempfile.mkdtemp(prefix="hades-launch-history-"))
    pid, master = pty.fork()
    if pid == 0:
        try:
            set_window_size(0, 120, 40)
            os.environ["TERM"] = "xterm-256color"
            os.environ["COLUMNS"] = "120"
            os.environ["LINES"] = "40"
            os.environ["HERMES_HOME"] = str(history_home)
            os.execv(str(binary), [str(binary), *arguments])
        except BaseException as error:
            os.write(2, f"launch replay child failed to start: {error}\n".encode())
            os._exit(127)

    set_window_size(master, 120, 40)
    slave_path = slave_path_for_pid(pid)
    retain_slave_descriptor(slave_path)
    return pid, master, slave_path, history_home


def run_case(binary: Path, name: str, arguments: list[str], timeout: float) -> dict[str, object]:
    pid, master, slave_path, history_home = spawn(binary, arguments)
    output = bytearray()
    reaped = False
    try:
        startup_markers = ("Hermes Agent", "Nous Research", "Available Tools", "Available Skills")
        wait_for(
            pid,
            master,
            output,
            f"{name}: startup",
            lambda text: all(marker in text for marker in startup_markers),
            timeout,
        )
        startup_flags = terminal_flags(slave_path)
        if startup_flags["canonical"] or startup_flags["echo"]:
            raise ProbeError(f"{name}: startup did not enter raw mode: {startup_flags}")

        os.write(master, b"\x03")
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
            "arguments": arguments,
            "startup": {"landmarks": list(startup_markers), "raw_mode": startup_flags},
            "exit": exit_status,
            "cleanup": {
                "input": "Ctrl+C",
                "alternate_screen_left": True,
                "terminal_flags": cleanup_flags,
            },
        }
    finally:
        if not reaped:
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        os.close(master)
        shutil.rmtree(history_home, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default="target/debug/hades")
    parser.add_argument("--report")
    parser.add_argument("--timeout", type=float, default=5.0)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    binary = Path(arguments.binary).resolve()
    report_path = Path(arguments.report) if arguments.report else None
    report: dict[str, object] = {
        "probe": "hades-cli-launch",
        "binary": str(binary),
        "dimensions": {"columns": 120, "rows": 40},
        "cases": [],
    }
    if not binary.is_file():
        report.update({"passed": False, "error": f"binary not found: {binary}"})
        return write_report(report, report_path, 2)

    try:
        report["cases"] = [
            run_case(binary, "default-tui", [], arguments.timeout),
            run_case(binary, "explicit-tui", ["tui"], arguments.timeout),
        ]
        report["passed"] = True
    except (OSError, ProbeError) as error:
        report.update({"passed": False, "error": str(error)})
        return write_report(report, report_path, 1)

    return write_report(report, report_path, 0)


def write_report(report: dict[str, object], path: Path | None, status: int) -> int:
    text = json.dumps(report, indent=2, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
