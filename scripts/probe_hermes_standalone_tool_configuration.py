#!/usr/bin/env python3
"""Capture Hermes standalone setup's bounded Tool Configuration action boundary."""

from __future__ import annotations

import argparse
import errno
import json
import os
import select
import signal
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_standalone_terminal_platform import (
    CONTINUATION_MARKERS,
    DEFAULT_REFERENCE,
    INITIAL_MARKERS,
    PLATFORM_MARKERS,
    SOURCE_COMMIT,
    artifact_classes,
    config_shape,
    file_inventory,
    safe_tail,
    spawn_setup,
    wait_for_rendered,
)
from probe_hermes_terminal_palette import child_status, write_bytes
from probe_tui_lifecycle import describe_status, terminal_flags


COLUMNS = 120
ROWS = 40
BACKEND_MARKERS = ("Select terminal backend:", "Keep current (local)")
TOOL_CONFIGURATION_MARKERS = (
    "No platforms selected. Run 'hermes setup gateway' later to configure.",
    "Hermes Tool Configuration",
    "Enable or disable tools per platform.",
    "Tools that need API keys will be configured when enabled.",
)
SAFE_ACTION_CANDIDATES = (
    "Tools for 🖥️  CLI",
    "SPACE toggle",
    "ENTER confirm",
    "ESC cancel",
    "Web Search & Scraping",
    "Browser Automation",
    "Terminal & Processes",
    "File Operations",
    "Configuring 6 tool(s):",
    "Choose a provider:",
    "Local Browser",
    "Skip — keep defaults / configure later",
)


