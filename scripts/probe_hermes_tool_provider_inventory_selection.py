#!/usr/bin/env python3
"""Observe bounded Hermes provider-inventory selection and cancellation."""

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
    DEFAULT_REFERENCE,
    SOURCE_COMMIT,
    artifact_classes,
    config_shape,
    file_inventory,
    rendered_text,
    safe_tail,
)
from probe_hermes_terminal_palette import child_status, write_bytes
from probe_hermes_tool_provider_boundary import force_teardown, read_window
from probe_hermes_tool_provider_inventory_edges import PROVIDER_ROWS
from probe_hermes_tool_provider_inventory_interaction import (
    COLUMNS,
    PROVIDER_INVENTORY_MARKERS,
    route_to_provider,
    surface_flags,
)
from probe_tui_lifecycle import describe_status, release_slave_descriptor


ROWS = 40
OBSERVATION_WINDOW_SECONDS = 1.5
PRE_ACTION_IDLE_SECONDS = 1.0
STEP_WINDOW_SECONDS = 0.15
ARROW_DOWN = b"\x1b[B"


def cursor_targets(raw: bytes) -> list[str]:
    return [
        target
        for line in rendered_text(raw).splitlines()
        if "→" in line
        for target in PROVIDER_ROWS
        if target in line
    ]


def selected_targets(raw: bytes) -> list[str]:
    return [
        target
        for line in rendered_text(raw).splitlines()
        if "(●)" in line
        for target in PROVIDER_ROWS
        if target in line
    ]


def marker_state(raw: bytes) -> dict[str, Any]:
    text = rendered_text(raw)
    transition_markers = (
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
        "API key",
        "api key",
        "OAuth",
        "oauth",
        "configured",
        "Configuration",
        "cancel",
        "Cancel",
        "error",
        "Error",
        "saved",
        "Save",
        "Tools",
    )
    return {
        "provider_inventory_markers": [
            marker for marker in PROVIDER_INVENTORY_MARKERS if marker in text
        ],
        "transition_markers": [marker for marker in transition_markers if marker in text],
        "cursor_targets": cursor_targets(raw),
        "selected_targets": selected_targets(raw),
        "rendered_tail": "\n".join(text.splitlines()[-18:]),
    }


def normalized_tail(raw: bytes, root: Path, reference: Path) -> str:
    tail = safe_tail(raw)
    return (
        tail.replace(str(root), "<synthetic-root>")
        .replace(str(reference), "<reference-checkout>")
    )


def process_snapshot(pid: int) -> list[dict[str, str]]:
    """Record descendant process names without retaining PIDs or command args."""
    parents: dict[int, int] = {}
    commands: dict[int, str] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8")
            comm = (entry / "comm").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            continue
        closing = stat.rfind(")")
        if closing == -1:
            continue
        fields = stat[closing + 2 :].split()
        if len(fields) < 2:
            continue
        try:
            process_id = int(entry.name)
            parent_id = int(fields[1])
        except ValueError:
            continue
        parents[process_id] = parent_id
        commands[process_id] = comm

    descendants: set[int] = set()
    frontier = [pid]
    while frontier:
        parent = frontier.pop()
        children = [child for child, parent_id in parents.items() if parent_id == parent]
        for child in children:
            if child not in descendants:
                descendants.add(child)
                frontier.append(child)
    return [
        {"command": commands[child]}
        for child in sorted(descendants)
        if child in commands
    ]


def action_inputs(action: str) -> list[tuple[str, bytes, str]]:
    if action == "enter-local":
        return [("Enter", b"\r", "submit the default Local Browser row")]
    if action == "space-local":
        return [("Space", b" ", "submit the default Local Browser row")]
    if action == "enter-skip":
        return [
            ("Down", ARROW_DOWN, "move the cursor toward Skip")
            for _ in range(6)
        ] + [("Enter", b"\r", "submit the Skip row")]
    if action == "escape":
        return [("Escape", b"\x1b", "cancel the provider inventory")]
    raise ValueError(f"unsupported action: {action}")


