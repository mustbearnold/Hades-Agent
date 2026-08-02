#!/usr/bin/env python3
"""Observe bounded Hermes provider-inventory navigation and cancellation inputs."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import termios
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
from probe_tui_lifecycle import (
    describe_status,
    release_slave_descriptor,
    retain_slave_descriptor,
)


COLUMNS = 120
ROWS = 40
PROVIDER_INVENTORY_MARKERS = (
    "Choose a provider:",
    "↑↓ navigate",
    "ENTER/SPACE select",
    "ESC cancel",
    "Local Browser",
    "Nous Subscription",
    "Camofox",
    "Browser Use",
    "Browserbase",
    "Firecrawl",
    "Skip — keep defaults / configure later",
)
INTERACTION_WINDOW_SECONDS = 0.75
SAFE_INPUTS = {
    "down": b"\x1b[B",
    "escape": b"\x1b",
    "ctrl-c": b"\x03",
}


def marker_lines(raw: bytes, markers: tuple[str, ...]) -> list[str]:
    return [
        line.strip()
        for line in rendered_text(raw).splitlines()
        if any(marker in line for marker in markers)
    ]


def surface_flags(terminal_fd: int) -> dict[str, bool]:
    attributes = termios.tcgetattr(terminal_fd)
    local_flags = attributes[3]
    return {
        "canonical": bool(local_flags & termios.ICANON),
        "echo": bool(local_flags & termios.ECHO),
    }


def route_to_provider(
    reference: Path,
    home: Path,
    timeout: float,
    session: dict[str, int],
) -> tuple[int, int, int, bytes, dict[str, Any]]:
    case = "standalone-first-install-tool-provider-inventory-interaction"
    pid, fd, slave_path = spawn_setup(reference, home)
    session.update(pid=pid, fd=fd)
    terminal_fd = retain_slave_descriptor(slave_path)
    session.update(terminal_fd=terminal_fd, slave_path=slave_path)
    buffer = b""
    files_before = file_inventory(home)
    config_before = config_shape(home / "config.yaml")

    buffer = wait_for_rendered(pid, fd, buffer, case, "initial-surface", INITIAL_MARKERS, timeout)
    initial_flags = surface_flags(terminal_fd)
    write_bytes(fd, b"j")
    buffer = wait_for_rendered(pid, fd, buffer, case, "full-setup", ("Full setup",), timeout)
    write_bytes(fd, b"\r")
    buffer = wait_for_rendered(
        pid, fd, buffer, case, "continuation-surface", CONTINUATION_MARKERS, timeout
    )
    continuation_flags = surface_flags(terminal_fd)

    write_bytes(fd, b"\x03")
    buffer = wait_for_rendered(pid, fd, buffer, case, "terminal-backend", BACKEND_MARKERS, timeout)
    backend_flags = surface_flags(terminal_fd)
    write_bytes(fd, b"\r")
    buffer = wait_for_rendered(pid, fd, buffer, case, "platform-picker", PLATFORM_MARKERS, timeout)
    platform_flags = surface_flags(terminal_fd)

    write_bytes(fd, b"\x03")
    buffer = wait_for_rendered(
        pid, fd, buffer, case, "tool-configuration", TOOL_CONFIGURATION_MARKERS, timeout
    )
    tool_configuration_flags = surface_flags(terminal_fd)
    config_at_tool_configuration = config_shape(home / "config.yaml")
    files_at_tool_configuration = file_inventory(home)

    checklist_offset = len(buffer)
    write_bytes(fd, b"\x1b")
    buffer = wait_for_suffix_markers(pid, fd, buffer, checklist_offset, CHECKLIST_MARKERS, timeout)
    checklist_flags = surface_flags(terminal_fd)

    provider_offset = len(buffer)
    write_bytes(fd, b"\x03")
    buffer = wait_for_suffix_markers(
        pid, fd, buffer, provider_offset, PROVIDER_BOUNDARY_MARKERS, timeout
    )
    buffer = read_window(fd, buffer, 1.0)
    inventory_delta = buffer[provider_offset:]
    if not all(marker.encode("utf-8") in inventory_delta for marker in PROVIDER_INVENTORY_MARKERS):
        raise RuntimeError(
            "provider inventory did not render before interaction: "
            f"tail={safe_tail(inventory_delta)}"
        )

    route = {
        "initial": {"markers": list(INITIAL_MARKERS), "terminal_flags": initial_flags},
        "continuation": {
            "markers": list(CONTINUATION_MARKERS),
            "terminal_flags": continuation_flags,
        },
        "terminal_backend": {
            "markers": list(BACKEND_MARKERS),
            "terminal_flags": backend_flags,
        },
        "platform_picker": {
            "markers": list(PLATFORM_MARKERS),
            "terminal_flags": platform_flags,
        },
        "tool_configuration": {
            "markers": list(TOOL_CONFIGURATION_MARKERS),
            "terminal_flags": tool_configuration_flags,
        },
        "checklist": {
            "markers": list(CHECKLIST_MARKERS),
            "terminal_flags": checklist_flags,
            "process_still_alive": not child_status(pid)[0],
        },
        "provider_inventory": {
            "markers": list(PROVIDER_INVENTORY_MARKERS),
            "terminal_flags": surface_flags(terminal_fd),
            "process_still_alive_before_interaction": not child_status(pid)[0],
            "observation_window_ms": 1000,
            "rendered_marker_lines": marker_lines(inventory_delta, PROVIDER_INVENTORY_MARKERS),
        },
        "alternate_screen": {
            "entered": b"\x1b[?1049h" in buffer,
            "left_before_interaction": b"\x1b[?1049l" in buffer,
        },
        "persistence": {
            "config_before": config_before,
            "config_at_tool_configuration": config_at_tool_configuration,
            "files_before": sorted(files_before),
            "files_at_tool_configuration": sorted(files_at_tool_configuration),
        },
    }
    return pid, fd, terminal_fd, buffer, {
        "route": route,
        "config_at_tool_configuration": config_at_tool_configuration,
        "files_at_tool_configuration": files_at_tool_configuration,
    }


def finish_case(
    pid: int,
    fd: int,
    terminal_fd: int,
    buffer: bytes,
    route_state: dict[str, Any],
    interaction: str,
    timeout: float,
) -> dict[str, Any]:
    payload = SAFE_INPUTS[interaction]
    interaction_offset = len(buffer)
    write_bytes(fd, payload)
    buffer = read_window(fd, buffer, INTERACTION_WINDOW_SECONDS)
    interaction_delta = buffer[interaction_offset:]
    exited, status = child_status(pid)
    exit_description = describe_status(status) if exited and status is not None else None

    config_after = config_shape(route_state["home"] / "config.yaml")
    files_after = file_inventory(route_state["home"])
    if config_after != route_state["config_at_tool_configuration"]:
        raise RuntimeError(f"{interaction} changed the setup config")
    if (route_state["home"] / ".env").exists():
        raise RuntimeError(f"{interaction} created a secrets file")

    if interaction != "ctrl-c" and exited:
        raise RuntimeError(f"{interaction} unexpectedly exited Hermes: {exit_description}")

    result = {
        "id": f"provider-inventory-{interaction}",
        "status": "passed",
        "input": {
            "label": interaction,
            "bytes_hex": payload.hex(" "),
            "submitted_provider": False,
            "credentials_entered": False,
            "oauth_action_sent": False,
            "network_bearing_input_sent": False,
        },
        "provider_surface": route_state["route"]["provider_inventory"],
        "interaction": {
            "observation_window_ms": round(INTERACTION_WINDOW_SECONDS * 1000),
            "process_alive_after_input": not exited,
            "exit": exit_description,
            "terminal_flags_after_input": surface_flags(terminal_fd),
            "rendered_marker_lines_in_delta": marker_lines(
                interaction_delta, PROVIDER_INVENTORY_MARKERS
            ),
            "screen_delta_tail": safe_tail(interaction_delta),
        },
        "persistence": {
            "config_unchanged": config_after == route_state["config_at_tool_configuration"],
            "files_at_tool_configuration": sorted(route_state["files_at_tool_configuration"]),
            "files_after_input": sorted(files_after),
            "new_artifacts_after_input": sorted(
                set(files_after) - set(route_state["files_at_tool_configuration"])
            ),
            "secrets_file_created": False,
        },
        "scope": {
            "provider_selection_submitted": False,
            "credentials_entered": False,
            "oauth_action_sent": False,
            "network_bearing_input_sent": False,
            "later_behavior": "unknown",
            "forced_teardown_if_alive": "harness cleanup only; not a Hermes product outcome",
        },
    }
    return result


def run_case(reference: Path, interaction: str, timeout: float) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix=f"hades-hermes-provider-inventory-{interaction}-"))
    home = root / "home"
    home.mkdir()
    session = {"pid": -1, "fd": -1}
    try:
        pid, fd, terminal_fd, buffer, route_state = route_to_provider(
            reference, home, timeout, session
        )
        route_state["home"] = home
        result = finish_case(pid, fd, terminal_fd, buffer, route_state, interaction, timeout)
        result["route"] = route_state["route"]
        return result
    finally:
        pid = session["pid"]
        fd = session["fd"]
        terminal_fd = session.get("terminal_fd", -1)
        slave_path = session.get("slave_path")
        if pid != -1:
            force_teardown(pid)
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
        if isinstance(slave_path, str):
            try:
                release_slave_descriptor(slave_path)
            except OSError:
                pass
        elif terminal_fd != -1:
            try:
                os.close(terminal_fd)
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
        "observation_id": "OBS-0081",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "fresh synthetic home with direct PTY and bounded safe interaction cases",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, PTY paths, credentials, timestamps, and raw redraw bytes are omitted or replaced by stable markers.",
            "Each fresh case repeats the safe route through the provider inventory, then sends exactly one non-submitting navigation or cancellation byte sequence before the bounded read window.",
            "No provider choice, Enter, Space, credential, OAuth action, network-bearing input, or persistence action is sent; forced teardown is harness cleanup only.",
        ],
        "unknowns": [
            "Provider selection, Enter/Space semantics, credential prompts, OAuth, network behavior, persistence, discovery completeness, and behavior after the bounded window remain unknown.",
            "A rendered screen delta or line-buffered echo is not promoted into a provider-selection claim; any Hermes defect observed here is not a Hades compatibility requirement.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        reference = args.reference.resolve()
        if not reference.is_dir():
            raise RuntimeError(f"reference checkout does not exist: {reference}")
        report["cases"] = [
            run_case(reference, interaction, args.timeout)
            for interaction in ("down", "escape", "ctrl-c")
        ]
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