def read_window(fd: int, buffer: bytes, duration: float) -> bytes:
    """Read a bounded PTY window without waiting for a continuously redrawn surface."""
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        readable, _, _ = select.select([fd], [], [], 0.02)
        if not readable:
            continue
        try:
            chunk = os.read(fd, 65_536)
        except OSError as error:
            if error.errno == errno.EIO:
                break
            raise
        if not chunk:
            break
        buffer += chunk
    return buffer


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "standalone-tool-configuration-action-boundary"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-standalone-tool-configuration-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        pid, fd, slave_path = spawn_setup(reference, home)
        files_before = file_inventory(home)
        config_before = config_shape(home / "config.yaml")
        buffer = wait_for_rendered(pid, fd, buffer, case, "initial-surface", INITIAL_MARKERS, timeout)
        initial_flags = terminal_flags(slave_path)

        write_bytes(fd, b"j")
        buffer = wait_for_rendered(pid, fd, buffer, case, "full-setup", ("Full setup",), timeout)
        write_bytes(fd, b"\r")
        buffer = wait_for_rendered(
            pid, fd, buffer, case, "continuation-surface", CONTINUATION_MARKERS, timeout
        )
        continuation_flags = terminal_flags(slave_path)

        write_bytes(fd, b"\x03")
        time.sleep(0.1)
        buffer = wait_for_rendered(pid, fd, buffer, case, "terminal-backend", BACKEND_MARKERS, timeout)
        backend_flags = terminal_flags(slave_path)
        write_bytes(fd, b"\r")
        time.sleep(0.1)
        buffer = wait_for_rendered(pid, fd, buffer, case, "platform-picker", PLATFORM_MARKERS, timeout)
        platform_flags = terminal_flags(slave_path)

        write_bytes(fd, b"\x03")
        buffer = wait_for_rendered(
            pid, fd, buffer, case, "tool-configuration", TOOL_CONFIGURATION_MARKERS, timeout
        )
        tool_configuration_flags = terminal_flags(slave_path)
        tool_config_offset = len(buffer)
        leaves_before_cancel = buffer.count(b"\x1b[?1049l")
        config_at_tool_configuration = config_shape(home / "config.yaml")
        files_at_tool_configuration = file_inventory(home)

        # Escape is the only bounded non-secret action exercised here. Stop at
        # the first newly opened surface and do not submit a tool/platform/key.
        write_bytes(fd, b"\x1b")
        time.sleep(0.75)
        buffer = read_window(fd, buffer, 0.25)
        action_bytes = buffer[tool_config_offset:]
        action_markers = {
            marker: marker.encode() in action_bytes for marker in SAFE_ACTION_CANDIDATES
        }
        action_process_alive = not child_status(pid)[0]
        action_flags = terminal_flags(slave_path)
        leaves_after_action = buffer.count(b"\x1b[?1049l")
        config_after_action = config_shape(home / "config.yaml")

        if not action_process_alive:
            raise RuntimeError("Escape unexpectedly exited Hermes before bounded Ctrl+C cleanup")

        # Escape may have opened a new raw curses provider surface. Repeated
        # Ctrl+C is still a safe cancellation path; never submit a selection.
        cleanup_deadline = time.monotonic() + min(timeout, 5.0)
        status: int | None = None
        cleanup_presses = 0
        while time.monotonic() < cleanup_deadline:
            write_bytes(fd, b"\x03")
            cleanup_presses += 1
            buffer = read_window(fd, buffer, 0.05)
            exited, candidate_status = child_status(pid)
            if exited:
                status = candidate_status
                break
            time.sleep(0.1)
        if status is None:
            raise RuntimeError(
                "bounded Ctrl+C cleanup did not exit after the Escape action; "
                f"flags={terminal_flags(slave_path)} tail={safe_tail(buffer)}"
            )
        buffer = read_window(fd, buffer, 0.05)
        exit_status = describe_status(status)
        cleanup_flags = terminal_flags(slave_path)
        files_after = file_inventory(home)
        config_after = config_shape(home / "config.yaml")
        if exit_status != {"kind": "exit", "code": 130}:
            raise RuntimeError(f"unexpected bounded cleanup status: {exit_status}")
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise RuntimeError(f"terminal was not restored after cleanup: {cleanup_flags}")
        if config_after_action != config_at_tool_configuration or config_after != config_after_action:
            raise RuntimeError("bounded Tool Configuration action changed the config shape")
        if (home / ".env").exists():
            raise RuntimeError("bounded Tool Configuration action created a secrets file")

        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "key", "value": "j", "bytes_hex": "6a", "meaning": "move to Full setup"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d", "meaning": "submit Full setup"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "skip provider"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d", "meaning": "accept local backend"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "cancel platform picker"},
                {"kind": "key", "value": "Escape", "bytes_hex": "1b", "meaning": "bounded non-secret action"},
                {"kind": "key", "value": "Ctrl+C × bounded cleanup", "bytes_hex": "03", "meaning": "cancel without selecting a tool/provider"},
            ],
            "surfaces": {
                "initial_terminal_flags": initial_flags,
                "continuation_terminal_flags": continuation_flags,
                "terminal_backend_terminal_flags": backend_flags,
                "platform_picker_terminal_flags": platform_flags,
                "tool_configuration_markers": list(TOOL_CONFIGURATION_MARKERS),
                "tool_configuration_terminal_flags": tool_configuration_flags,
            },
            "bounded_action": {
                "key": "Escape",
                "process_still_alive": action_process_alive,
                "terminal_flags": action_flags,
                "new_alternate_screen_leaves": leaves_after_action > leaves_before_cancel,
                "new_stable_markers": action_markers,
                "stopped_before_submission": True,
            },
            "cancellation": {
                "first_platform_ctrl_c_alternate_screen_left": leaves_before_cancel > 0,
                "bounded_ctrl_c_exit": exit_status,
                "cleanup_ctrl_c_presses": cleanup_presses,
                "alternate_screen_entered": b"\x1b[?1049h" in buffer,
                "alternate_screen_left": b"\x1b[?1049l" in buffer,
                "terminal_flags": cleanup_flags,
                "credentials_entered": False,
                "oauth_started": False,
                "network_requested": False,
            },
            "persistence": {
                "config_before": config_before,
                "config_at_tool_configuration": config_at_tool_configuration,
                "config_after_action": config_after_action,
                "config_after_cleanup": config_after,
                "config_created_during_setup": config_at_tool_configuration != config_before,
                "config_unchanged_after_action": config_after_action == config_at_tool_configuration,
                "config_unchanged_after_cleanup": config_after == config_after_action,
                "artifact_classes_before_tool_configuration": artifact_classes(
                    files_at_tool_configuration - files_before
                ),
                "artifact_classes_after_cleanup": artifact_classes(files_after - files_at_tool_configuration),
                "secrets_file_created": False,
            },
        }
    finally:
        if pid != -1:
            if not child_status(pid)[0]:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    os.waitpid(pid, 0)
                except ChildProcessError:
                    pass
            try:
                os.close(fd)
            except OSError:
                pass
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0075",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "fresh synthetic home with direct PTY and bounded non-secret action",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, PTY paths, credentials, timestamps, and raw redraw bytes are omitted or replaced by stable markers.",
            "The safe route enters only Full setup, skips the provider, accepts the displayed local backend, cancels the platform picker, sends one Escape at Tool Configuration, and then sends Ctrl+C cleanup.",
            "The action report retains only candidate marker booleans and normalized config/artifact shape; it stops before any tool, platform, secret, provider, or model submission.",
        ],
        "unknowns": [
            "Any tool checklist rows, tool selection semantics, platform-specific tool configuration, credentials, OAuth, provider activity, and successful save behavior remain unknown because the probe stops before submission.",
            "The observed plain Tool Configuration screen's later interactive continuation is bounded by one Escape action and may depend on terminal/input timing outside this probe.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        reference = args.reference.resolve()
        if not reference.is_dir():
            raise RuntimeError(f"reference checkout does not exist: {reference}")
        report["cases"] = [run_case(reference, args.timeout)]
        report["passed"] = True
    except (OSError, RuntimeError, ValueError) as error:
        report["failure"] = {"message": str(error)}
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(serialized)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