def run_case(reference: Path, action: str, timeout: float) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix=f"hades-hermes-provider-selection-{action}-"))
    home = root / "home"
    home.mkdir()
    session: dict[str, Any] = {"pid": -1, "fd": -1}
    try:
        pid, fd, terminal_fd, buffer, route_state = route_to_provider(
            reference, home, timeout, session
        )
        idle_offset = len(buffer)
        buffer = read_window(fd, buffer, PRE_ACTION_IDLE_SECONDS)
        idle_delta = buffer[idle_offset:]
        before_config = config_shape(home / "config.yaml")
        before_files = file_inventory(home)
        before_processes = process_snapshot(pid)
        steps: list[dict[str, Any]] = []
        interaction_offset = len(buffer)
        for label, payload, meaning in action_inputs(action):
            step_offset = len(buffer)
            write_bytes(fd, payload)
            buffer = read_window(fd, buffer, STEP_WINDOW_SECONDS)
            step_delta = buffer[step_offset:]
            steps.append(
                {
                    "label": label,
                    "bytes_hex": payload.hex(" "),
                    "meaning": meaning,
                    "observation_window_ms": round(STEP_WINDOW_SECONDS * 1000),
                    "markers": marker_state(step_delta),
                    "screen_delta_tail": normalized_tail(step_delta, root, reference),
                }
            )

        buffer = read_window(fd, buffer, OBSERVATION_WINDOW_SECONDS)
        interaction_delta = buffer[interaction_offset:]
        exited, status = child_status(pid)
        exit_description = describe_status(status) if exited and status is not None else None
        after_config = config_shape(home / "config.yaml")
        after_files = file_inventory(home)
        after_processes = process_snapshot(pid)
        flags_after = surface_flags(terminal_fd)

        return {
            "id": f"provider-inventory-{action}",
            "status": "passed",
            "input": [
                {
                    "label": label,
                    "bytes_hex": payload.hex(" "),
                    "meaning": meaning,
                    "credentials_entered": False,
                    "oauth_action_sent": False,
                    "network_bearing_input_sent": False,
                }
                for label, payload, meaning in action_inputs(action)
            ],
            "route": route_state["route"],
            "interaction": {
                "pre_action_idle_window_ms": round(PRE_ACTION_IDLE_SECONDS * 1000),
                "pre_action_idle": {
                    "markers": marker_state(idle_delta),
                    "screen_delta_tail": normalized_tail(idle_delta, root, reference),
                    "processes": before_processes,
                    "files": sorted(before_files),
                },
                "observation_window_ms_after_final_input": round(
                    OBSERVATION_WINDOW_SECONDS * 1000
                ),
                "process_alive_after_input": not exited,
                "exit": exit_description,
                "terminal_flags_after_input": flags_after,
                "alternate_screen": {
                    "entered": b"\x1b[?1049h" in buffer,
                    "left_after_interaction": b"\x1b[?1049l" in interaction_delta,
                },
                "steps": steps,
                "final_markers": marker_state(interaction_delta),
                "screen_delta_tail": normalized_tail(interaction_delta, root, reference),
            },
            "provider_processes": {
                "before_input": before_processes,
                "after_input": after_processes,
                "new_commands": sorted(
                    {item["command"] for item in after_processes}
                    - {item["command"] for item in before_processes}
                ),
            },
            "persistence": {
                "config_before_input": before_config,
                "config_after_input": after_config,
                "config_unchanged": before_config == after_config,
                "files_before_input": sorted(before_files),
                "files_after_input": sorted(after_files),
                "new_artifacts_after_input": sorted(set(after_files) - set(before_files)),
                "artifact_classes_after_input": artifact_classes(set(after_files)),
                "secrets_file_created": (home / ".env").exists(),
            },
            "scope": {
                "provider_selection_attempted": action in {"enter-local", "space-local", "enter-skip"},
                "credentials_entered": False,
                "oauth_action_sent": False,
                "network_bearing_input_sent": False,
                "later_behavior": "unknown beyond the bounded observation window",
                "forced_teardown_if_alive": "harness cleanup only; not a Hermes product outcome",
            },
        }
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
        "observation_id": "OBS-0085",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "fresh synthetic homes with direct PTY and bounded provider actions",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, PTY paths, credentials, timestamps, PIDs, and raw redraw bytes are omitted or replaced by stable markers.",
            "Each fresh case repeats the established route through the provider inventory, then sends only the named provider action before a bounded observation window.",
            "No credential, OAuth, external network-bearing input, or later setup value is sent; forced teardown is harness cleanup only.",
        ],
        "unknowns": [
            "Behavior after the bounded provider action, complete provider discovery, credentials, OAuth, external network behavior, and durable persistence remain unknown unless directly visible in the recorded window.",
            "A Hermes defect, unsafe behavior, or failure case is reference evidence to fix in Hades, not a compatibility requirement; the observation does not cap Hades performance or capabilities.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        reference = args.reference.resolve()
        if not reference.is_dir():
            raise RuntimeError(f"reference checkout does not exist: {reference}")
        report["cases"] = [
            run_case(reference, action, args.timeout)
            for action in ("enter-local", "space-local", "enter-skip", "escape")
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
