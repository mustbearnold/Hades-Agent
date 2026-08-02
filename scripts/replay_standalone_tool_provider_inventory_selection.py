#!/usr/bin/env python3
"""Replay Hades' safe provider-inventory action boundary."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_tui_lifecycle import (
    ProbeError,
    clean_output,
    describe_status,
    marker_present,
    release_slave_descriptor,
    send,
    terminal_flags,
    wait_for,
    wait_for_exit,
)
from replay_standalone_tool_provider_boundary import (
    config_shape,
    file_inventory,
    process_alive,
)
from replay_standalone_tool_provider_inventory_navigation import (
    PROVIDER_BOUNDARY_MARKERS,
    PROVIDER_OPTION_MARKERS,
    ROUTE_INPUT,
    route_to_provider_inventory,
)


COLUMNS = 120
ROWS = 40
SELECTED_LOCAL_MARKER = "(●) Local Browser"
SAFE_ACTION_CASES: tuple[tuple[str, str, bytes, str], ...] = (
    (
        "enter-local-browser",
        "Enter",
        b"\r",
        "✓ Local Browser selected; no implicit installation or network activity started.",
    ),
    (
        "space-local-browser",
        "Space",
        b" ",
        "✓ Local Browser selected; no implicit installation or network activity started.",
    ),
    (
        "enter-skip",
        "Enter",
        b"\r",
        "✓ Browser Automation skipped; no implicit installation or network activity started.",
    ),
    (
        "escape-cancel",
        "Escape",
        b"\x1b",
        "✓ Provider selection cancelled; no configuration or network activity started.",
    ),
)


def route_to_skip(pid: int, master: int, output: bytearray, timeout: float) -> list[str]:
    cursor_trace: list[str] = []
    for cursor in (
        "Nous Subscription (Browser Use cloud)",
        "Camofox",
        "Browser Use",
        "Browserbase",
        "Firecrawl",
        "Skip — keep defaults / configure later",
    ):
        send(master, b"\x1b[B")
        wait_for(
            pid,
            master,
            output,
            "provider selection navigation",
            lambda text, expected=f"→ (○) {cursor}": marker_present(text, expected),
            timeout,
        )
        cursor_trace.append(cursor)
    return cursor_trace


def run_case(
    binary: Path,
    case_id: str,
    label: str,
    payload: bytes,
    expected_status: str,
    timeout: float,
) -> dict[str, object]:
    home = Path(tempfile.mkdtemp(prefix=f"hades-standalone-tool-provider-action-{case_id}-"))
    pid = -1
    master = -1
    slave_path: str | None = None
    output = bytearray()
    reaped = False
    try:
        pid, master, slave_path, output = route_to_provider_inventory(binary, home, timeout)
        provider_flags = terminal_flags(slave_path)
        if provider_flags["canonical"] or provider_flags["echo"]:
            raise ProbeError(f"{case_id}: provider inventory did not enter raw mode: {provider_flags}")
        if not process_alive(pid):
            raise ProbeError(f"{case_id}: provider inventory process exited before action")
        config_before = config_shape(home / "config.yaml")
        files_before = file_inventory(home)
        cursor_trace: list[str] = []
        if case_id == "enter-skip":
            cursor_trace = route_to_skip(pid, master, output, timeout)

        raw_offset = len(output)
        send(master, payload)
        wait_for(
            pid,
            master,
            output,
            f"{case_id} safe action status",
            lambda text: marker_present(text, expected_status),
            timeout,
        )
        flags_after_action = terminal_flags(slave_path)
        alive_after_action = process_alive(pid)
        if not flags_after_action["canonical"] or not flags_after_action["echo"]:
            raise ProbeError(f"{case_id}: action did not restore terminal input: {flags_after_action}")
        if not alive_after_action:
            raise ProbeError(f"{case_id}: process exited after safe action")

        config_after = config_shape(home / "config.yaml")
        files_after = file_inventory(home)
        new_files = sorted(set(files_after) - set(files_before))
        if config_after != config_before:
            raise ProbeError(f"{case_id}: safe action changed setup config")
        if new_files:
            raise ProbeError(f"{case_id}: safe action created artifacts: {new_files}")
        rendered = clean_output(output)
        forbidden_side_effect_markers = (
            "Provider error",
            "HADES_PROVIDER_BASE_URL",
            "curl",
            "installing cua-driver",
            "downloading",
        )
        if any(marker in rendered for marker in forbidden_side_effect_markers):
            raise ProbeError(f"{case_id}: unsafe provider side effect marker appeared")

        send(master, b"\x03")
        status = wait_for_exit(pid, master, output, timeout)
        reaped = True
        exit_status = describe_status(status)
        if exit_status != {"kind": "exit", "code": 130}:
            raise ProbeError(f"{case_id}: unexpected cleanup exit: {exit_status}")
        cleanup_flags = terminal_flags(slave_path)
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeError(f"{case_id}: terminal was not restored after cleanup: {cleanup_flags}")

        return {
            "id": case_id,
            "status": "passed",
            "input": {
                "route": ROUTE_INPUT,
                "action": {
                    "kind": "key",
                    "value": label,
                    "bytes_hex": payload.hex(" "),
                    "meaning": "bounded safe provider action",
                },
                "cursor_trace": cursor_trace,
            },
            "provider_inventory": {
                "boundary_markers": list(PROVIDER_BOUNDARY_MARKERS),
                "option_markers": list(PROVIDER_OPTION_MARKERS),
                "cursor_before": "Local Browser" if not cursor_trace else cursor_trace[-1],
                "selected_before": "Local Browser",
                "selected_local_marker_observed": marker_present(
                    clean_output(output[:raw_offset]), SELECTED_LOCAL_MARKER
                ),
                "status_marker": expected_status,
            },
            "action_result": {
                "status_marker_observed": marker_present(clean_output(output), expected_status),
                "terminal_flags_before_action": provider_flags,
                "terminal_flags_after_action": flags_after_action,
                "process_alive_after_action": alive_after_action,
                "clean_exit": exit_status,
                "cleanup_terminal_flags": cleanup_flags,
                "alternate_screen_entered": b"\x1b[?1049h" in output,
                "alternate_screen_left_before_provider_action": b"\x1b[?1049l" in output,
                "config_unchanged": config_before == config_after,
                "new_artifacts": new_files,
                "forbidden_side_effect_markers_observed": [],
            },
            "persistence": {
                "config_before_action": config_before,
                "config_after_action": config_after,
                "files_before_action": files_before,
                "files_after_action": files_after,
                "secrets_file_created": False,
            },
            "scope": {
                "credentials_entered": False,
                "oauth_action_sent": False,
                "network_bearing_input_sent": False,
                "provider_subprocess_started": False,
                "later_provider_setup": "unknown",
                "cleanup": "one Ctrl+C after bounded readback; expected exit 130",
            },
        }
    finally:
        if pid > 0 and not reaped:
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        if master >= 0:
            os.close(master)
        if slave_path is not None:
            release_slave_descriptor(slave_path)
        shutil.rmtree(home, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", default="target/debug/hades")
    parser.add_argument("--report")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()
    binary = Path(args.binary).resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0086",
        "probe": "hades-standalone-tool-provider-inventory-selection",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "normalization": [
            "Synthetic HOME/HERMES_HOME paths, PTY paths, timestamps, raw redraw bytes, and full buffers are omitted or represented by stable markers.",
            "Each fresh route reaches the provider inventory and sends exactly one bounded safe action, with six Down bytes before Enter only in the Skip case; no credential, OAuth, network-bearing, or persistence action is sent.",
            "The replay requires canonical input/echo restoration, process liveness until explicit Ctrl+C cleanup, unchanged config/artifacts, and absence of Hermes' implicit installer/network markers.",
        ],
        "unknowns": [
            "Paid/provider-specific selection, credentials, OAuth, discovery, persistence, later setup, and real browser capability remain outside this safe action boundary.",
            "Hermes' implicit background installer/network side effect is deliberately not reproduced and is not part of the Hades contract; this replay does not cap Hades performance or safer capabilities.",
        ],
        "cases": [],
        "passed": False,
    }
    if not binary.is_file():
        report["error"] = "Hades binary not found"
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2

    try:
        report["cases"] = [
            run_case(binary, case_id, label, payload, expected_status, args.timeout)
            for case_id, label, payload, expected_status in SAFE_ACTION_CASES
        ]
        report["passed"] = True
    except (OSError, ProbeError) as error:
        report["error"] = str(error)

    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
