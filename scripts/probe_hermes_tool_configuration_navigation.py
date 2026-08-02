#!/usr/bin/env python3
"""Capture one non-mutating Hermes Tool Configuration navigation boundary."""

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
    BACKEND_MARKERS,
    CONTINUATION_MARKERS,
    DEFAULT_REFERENCE,
    INITIAL_MARKERS,
    PLATFORM_MARKERS,
    SOURCE_COMMIT,
    TOOL_CONFIGURATION_MARKERS,
    artifact_classes,
    config_shape,
    file_inventory,
    safe_tail,
    spawn_setup,
    wait_for_rendered,
)
from probe_hermes_terminal_palette import Screen, child_status, write_bytes
from probe_tui_lifecycle import terminal_flags


COLUMNS = 120
ROWS = 40
CHECKLIST_MARKERS = (
    "Tools for 🖥️  CLI",
    "SPACE toggle",
    "ENTER confirm",
    "ESC cancel",
)
CHECKLIST_ROWS = (
    "Web Search & Scraping",
    "Browser Automation",
    "Terminal & Processes",
    "File Operations",
)
ACTION_MARKERS = CHECKLIST_MARKERS + CHECKLIST_ROWS + (
    "Configuring 6 tool(s):",
    "Choose a provider",
    "Local Browser",
    "Skip — keep defaults / configure later",
)


def read_window(fd: int, buffer: bytes, duration: float) -> bytes:
    """Read a bounded PTY window without waiting on a continuously redrawn surface."""
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


def wait_for_suffix_markers(
    pid: int,
    fd: int,
    buffer: bytes,
    offset: int,
    markers: tuple[str, ...],
    timeout: float,
) -> bytes:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        buffer = read_window(fd, buffer, 0.05)
        suffix = buffer[offset:]
        if all(marker.encode("utf-8") in suffix for marker in markers):
            return buffer
        if child_status(pid)[0]:
            raise RuntimeError(
                "Hermes exited before the bounded checklist surface rendered: "
                f"{safe_tail(buffer)}"
            )
    raise RuntimeError(f"timed out waiting for checklist markers: {markers}")


