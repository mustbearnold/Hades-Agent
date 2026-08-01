#!/usr/bin/env python3
"""Replay Hades' standalone setup entry and bounded cancellation boundary."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from probe_tui_lifecycle import (
    ProbeError,
    clean_output,
    describe_status,
    marker_present,
    send,
    set_window_size,
    terminal_flags,
    wait_for,
    wait_for_exit,
)


COLUMNS = 120
ROWS = 40
INITIAL_MARKERS = (
    "Hermes Agent Setup Wizard",
    "Let's configure your Hermes Agent installation.",
    "Press Ctrl+C at any time to exit.",
    "How would you like to set up Hermes?",
    "Quick Setup (Nous Portal)",
    "Full setup",
    "Blank Slate",
    "ESC cancel",
)
FALLBACK_MARKERS = (
    "How would you like to set up Hermes?",
    "Quick Setup (Nous Portal)",
    "Full setup",
    "Blank Slate",
    "Enter for default (1)",
    "Ctrl+C to exit",
    "Select [1-3] (1):",
)


def spawn_setup(binary: Path, home: Path) -> tuple[int, int, str]:
    import pty

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
            os.execvpe(str(binary), [str(binary), "setup"], environment)
        except BaseException as error:
            os.write(2, f"standalone setup replay child failed to start: {error}\n".encode())
            os._exit(127)

    set_window_size(master, COLUMNS, ROWS)
    os.set_blocking(master, False)
    return pid, master, os.readlink(f"/proc/{pid}/fd/0")


def run_setup_case(binary: Path, timeout: float) -> dict[str, object]:
    home = Path(tempfile.mkdtemp(prefix="hades-standalone-setup-home-"))
    pid, master, slave_path = spawn_setup(binary, home)
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            master,
            output,
            "standalone setup initial surface",
            lambda text: all(marker_present(text, marker) for marker in INITIAL_MARKERS),
            timeout,
        )
        initial_flags = terminal_flags(slave_path)
        if initial_flags["canonical"] or initial_flags["echo"]:
            raise ProbeError(f"initial setup surface did not enter raw mode: {initial_flags}")

        send(master, b"\x1b")
        wait_for(
            pid,
            master,
            output,
            "standalone setup numbered fallback",
            lambda text: all(marker_present(text, marker) for marker in FALLBACK_MARKERS),
            timeout,
        )
        fallback_flags = terminal_flags(slave_path)
        if not fallback_flags["canonical"] or not fallback_flags["echo"]:
            raise ProbeError(f"numbered fallback did not restore terminal flags: {fallback_flags}")

        send(master, b"\x03")
        status = wait_for_exit(pid, master, output, timeout)
        reaped = True
        exit_status = describe_status(status)
        if exit_status != {"kind": "exit", "code": 1}:
            raise ProbeError(f"unexpected standalone setup cancellation status: {exit_status}")

        raw_output = bytes(output)
        cleanup_flags = terminal_flags(slave_path)
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeError(f"terminal was not restored after setup cancellation: {cleanup_flags}")
        cleaned = clean_output(output)
        if "Provider error" in cleaned or "HADES_PROVIDER_BASE_URL" in cleaned:
            raise ProbeError("standalone setup unexpectedly started provider behavior")

        return {
            "case": "standalone-setup-escape-fallback",
            "arguments": ["setup"],
            "dimensions": {"columns": COLUMNS, "rows": ROWS},
            "startup": {"markers": list(INITIAL_MARKERS), "raw_mode": initial_flags},
            "fallback": {"markers": list(FALLBACK_MARKERS), "terminal_flags": fallback_flags},
            "input": ["Escape", "Ctrl+C"],
            "config_created": (home / "config.yaml").exists(),
            "provider_started": False,
            "exit": exit_status,
            "cleanup": {
                "alternate_screen_entered": b"\x1b[?1049h" in raw_output,
                "alternate_screen_left": b"\x1b[?1049l" in raw_output,
                "terminal_flags": cleanup_flags,
            },
            "status": "passed",
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
        "probe": "hades-standalone-setup",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "cases": [],
    }
    if not binary.is_file():
        report.update({"passed": False, "error": "Hades binary not found"})
        return write_report(report, Path(args.report) if args.report else None, 2)

    try:
        report["cases"] = [run_setup_case(binary, args.timeout)]
        report["passed"] = True
    except (OSError, ProbeError) as error:
        report.update({"passed": False, "error": str(error)})
        return write_report(report, Path(args.report) if args.report else None, 1)

    return write_report(report, Path(args.report) if args.report else None, 0)


if __name__ == "__main__":
    raise SystemExit(main())
