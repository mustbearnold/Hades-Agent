#!/usr/bin/env python3
"""Capture Hermes' first-install tool-provider boundary without submission."""

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
from probe_hermes_terminal_palette import child_status, write_bytes
from probe_tui_lifecycle import terminal_flags


COLUMNS = 120
ROWS = 40
CHECKLIST_MARKERS = (
    "Tools for 🖥️  CLI",
    "SPACE toggle",
    "ENTER confirm",
    "ESC cancel",
)
PROVIDER_BOUNDARY_MARKERS = (
    "Configuring 6 tool(s):",
    "Browser Automation",
    "Choose a provider",
)


def read_window(fd: int, buffer: bytes, duration: float) -> bytes:
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
            raise RuntimeError(f"Hermes exited before the checklist surface rendered: {safe_tail(buffer)}")
    raise RuntimeError(f"timed out waiting for checklist markers: {markers}")


def force_teardown(pid: int) -> None:
    """Stop only the probe-owned child group after the evidence boundary."""
    if child_status(pid)[0]:
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "standalone-first-install-tool-provider-boundary"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-tool-provider-boundary-"))
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

        checklist_offset = len(buffer)
        write_bytes(fd, b"\x1b")
        buffer = wait_for_suffix_markers(pid, fd, buffer, checklist_offset, CHECKLIST_MARKERS, timeout)
        checklist_flags = terminal_flags(slave_path)
        checklist_alive = not child_status(pid)[0]

        # Ctrl+C is the only action from the checklist. Capture the first
        # first-install continuation and stop before any provider value/key.
        provider_offset = len(buffer)
        write_bytes(fd, b"\x03")
        buffer = read_window(fd, buffer, 0.20)
        provider_delta = buffer[provider_offset:]
        provider_markers = {
            marker: marker.encode("utf-8") in provider_delta for marker in PROVIDER_BOUNDARY_MARKERS
        }
        provider_flags = terminal_flags(slave_path)
        provider_alive = not child_status(pid)[0]
        provider_config = config_shape(home / "config.yaml")
        files_at_provider_boundary = file_inventory(home)
        if not all(provider_markers.values()):
            raise RuntimeError(
                "provider boundary markers did not render in the bounded window: "
                f"{provider_markers}; tail={safe_tail(provider_delta)}"
            )

        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "key", "value": "j", "bytes_hex": "6a", "meaning": "move to Full setup"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d", "meaning": "submit Full setup"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "skip provider"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d", "meaning": "accept local backend"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "cancel platform picker"},
                {"kind": "key", "value": "Escape", "bytes_hex": "1b", "meaning": "open raw CLI checklist"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "bounded checklist cancellation"},
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
                    "process_still_alive": checklist_alive,
                },
                "provider_boundary": {
                    "markers": list(PROVIDER_BOUNDARY_MARKERS),
                    "markers_in_delta": provider_markers,
                    "terminal_flags": provider_flags,
                    "process_still_alive": provider_alive,
                    "discovery_window_ms": 200,
                    "safe_screen_tail": safe_tail(provider_delta),
                    "provider_choice_submitted": False,
                },
            },
            "cancellation": {
                "first_ctrl_c_left_checklist": True,
                "later_cancellation_status": "unknown; probe stopped at the first-install provider boundary",
                "probe_teardown": "forced child/process-group teardown after the bounded evidence window; not a Hermes product outcome",
                "alternate_screen_entered": b"\x1b[?1049h" in buffer,
                "alternate_screen_left": b"\x1b[?1049l" in buffer,
                "terminal_flags_at_provider_boundary": provider_flags,
                "credentials_entered": False,
                "oauth_started": False,
                "network_requested": False,
            },
            "persistence": {
                "config_before": config_before,
                "config_at_tool_configuration": config_at_tool_configuration,
                "config_at_provider_boundary": provider_config,
                "config_created_during_setup": config_at_tool_configuration != config_before,
                "config_unchanged_through_provider_boundary": provider_config == config_at_tool_configuration,
                "artifact_classes_before_tool_configuration": artifact_classes(
                    files_at_tool_configuration - files_before
                ),
                "artifact_classes_at_provider_boundary": artifact_classes(
                    files_at_provider_boundary - files_at_tool_configuration
                ),
                "secrets_file_created": (home / ".env").exists(),
            },
        }
    finally:
        if pid != -1:
            force_teardown(pid)
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
        "observation_id": "OBS-0077",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "fresh synthetic home with direct PTY and bounded provider-boundary capture",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, PTY paths, credentials, timestamps, and raw redraw bytes are omitted or replaced by stable markers.",
            "The route enters only Full setup, skips the provider, accepts the local backend, cancels the platform picker, opens the raw CLI checklist, sends one Ctrl+C, and stops after the first-install provider boundary.",
            "Provider discovery timing is retained only as a 200 ms bounded observation; provider choices, key prompts, OAuth, network behavior, and later cleanup are not claimed.",
        ],
        "unknowns": [
            "The complete provider list, selected provider semantics, API-key prompts, provider discovery subprocess behavior, OAuth, network activity, configuration persistence, and later cancellation status remain unknown.",
            "The forced child/process-group teardown is probe cleanup only and is not a Hermes product exit or terminal-restoration claim.",
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
