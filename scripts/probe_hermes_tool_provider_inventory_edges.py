#!/usr/bin/env python3
"""Observe bounded Hermes provider-inventory cursor edge behavior."""

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
)
from probe_hermes_terminal_palette import child_status, write_bytes
from probe_hermes_tool_provider_inventory_interaction import (
    COLUMNS,
    INTERACTION_WINDOW_SECONDS,
    PROVIDER_INVENTORY_MARKERS,
    route_to_provider,
    surface_flags,
)
from probe_hermes_tool_provider_boundary import force_teardown, read_window, safe_tail
from probe_tui_lifecycle import describe_status, release_slave_descriptor


ARROW_INPUTS = {
    "up": b"\x1b[A",
    "down": b"\x1b[B",
}
EDGE_DOWN_COUNT = 8
STEP_WINDOW_SECONDS = 0.35
ROWS = 40
PROVIDER_ROWS = (
    "Local Browser [★ recommended · free]",
    "Nous Subscription (Browser Use cloud)",
    "Camofox [free · local]",
    "Browser Use [paid]",
    "Browserbase [paid]",
    "Firecrawl [paid]",
    "Skip — keep defaults / configure later",
)


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


def run_case(reference: Path, case_id: str, inputs: list[str], timeout: float) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix=f"hades-hermes-provider-inventory-{case_id}-"))
    home = root / "home"
    home.mkdir()
    session = {"pid": -1, "fd": -1}
    try:
        pid, fd, terminal_fd, buffer, route_state = route_to_provider(
            reference, home, timeout, session
        )
        before_config = config_shape(home / "config.yaml")
        before_files = file_inventory(home)
        interaction_steps: list[dict[str, Any]] = []
        for input_name in inputs:
            interaction_offset = len(buffer)
            write_bytes(fd, ARROW_INPUTS[input_name])
            time.sleep(0.05)
            buffer = read_window(fd, buffer, STEP_WINDOW_SECONDS)
            interaction_delta = buffer[interaction_offset:]
            interaction_steps.append(
                {
                    "input": input_name,
                    "bytes_hex": ARROW_INPUTS[input_name].hex(" "),
                    "observation_window_ms": round(STEP_WINDOW_SECONDS * 1000),
                    "cursor_targets": cursor_targets(interaction_delta),
                    "selected_targets": selected_targets(interaction_delta),
                    "screen_delta_tail": safe_tail(interaction_delta),
                }
            )
        interaction_delta = buffer[interaction_offset:]
        exited, status = child_status(pid)
        exit_description = describe_status(status) if exited and status is not None else None
        after_config = config_shape(home / "config.yaml")
        after_files = file_inventory(home)
        flags_after = surface_flags(terminal_fd)
        if exited:
            raise RuntimeError(f"{case_id} unexpectedly exited Hermes: {exit_description}")
        if after_config != before_config:
            raise RuntimeError(f"{case_id} changed the setup config")
        if (home / ".env").exists():
            raise RuntimeError(f"{case_id} created a secrets file")

        return {
            "id": f"provider-inventory-{case_id}",
            "status": "passed",
            "input": [
                {
                    "label": input_name,
                    "bytes_hex": ARROW_INPUTS[input_name].hex(" "),
                    "submitted_provider": False,
                    "credentials_entered": False,
                    "oauth_action_sent": False,
                    "network_bearing_input_sent": False,
                }
                for input_name in inputs
            ],
            "interaction": {
                "observation_window_ms_per_input": round(STEP_WINDOW_SECONDS * 1000),
                "process_alive_after_input": not exited,
                "exit": exit_description,
                "terminal_flags_after_input": flags_after,
                "steps": interaction_steps,
                "cursor_targets_in_delta": cursor_targets(interaction_delta),
                "selected_targets_in_delta": selected_targets(interaction_delta),
                "screen_delta_tail": safe_tail(interaction_delta),
            },
            "route": route_state["route"],
            "persistence": {
                "config_before_input": before_config,
                "config_after_input": after_config,
                "config_unchanged": before_config == after_config,
                "files_before_input": sorted(before_files),
                "files_after_input": sorted(after_files),
                "new_artifacts_after_input": sorted(set(after_files) - set(before_files)),
                "artifact_classes_after_input": artifact_classes(set(after_files)),
                "secrets_file_created": False,
            },
            "scope": {
                "provider_selection_submitted": False,
                "credentials_entered": False,
                "oauth_action_sent": False,
                "network_bearing_input_sent": False,
                "enter_space_escape_ctrl_c_semantics": "unknown",
                "later_behavior": "unknown",
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
        "observation_id": "OBS-0083",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "fresh synthetic home with direct PTY and bounded arrow-only edge cases",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, PTY paths, credentials, timestamps, and raw redraw bytes are omitted or replaced by stable markers.",
            "Each fresh case repeats the safe route through the provider inventory, then sends only the named Up/Down arrow bytes before a bounded read window.",
            "No provider choice, Enter, Space, Escape, Ctrl+C, credential, OAuth action, network-bearing input, or persistence action is sent; forced teardown is harness cleanup only.",
        ],
        "unknowns": [
            "Provider selection, Enter/Space/Escape/Ctrl+C semantics, credential prompts, OAuth, network behavior, persistence, discovery completeness, and behavior after the bounded window remain unknown.",
            "A missing or delayed cursor redraw is recorded as observed uncertainty, not inferred into a Hades contract; Hermes defects and failure cases are not compatibility requirements.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        reference = args.reference.resolve()
        if not reference.is_dir():
            raise RuntimeError(f"reference checkout does not exist: {reference}")
        report["cases"] = [
            run_case(reference, "up-at-initial", ["up"], args.timeout),
            run_case(reference, "down-to-edge", ["down"] * EDGE_DOWN_COUNT, args.timeout),
            run_case(reference, "down-then-up", ["down", "up"], args.timeout),
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