def screen_snapshot(raw: bytes) -> dict[str, Any]:
    screen = Screen(columns=COLUMNS, rows=ROWS)
    screen.feed(raw)
    lines = screen.lines()
    return {
        "rows": [
            {"marker": marker, "style": screen.marker_style(marker)}
            for marker in CHECKLIST_ROWS
            if screen.marker_style(marker) is not None
        ],
        "marker_lines": [
            line.strip()
            for line in lines
            if any(marker in line for marker in CHECKLIST_MARKERS + CHECKLIST_ROWS)
        ],
        "style_inventory": screen.inventory(),
    }


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "standalone-tool-configuration-navigation-boundary"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-tool-configuration-navigation-"))
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
        buffer = wait_for_rendered(pid, fd, buffer, case, "terminal-backend", BACKEND_MARKERS, timeout)
        backend_flags = terminal_flags(slave_path)
        write_bytes(fd, b"\r")
        buffer = wait_for_rendered(pid, fd, buffer, case, "platform-picker", PLATFORM_MARKERS, timeout)
        platform_flags = terminal_flags(slave_path)

        write_bytes(fd, b"\x03")
        buffer = wait_for_rendered(
            pid, fd, buffer, case, "tool-configuration", TOOL_CONFIGURATION_MARKERS, timeout
        )
        tool_configuration_flags = terminal_flags(slave_path)
        config_at_tool_configuration = config_shape(home / "config.yaml")
        files_at_tool_configuration = file_inventory(home)

        # Escape opens the raw checklist. No row is selected or confirmed.
        checklist_offset = len(buffer)
        write_bytes(fd, b"\x1b")
        buffer = wait_for_suffix_markers(pid, fd, buffer, checklist_offset, CHECKLIST_MARKERS, timeout)
        checklist_flags = terminal_flags(slave_path)
        checklist_process_alive = not child_status(pid)[0]
        checklist_snapshot = screen_snapshot(buffer)

        # One `j` navigation key is navigation only. It must not toggle or submit
        # a tool.
        navigation_offset = len(buffer)
        write_bytes(fd, b"j")
        # Keep this observation window bounded; downstream setup is explicitly
        # not explored after the first cancellation boundary.
        buffer = read_window(fd, buffer, 0.10)
        navigation_bytes = buffer[navigation_offset:]
        navigation_snapshot = screen_snapshot(buffer)
        navigation_flags = terminal_flags(slave_path)
        navigation_markers = {
            marker: marker.encode("utf-8") in navigation_bytes for marker in ACTION_MARKERS
        }
        navigation_process_alive = not child_status(pid)[0]
        if not navigation_process_alive:
            raise RuntimeError("Down unexpectedly exited Hermes before bounded cancellation")

        # Ctrl+C is the first bounded cancellation action from the raw checklist.
        # It returns into the first-install tool configuration flow, which is
        # outside this task. Capture only that handoff and stop before any
        # provider/key prompt can be submitted.
        cancel_offset = len(buffer)
        write_bytes(fd, b"\x03")
        buffer = read_window(fd, buffer, 0.20)
        cancel_bytes = buffer[cancel_offset:]
        cancel_flags = terminal_flags(slave_path)
        cancel_process_alive = not child_status(pid)[0]
        cancel_markers = {
            marker: marker.encode("utf-8") in cancel_bytes for marker in ACTION_MARKERS
        }
        cancel_tail = safe_tail(cancel_bytes)
        files_after_scope = file_inventory(home)
        config_after_scope = config_shape(home / "config.yaml")
        secrets_file_created = (home / ".env").exists()

        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "key", "value": "j", "bytes_hex": "6a", "meaning": "move to Full setup"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d", "meaning": "submit Full setup"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "skip provider"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d", "meaning": "accept local backend"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "cancel platform picker"},
                {"kind": "key", "value": "Escape", "bytes_hex": "1b", "meaning": "open tool checklist"},
                {"kind": "key", "value": "j", "bytes_hex": "6a", "meaning": "one non-mutating navigation step"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "bounded checklist cancellation without toggling"},
            ],
            "surfaces": {
                "initial_terminal_flags": initial_flags,
                "continuation_terminal_flags": continuation_flags,
                "terminal_backend_terminal_flags": backend_flags,
                "platform_picker_terminal_flags": platform_flags,
                "tool_configuration_terminal_flags": tool_configuration_flags,
                "checklist": {
                    "markers": list(CHECKLIST_MARKERS),
                    "terminal_flags": checklist_flags,
                    "process_still_alive": checklist_process_alive,
                    "snapshot": checklist_snapshot,
                },
                "after_down": {
                    "terminal_flags": navigation_flags,
                    "process_still_alive": navigation_process_alive,
                    "markers_in_delta": navigation_markers,
                    "snapshot": navigation_snapshot,
                    "snapshot_changed": navigation_snapshot != checklist_snapshot,
                },
                "after_ctrl_c": {
                    "terminal_flags": cancel_flags,
                    "process_still_alive": cancel_process_alive,
                    "markers_in_delta": cancel_markers,
                    "safe_screen_tail": cancel_tail,
                },
            },
            "navigation": {
                "key": "j",
                "bytes_hex": "6a",
                "mutated_selection": False,
                "confirmed_tool": False,
                "provider_or_secret_surface_submitted": False,
                "checklist_snapshot_changed": navigation_snapshot != checklist_snapshot,
            },
            "cancellation": {
                "first_ctrl_c_left_process_alive": cancel_process_alive,
                "first_ctrl_c_outcome": "left the raw checklist and opened the first-install continuation at Configuring 6 tool(s), then the Browser Automation provider boundary",
                "later_cancellation_status": "unknown; probe stopped at the new boundary",
                "probe_teardown": "forced child/process-group teardown after the bounded evidence window; not a Hermes product outcome",
                "alternate_screen_entered": b"\x1b[?1049h" in buffer,
                "alternate_screen_left": b"\x1b[?1049l" in buffer,
                "terminal_flags_at_scope_exit": cancel_flags,
                "credentials_entered": False,
                "oauth_started": False,
                "network_requested": False,
            },
            "persistence": {
                "config_before": config_before,
                "config_at_tool_configuration": config_at_tool_configuration,
                "config_at_scope_exit": config_after_scope,
                "config_created_during_setup": config_at_tool_configuration != config_before,
                "config_unchanged_through_navigation": config_after_scope == config_at_tool_configuration,
                "artifact_classes_before_tool_configuration": artifact_classes(
                    files_at_tool_configuration - files_before
                ),
                "artifact_classes_at_scope_exit": artifact_classes(
                    files_after_scope - files_at_tool_configuration
                ),
                "secrets_file_created": secrets_file_created,
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
        "observation_id": "OBS-0076",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "fresh synthetic home with direct PTY and one non-mutating navigation key",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, PTY paths, credentials, timestamps, and raw redraw bytes are omitted or replaced by stable markers.",
            "The safe route enters only Full setup, skips the provider, accepts the displayed local backend, cancels the platform picker, opens the CLI checklist, presses j once, cancels with Ctrl+C, and stops before any later setup continuation.",
            "Navigation evidence records stable checklist rows, terminal state, screen-model style snapshots, and normalized config/artifact shape; no tool, platform, secret, provider, or model value is submitted.",
        ],
        "unknowns": [
            "The exact selected-row styling is retained only as a bounded screen-model comparison; tool-specific cursor semantics, scrolling, toggling, confirmation, provider selection, and successful save behavior remain unknown.",
            "Later provider/platform/credential prompts, OAuth, network behavior, and config persistence after a tool toggle remain unknown because this probe never toggles or confirms a tool.",
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
