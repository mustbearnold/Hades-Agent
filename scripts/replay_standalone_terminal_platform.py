#!/usr/bin/env python3
"""Replay Hades' standalone terminal-backend and platform cancellation boundary."""

from __future__ import annotations

import argparse
import json
import os
import pty
import shutil
import tempfile
import time
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
PLATFORM_MARKERS = (
    "Mattermost",
    "Signal",
    "WhatsApp",
    "(not configured)",
)
TOOL_CONFIGURATION_MARKERS = (
    "No platforms selected. Run 'hermes setup gateway' later to configure.",
    "Hermes Tool Configuration",
    "Enable or disable tools per platform.",
    "Tools that need API keys will be configured when enabled.",
)


def spawn_setup(binary: Path, home: Path) -> tuple[int, int, str]:
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
            os.write(2, f"standalone terminal/platform replay child failed: {error}\n".encode())
            os._exit(127)

    set_window_size(master, COLUMNS, ROWS)
    os.set_blocking(master, False)
    return pid, master, os.readlink(f"/proc/{pid}/fd/0")


def config_shape(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"exists": False, "bytes": 0}
    text = path.read_text(encoding="utf-8")
    return {
        "exists": True,
        "bytes": len(text.encode("utf-8")),
        "contains_non_secret_baseline": "mode: full" in text and "provider: unconfigured" in text,
        "contains_credential_like_field": any(
            marker in text.lower() for marker in ("api_key", "oauth", "token")
        ),
    }


def run_case(binary: Path, timeout: float) -> dict[str, object]:
    home = Path(tempfile.mkdtemp(prefix="hades-standalone-terminal-platform-home-"))
    pid, master, slave_path = spawn_setup(binary, home)
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            master,
            output,
            "standalone terminal/platform initial surface",
            lambda text: all(marker_present(text, marker) for marker in INITIAL_MARKERS),
            timeout,
        )
        initial_flags = terminal_flags(slave_path)
        if initial_flags["canonical"] or initial_flags["echo"]:
            raise ProbeError(f"initial setup surface did not enter raw mode: {initial_flags}")
        config_before = config_shape(home / "config.yaml")

        send(master, b"j\r")
        wait_for(
            pid,
            master,
            output,
            "standalone Full setup continuation",
            lambda text: all(marker_present(text, marker) for marker in CONTINUATION_MARKERS),
            timeout,
        )
        continuation_flags = terminal_flags(slave_path)
        config_at_continuation = config_shape(home / "config.yaml")

        send(master, b"\x03")
        wait_for(
            pid,
            master,
            output,
            "standalone terminal backend",
            lambda text: all(marker_present(text, marker) for marker in TERMINAL_BACKEND_MARKERS),
            timeout,
        )
        terminal_backend_flags = terminal_flags(slave_path)
        if terminal_backend_flags["canonical"] or terminal_backend_flags["echo"]:
            raise ProbeError(
                "provider cancellation unexpectedly restored terminal flags: "
                f"{terminal_backend_flags}"
            )

        send(master, b"\r")
        wait_for(
            pid,
            master,
            output,
            "standalone platform picker",
            lambda text: all(marker_present(text, marker) for marker in PLATFORM_MARKERS),
            timeout,
        )
        platform_flags = terminal_flags(slave_path)
        leaves_before_cancel = bytes(output).count(b"\x1b[?1049l")

        send(master, b"\x03")
        wait_for(
            pid,
            master,
            output,
            "standalone tool configuration boundary",
            lambda text: all(marker_present(text, marker) for marker in TOOL_CONFIGURATION_MARKERS),
            timeout,
        )
        first_cancel_flags = terminal_flags(slave_path)
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done:
            raise ProbeError("first platform Ctrl+C unexpectedly exited the setup process")
        leaves_after_first_cancel = bytes(output).count(b"\x1b[?1049l")
        if leaves_after_first_cancel <= leaves_before_cancel:
            raise ProbeError("first platform Ctrl+C did not leave the alternate screen")

        send(master, b"\x03")
        status = wait_for_exit(pid, master, output, timeout)
        reaped = True
        exit_status = describe_status(status)
        if exit_status != {"kind": "exit", "code": 130}:
            raise ProbeError(f"unexpected second Ctrl+C status: {exit_status}")
        cleanup_flags = terminal_flags(slave_path)
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeError(f"terminal was not restored after cleanup: {cleanup_flags}")

        config_after = config_shape(home / "config.yaml")
        if config_after != config_at_continuation:
            raise ProbeError("platform cancellation changed the bounded setup config")
        if (home / ".env").exists():
            raise ProbeError("platform cancellation created a secrets file")
        cleaned = clean_output(output)
        if "Provider error" in cleaned or "HADES_PROVIDER_BASE_URL" in cleaned:
            raise ProbeError("standalone platform boundary unexpectedly started provider behavior")

        return {
            "case": "standalone-terminal-platform-boundary",
            "arguments": ["setup"],
            "dimensions": {"columns": COLUMNS, "rows": ROWS},
            "startup": {"markers": list(INITIAL_MARKERS), "terminal_flags": initial_flags},
            "continuation": {
                "markers": list(CONTINUATION_MARKERS),
                "terminal_flags": continuation_flags,
                "config": config_at_continuation,
            },
            "terminal_backend": {
                "markers": list(TERMINAL_BACKEND_MARKERS),
                "terminal_flags": terminal_backend_flags,
            },
            "platform_picker": {
                "markers": list(PLATFORM_MARKERS),
                "terminal_flags": platform_flags,
            },
            "tool_configuration_after_platform_cancel": {
                "markers": list(TOOL_CONFIGURATION_MARKERS),
                "terminal_flags": first_cancel_flags,
                "process_still_alive": True,
            },
            "cancellation": {
                "input": [
                    "j",
                    "Enter",
                    "Ctrl+C (skip provider)",
                    "Enter (accept Keep current local backend)",
                    "Ctrl+C (leave platform picker)",
                    "Ctrl+C (SIGINT cleanup)",
                ],
                "first_ctrl_c_alternate_screen_left": True,
                "second_ctrl_c_exit": exit_status,
                "alternate_screen_entered": b"\x1b[?1049h" in bytes(output),
                "alternate_screen_left": b"\x1b[?1049l" in bytes(output),
                "terminal_flags": cleanup_flags,
                "credentials_entered": False,
                "oauth_started": False,
                "network_requested": False,
            },
            "persistence": {
                "config_before": config_before,
                "config_after": config_after,
                "config_unchanged_after_platform_cancel": config_after == config_at_continuation,
                "secrets_file_created": False,
            },
            "provider_started": False,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default="target/debug/hades")
    parser.add_argument("--report")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    binary = Path(args.binary).resolve()
    report: dict[str, object] = {
        "probe": "hades-standalone-terminal-platform",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "cases": [],
    }
    if not binary.is_file():
        report.update({"passed": False, "error": "Hades binary not found"})
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2

    try:
        report["cases"] = [run_case(binary, args.timeout)]
        report["passed"] = True
    except (OSError, ProbeError) as error:
        report.update({"passed": False, "error": str(error)})
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
