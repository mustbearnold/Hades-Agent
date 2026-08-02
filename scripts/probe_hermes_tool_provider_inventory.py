#!/usr/bin/env python3
"""Capture the bounded Hermes Browser Automation provider inventory surface."""

from __future__ import annotations

import argparse
import json
import os
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
    rendered_text,
    safe_tail,
    spawn_setup,
    wait_for_rendered,
)
from probe_hermes_terminal_palette import child_status, write_bytes
from probe_hermes_tool_provider_boundary import (
    CHECKLIST_MARKERS,
    PROVIDER_BOUNDARY_MARKERS,
    force_teardown,
    read_window,
    wait_for_suffix_markers,
)
from probe_tui_lifecycle import terminal_flags


COLUMNS = 120
ROWS = 40
OBSERVATION_WINDOW_SECONDS = 1.0
INVENTORY_MARKERS = (
    "Local Browser",
    "Nous Subscription",
    "Camofox",
    "Browser Use",
    "Browserbase",
    "Firecrawl",
    "Skip — keep defaults / configure later",
)
PROVIDER_CONTROL_MARKERS = (
    "Choose a provider:",
    "ENTER/SPACE select",
    "ESC cancel",
)


def marker_lines(raw: bytes, markers: tuple[str, ...]) -> list[str]:
    return [
        line.strip()
        for line in rendered_text(raw).splitlines()
        if any(marker in line for marker in markers)
    ]


def run_case(reference: Path, timeout: float, observation_window: float) -> dict[str, Any]:
    case = "standalone-first-install-tool-provider-inventory"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-tool-provider-inventory-"))
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

        provider_offset = len(buffer)
        write_bytes(fd, b"\x03")
        buffer = wait_for_suffix_markers(
            pid, fd, buffer, provider_offset, PROVIDER_BOUNDARY_MARKERS, timeout
        )
        provider_flags = terminal_flags(slave_path)
        provider_boundary_delta = buffer[provider_offset:]

        # Read only; no key is sent during this window. The screen may be
        # static or may discover providers asynchronously, so retain both the
        # raw sanitized tail and the rendered marker lines.
        first_snapshot = rendered_text(provider_boundary_delta)
        first_markers = marker_lines(provider_boundary_delta, INVENTORY_MARKERS)
        buffer = read_window(fd, buffer, observation_window)
        inventory_delta = buffer[provider_offset:]
        second_snapshot = rendered_text(inventory_delta)
        inventory_markers = marker_lines(inventory_delta, INVENTORY_MARKERS)
        provider_config = config_shape(home / "config.yaml")
        files_at_provider_boundary = file_inventory(home)
        provider_alive = not child_status(pid)[0]

        if not provider_alive:
            raise RuntimeError("Hermes exited during the read-only provider inventory window")
        if provider_config != config_at_tool_configuration:
            raise RuntimeError("read-only provider inventory observation changed config shape")
        if (home / ".env").exists():
            raise RuntimeError("read-only provider inventory observation created a secrets file")

        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "key", "value": "j", "bytes_hex": "6a", "meaning": "move to Full setup"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d", "meaning": "submit Full setup"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "skip the unconfigured provider"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d", "meaning": "accept Keep current (local)"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "cancel the platform picker"},
                {"kind": "key", "value": "Escape", "bytes_hex": "1b", "meaning": "open the raw CLI checklist"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "reach the first-install provider boundary"},
                {"kind": "wait", "value": f"{observation_window:.3f}s", "meaning": "read provider inventory without input"},
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
                    "terminal_flags": provider_flags,
                    "process_still_alive_before_window": True,
                },
                "provider_inventory": {
                    "candidate_markers": list(INVENTORY_MARKERS),
                    "selection_controls": {
                        marker: marker.encode("utf-8") in inventory_delta
                        for marker in PROVIDER_CONTROL_MARKERS
                    },
                    "first_window_lines": first_markers,
                    "observation_window_ms": round(observation_window * 1000),
                    "lines": inventory_markers,
                    "snapshot_changed_during_window": first_snapshot != second_snapshot,
                    "stable_inventory_observed": bool(inventory_markers) and first_snapshot == second_snapshot,
                    "safe_screen_tail": safe_tail(inventory_delta),
                },
            },
            "persistence": {
                "config_before": config_before,
                "config_at_tool_configuration": config_at_tool_configuration,
                "config_at_provider_boundary": provider_config,
                "config_unchanged_during_read_only_window": provider_config == config_at_tool_configuration,
                "artifact_classes_before_tool_configuration": artifact_classes(
                    files_at_tool_configuration - files_before
                ),
                "artifact_classes_at_provider_boundary": artifact_classes(
                    files_at_provider_boundary - files_at_tool_configuration
                ),
                "secrets_file_created": (home / ".env").exists(),
            },
            "scope": {
                "provider_selection_submitted": False,
                "credentials_entered": False,
                "oauth_action_sent": False,
                "network_bearing_input_sent": False,
                "later_cancellation": "unknown",
                "probe_teardown": "forced child/process-group teardown after the bounded read window; not a Hermes product outcome",
                "alternate_screen_entered": b"\x1b[?1049h" in buffer,
                "alternate_screen_left_before_teardown": b"\x1b[?1049l" in buffer,
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
    parser.add_argument("--observation-window", type=float, default=OBSERVATION_WINDOW_SECONDS)
    args = parser.parse_args()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0079",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "fresh synthetic home with direct PTY and bounded read-only provider inventory capture",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, PTY paths, credentials, timestamps, and raw redraw bytes are omitted or replaced by stable markers.",
            "The safe route enters only Full setup, skips the provider, accepts the local backend, cancels the platform picker, opens the raw CLI checklist, sends Ctrl+C, and reads the provider boundary without further input.",
            "Provider inventory evidence is retained only as a bounded rendered screen and marker observation; no provider choice, key, OAuth action, or network-bearing input is sent.",
        ],
        "unknowns": [
            "Provider selection semantics, API-key prompts, OAuth, network behavior, persistence after selection, and later cancellation remain unknown.",
            "A stable provider inventory is not inferred when the bounded snapshots differ or no candidate marker is rendered.",
            "Forced child/process-group teardown is probe cleanup only and is not a Hermes product exit or terminal-restoration claim.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        reference = args.reference.resolve()
        if not reference.is_dir():
            raise RuntimeError(f"reference checkout does not exist: {reference}")
        if args.observation_window <= 0:
            raise ValueError("observation window must be positive")
        report["cases"] = [run_case(reference, args.timeout, args.observation_window)]
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
