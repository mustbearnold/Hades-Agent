#!/usr/bin/env python3
"""Replay Hades' no-provider startup boundary through a direct PTY."""

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
    clean_output,
    describe_status,
    marker_present,
    retain_slave_descriptor,
    slave_path_for_pid,
    set_window_size,
    terminal_flags,
    wait_for,
    wait_for_exit,
)


COLUMNS = 120
ROWS = 40
STARTUP_MARKERS = (
    "Hades Agent",
    "Underworld",
    "Available Tools",
    "Available Skills",
    "glm-5.2 · Hades",
    "starting agent",
)


def spawn(binary: Path, arguments: list[str]) -> tuple[int, int, str, Path]:
    home = Path(tempfile.mkdtemp(prefix="hades-unconfigured-startup-"))
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
            os.write(2, f"unconfigured startup child failed to start: {error}\n".encode())
            os._exit(127)

    set_window_size(master, COLUMNS, ROWS)
    slave_path = slave_path_for_pid(pid)
    retain_slave_descriptor(slave_path)
    return pid, master, slave_path, home


def run_case(binary: Path, name: str, arguments: list[str], timeout: float) -> dict[str, object]:
    pid, master, slave_path, home = spawn(binary, arguments)
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            master,
            output,
            f"{name}: startup",
            lambda text: all(marker_present(text, marker) for marker in STARTUP_MARKERS),
            timeout,
        )
        startup_text = clean_output(bytes(output))
        if marker_present(startup_text, "─ ready │"):
            raise ProbeError(f"{name}: unconfigured startup rendered a ready footer")
        if "<prompt-placeholder>" in startup_text:
            raise ProbeError(f"{name}: unconfigured startup rendered a prompt placeholder")
        if marker_present(startup_text, "mock model") or marker_present(startup_text, "mock-model"):
            raise ProbeError(f"{name}: unconfigured startup rendered the configured mock model")

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
            "startup": {
                "landmarks": list(STARTUP_MARKERS),
                "model_provider": "glm-5.2 · Hades",
                "status": "starting agent",
                "ready_footer": False,
                "prompt_placeholder": False,
                "provider_endpoint": "absent",
                "raw_mode": startup_flags,
            },
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
        shutil.rmtree(home, ignore_errors=True)


def write_report(report: dict[str, object], path: Path | None, status: int) -> int:
    text = json.dumps(report, indent=2, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default="target/debug/hades")
    parser.add_argument("--report")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    binary = Path(args.binary).resolve()
    report: dict[str, object] = {
        "probe": "hades-unconfigured-startup",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "cases": [],
    }
    if not binary.is_file():
        report.update({"passed": False, "error": "Hades binary not found"})
        return write_report(report, Path(args.report) if args.report else None, 2)

    try:
        report["cases"] = [
            run_case(binary, "default-tui", [], args.timeout),
            run_case(binary, "explicit-tui", ["tui"], args.timeout),
        ]
        report["passed"] = True
    except (OSError, ProbeError) as error:
        report.update({"passed": False, "error": str(error)})
        return write_report(report, Path(args.report) if args.report else None, 1)

    return write_report(report, Path(args.report) if args.report else None, 0)


if __name__ == "__main__":
    raise SystemExit(main())
