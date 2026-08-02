#!/usr/bin/env python3
"""Replay Hades' standalone Full setup continuation and cancellation chain."""

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
    retain_slave_descriptor,
    send,
    set_window_size,
    terminal_flags,
    wait_for,
    wait_for_exit,
)
from probe_hermes_terminal_palette import Screen


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
CONTINUATION_MARKERS = (
    "Configuration Location",
    "Config file:",
    "Secrets file:",
    "Data folder:",
    "Install dir:",
    "Inference Provider",
    "Choose how to connect to your main chat model.",
)
TERMINAL_BACKEND_MARKERS = (
    "Select terminal backend:",
    "Keep current (local)",
)
FALLBACK_MARKERS = (
    "Select terminal backend:",
    "Enter for default (8)",
    "Ctrl+C to exit",
    "Select [1-8] (8):",
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
            os.write(2, f"standalone Full setup replay child failed to start: {error}\n".encode())
            os._exit(127)

    set_window_size(master, COLUMNS, ROWS)
    os.set_blocking(master, False)
    slave_path = os.readlink(f"/proc/{pid}/fd/0")
    retain_slave_descriptor(slave_path)
    return pid, master, slave_path


def rendered_screen(raw: bytes) -> str:
    screen = Screen(columns=COLUMNS, rows=ROWS)
    screen.feed(raw)
    return "\n".join(screen.lines())


def run_case(binary: Path, timeout: float) -> dict[str, object]:
    home = Path(tempfile.mkdtemp(prefix="hades-standalone-full-setup-home-"))
    pid, master, slave_path = spawn_setup(binary, home)
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            master,
            output,
            "standalone Full setup initial surface",
            lambda text: all(marker_present(text, marker) for marker in INITIAL_MARKERS),
            timeout,
        )
        initial_flags = terminal_flags(slave_path)
        if initial_flags["canonical"] or initial_flags["echo"]:
            raise ProbeError(f"initial setup surface did not enter raw mode: {initial_flags}")

        send(master, b"j")
        send(master, b"\r")
        wait_for(
            pid,
            master,
            output,
            "standalone Full setup continuation",
            lambda text: all(marker_present(text, marker) for marker in CONTINUATION_MARKERS),
            timeout,
        )
        continuation_flags = terminal_flags(slave_path)
        config_path = home / "config.yaml"
        if not config_path.is_file():
            raise ProbeError("Full setup did not create the bounded baseline config")
        config_text = config_path.read_text(encoding="utf-8")
        if "mode: full" not in config_text or "provider: unconfigured" not in config_text:
            raise ProbeError("baseline config did not contain the bounded non-secret setup marker")
        if any(secret_marker in config_text.lower() for secret_marker in ("api_key", "oauth", "token")):
            raise ProbeError("baseline config unexpectedly contained a credential-like field")

        send(master, b"\x03")
        wait_for(
            pid,
            master,
            output,
            "standalone Full setup Terminal Backend",
            lambda text: all(marker_present(text, marker) for marker in TERMINAL_BACKEND_MARKERS),
            timeout,
        )
        terminal_backend_flags = terminal_flags(slave_path)
        if "Terminal Backend" not in rendered_screen(bytes(output)):
            raise ProbeError("Terminal Backend title was not visible in the rendered screen")
        if terminal_backend_flags["canonical"] or terminal_backend_flags["echo"]:
            raise ProbeError(
                f"Terminal Backend unexpectedly left raw mode after provider skip: {terminal_backend_flags}"
            )

        send(master, b"\x03")
        wait_for(
            pid,
            master,
            output,
            "standalone Full setup numbered fallback",
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
            raise ProbeError(f"unexpected Full setup cancellation status: {exit_status}")

        raw_output = bytes(output)
        cleanup_flags = terminal_flags(slave_path)
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeError(f"terminal was not restored after Full setup cancellation: {cleanup_flags}")
        cleaned = clean_output(output)
        if "Provider error" in cleaned or "HADES_PROVIDER_BASE_URL" in cleaned:
            raise ProbeError("standalone Full setup unexpectedly started provider behavior")

        return {
            "case": "standalone-full-setup-continuation",
            "arguments": ["setup"],
            "dimensions": {"columns": COLUMNS, "rows": ROWS},
            "startup": {"markers": list(INITIAL_MARKERS), "raw_mode": initial_flags},
            "continuation": {
                "markers": list(CONTINUATION_MARKERS),
                "terminal_flags": continuation_flags,
                "config_created": True,
                "config_non_secret_marker": True,
            },
            "terminal_backend": {
                "markers": list(TERMINAL_BACKEND_MARKERS),
                "terminal_flags": terminal_backend_flags,
            },
            "fallback": {"markers": list(FALLBACK_MARKERS), "terminal_flags": fallback_flags},
            "input": [
                "j",
                "Enter",
                "Ctrl+C (skip provider)",
                "Ctrl+C (open terminal-backend fallback)",
                "Ctrl+C (cancel)",
            ],
            "provider_started": False,
            "credentials_entered": False,
            "oauth_started": False,
            "config_created": config_path.exists(),
            "exit": exit_status,
            "cleanup": {
                "alternate_screen_entered": b"\x1b[?1049h" in raw_output,
                "alternate_screen_left": b"\x1b[?1049l" in raw_output,
                "terminal_flags": cleanup_flags,
                "ctrl_c_presses": 3,
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
        "probe": "hades-standalone-full-setup",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "cases": [],
    }
    if not binary.is_file():
        report.update({"passed": False, "error": "Hades binary not found"})
        return write_report(report, Path(args.report) if args.report else None, 2)

    try:
        report["cases"] = [run_case(binary, args.timeout)]
        report["passed"] = True
    except (OSError, ProbeError) as error:
        report.update({"passed": False, "error": str(error)})
        return write_report(report, Path(args.report) if args.report else None, 1)

    return write_report(report, Path(args.report) if args.report else None, 0)


if __name__ == "__main__":
    raise SystemExit(main())
