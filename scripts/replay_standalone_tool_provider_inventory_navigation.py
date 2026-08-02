#!/usr/bin/env python3
"""Replay bounded cyclic arrow navigation in Hades' provider inventory."""

from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_tui_lifecycle import (
    ProbeError,
    clean_output,
    marker_present,
    output_tail,
    read_available,
    release_slave_descriptor,
    send,
    terminal_flags,
    wait_for,
)
from replay_standalone_tool_provider_boundary import (
    BACKEND_MARKERS,
    CHECKLIST_MARKERS,
    CONTINUATION_MARKERS,
    INITIAL_MARKERS,
    PLATFORM_MARKERS,
    config_shape,
    file_inventory,
    process_alive,
    spawn_setup,
)


COLUMNS = 120
ROWS = 40
PROVIDER_BOUNDARY_MARKERS = (
    "Configuring 6 tool(s):",
    "Browser Automation - Choose a provider",
    "Choose a provider:",
    "↑↓ navigate  ENTER/SPACE select  ESC cancel",
)
PROVIDER_OPTION_MARKERS = (
    "Local Browser [★ recommended · free]",
    "Nous Subscription (Browser Use cloud)",
    "Camofox [free · local]",
    "Browser Use [paid]",
    "Browserbase [paid]",
    "Firecrawl [paid]",
    "Skip — keep defaults / configure later",
)
SELECTED_LOCAL_MARKER = "(●) Local Browser"
ROUTE_INPUT = [
    {"kind": "key", "value": "j", "bytes_hex": "6a", "meaning": "move to Full setup"},
    {"kind": "key", "value": "Enter", "bytes_hex": "0d", "meaning": "submit Full setup"},
    {
        "kind": "key",
        "value": "Ctrl+C",
        "bytes_hex": "03",
        "meaning": "skip the unconfigured provider",
    },
    {
        "kind": "key",
        "value": "Enter",
        "bytes_hex": "0d",
        "meaning": "accept Keep current (local)",
    },
    {
        "kind": "key",
        "value": "Ctrl+C",
        "bytes_hex": "03",
        "meaning": "cancel the platform picker",
    },
    {
        "kind": "key",
        "value": "Escape",
        "bytes_hex": "1b",
        "meaning": "open the raw CLI checklist",
    },
    {
        "kind": "key",
        "value": "Ctrl+C",
        "bytes_hex": "03",
        "meaning": "reach the provider inventory",
    },
]


def navigation_input(value: str, bytes_hex: str, cursor: str) -> dict[str, str]:
    return {
        "kind": "key",
        "value": value,
        "bytes_hex": bytes_hex,
        "meaning": "move the provider cursor without submitting a provider",
        "expected_cursor": cursor,
    }


NAVIGATION_CASES: tuple[tuple[str, tuple[dict[str, str], ...]], ...] = (
    (
        "up-from-initial-wraps-to-skip",
        (
            navigation_input(
                "Up",
                "1b 5b 41",
                "Skip — keep defaults / configure later",
            ),
        ),
    ),
    (
        "down-from-skip-wraps-to-local-browser",
        tuple(
            navigation_input("Down", "1b 5b 42", cursor)
            for cursor in (
                "Nous Subscription (Browser Use cloud)",
                "Camofox",
                "Browser Use",
                "Browserbase",
                "Firecrawl",
                "Skip — keep defaults / configure later",
                "Local Browser",
            )
        ),
    ),
    (
        "down-then-up-returns-to-local-browser",
        (
            navigation_input("Down", "1b 5b 42", "Nous Subscription (Browser Use cloud)"),
            navigation_input("Up", "1b 5b 41", "Local Browser"),
        ),
    ),
)


def wait_for_delta(
    pid: int,
    master: int,
    output: bytearray,
    raw_offset: int,
    description: str,
    predicate: Any,
    timeout: float,
) -> str:
    """Wait for a marker in bytes emitted after one navigation input."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        read_available(master, output)
        delta = clean_output(bytearray(bytes(output)[raw_offset:]))
        if predicate(delta):
            return delta
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            raise ProbeError(
                f"{description}: process exited early with status {status}\n{output_tail(output)}"
            )
        remaining = deadline - time.monotonic()
        if remaining > 0:
            select.select([master], [], [], min(0.05, remaining))
    read_available(master, output)
    delta = clean_output(bytearray(bytes(output)[raw_offset:]))
    raise ProbeError(f"{description}: timed out\n{delta[-1200:]}")


def route_to_provider_inventory(
    binary: Path,
    home: Path,
    timeout: float,
) -> tuple[int, int, str, bytearray]:
    pid, master, slave_path = spawn_setup(binary, home)
    output = bytearray()
    wait_for(
        pid,
        master,
        output,
        "navigation initial surface",
        lambda text: all(marker_present(text, marker) for marker in INITIAL_MARKERS),
        timeout,
    )
    send(master, b"j\r")
    wait_for(
        pid,
        master,
        output,
        "navigation continuation",
        lambda text: all(marker_present(text, marker) for marker in CONTINUATION_MARKERS),
        timeout,
    )
    send(master, b"\x03")
    wait_for(
        pid,
        master,
        output,
        "navigation terminal backend",
        lambda text: all(marker_present(text, marker) for marker in BACKEND_MARKERS),
        timeout,
    )
    send(master, b"\r")
    wait_for(
        pid,
        master,
        output,
        "navigation platform picker",
        lambda text: all(marker_present(text, marker) for marker in PLATFORM_MARKERS),
        timeout,
    )
    send(master, b"\x03")
    wait_for(
        pid,
        master,
        output,
        "navigation tool configuration",
        lambda text: marker_present(text, "Hermes Tool Configuration"),
        timeout,
    )
    send(master, b"\x1b")
    wait_for(
        pid,
        master,
        output,
        "navigation checklist",
        lambda text: all(marker_present(text, marker) for marker in CHECKLIST_MARKERS),
        timeout,
    )
    send(master, b"\x03")
    wait_for(
        pid,
        master,
        output,
        "navigation provider inventory",
        lambda text: all(
            marker_present(text, marker)
            for marker in (*PROVIDER_BOUNDARY_MARKERS, *PROVIDER_OPTION_MARKERS)
        ),
        timeout,
    )
    return pid, master, slave_path, output


def cursor_marker(cursor: str) -> str:
    selected = "●" if cursor == "Local Browser" else "○"
    return f"→ ({selected}) {cursor}"


def run_case(
    binary: Path,
    case_id: str,
    navigation: tuple[dict[str, str], ...],
    timeout: float,
) -> dict[str, object]:
    home = Path(tempfile.mkdtemp(prefix="hades-standalone-tool-provider-navigation-home-"))
    pid = -1
    master = -1
    slave_path: str | None = None
    output = bytearray()
    try:
        pid, master, slave_path, output = route_to_provider_inventory(binary, home, timeout)
        config_before_input = config_shape(home / "config.yaml")
        files_before_input = file_inventory(home)
        provider_flags = terminal_flags(slave_path)
        if provider_flags["canonical"] or provider_flags["echo"]:
            raise ProbeError(f"provider inventory did not enter raw mode: {provider_flags}")
        if not process_alive(pid):
            raise ProbeError("provider inventory process exited before navigation")

        trace: list[dict[str, object]] = []
        for index, step in enumerate(navigation):
            raw_offset = len(output)
            send(master, bytes.fromhex(step["bytes_hex"]))
            expected_marker = cursor_marker(step["expected_cursor"])
            delta = wait_for_delta(
                pid,
                master,
                output,
                raw_offset,
                f"{case_id} navigation step {index + 1}",
                lambda text, marker=expected_marker: marker_present(text, marker),
                timeout,
            )
            flags = terminal_flags(slave_path)
            alive = process_alive(pid)
            if flags["canonical"] or flags["echo"]:
                raise ProbeError(f"{case_id} left raw mode after {step['value']}: {flags}")
            if not alive:
                raise ProbeError(f"{case_id} process exited after {step['value']}")
            accumulated = clean_output(output)
            if not marker_present(accumulated, SELECTED_LOCAL_MARKER):
                raise ProbeError(
                    f"{case_id} changed the selected provider after {step['value']}"
                )
            trace.append(
                {
                    "input": {
                        key: value
                        for key, value in step.items()
                        if key != "expected_cursor"
                    },
                    "cursor": step["expected_cursor"],
                    "rendered_markers": [expected_marker, SELECTED_LOCAL_MARKER],
                    "terminal_flags": flags,
                    "process_alive": alive,
                    "delta_marker_observed": marker_present(delta, expected_marker),
                    "selected_local_marker_observed": marker_present(
                        accumulated, SELECTED_LOCAL_MARKER
                    ),
                }
            )

        config_after_input = config_shape(home / "config.yaml")
        files_after_input = file_inventory(home)
        if config_after_input != config_before_input:
            raise ProbeError(f"{case_id} navigation changed setup config")
        if set(files_after_input) - set(files_before_input):
            raise ProbeError(f"{case_id} navigation created an artifact")
        if (home / ".env").exists():
            raise ProbeError(f"{case_id} navigation created a secrets file")
        rendered = clean_output(output)
        if "Provider error" in rendered or "HADES_PROVIDER_BASE_URL" in rendered:
            raise ProbeError(f"{case_id} unexpectedly started provider behavior")

        return {
            "id": case_id,
            "status": "passed",
            "input": {
                "route": ROUTE_INPUT,
                "navigation": [
                    {
                        key: value
                        for key, value in step.items()
                        if key != "expected_cursor"
                    }
                    for step in navigation
                ],
            },
            "surfaces": {
                "provider_inventory": {
                    "boundary_markers": list(PROVIDER_BOUNDARY_MARKERS),
                    "option_markers": list(PROVIDER_OPTION_MARKERS),
                    "cursor_before": "Local Browser",
                    "selected_before": "Local Browser",
                    "trace": trace,
                    "cursor_after": trace[-1]["cursor"],
                    "selected_after": "Local Browser",
                },
                "terminal_flags": {
                    "provider_inventory_before_navigation": provider_flags,
                    "provider_inventory_after_navigation": trace[-1]["terminal_flags"],
                },
                "alternate_screen": {
                    "entered": b"\x1b[?1049h" in output,
                    "left_before_provider_interaction": b"\x1b[?1049l" in output,
                },
                "process_alive_after_navigation": trace[-1]["process_alive"],
            },
            "persistence": {
                "config_before_input": config_before_input,
                "config_after_input": config_after_input,
                "config_unchanged": config_before_input == config_after_input,
                "files_before_input": files_before_input,
                "files_after_input": files_after_input,
                "new_artifacts_after_input": sorted(
                    set(files_after_input) - set(files_before_input)
                ),
                "secrets_file_created": False,
            },
            "scope": {
                "provider_selection_submitted": False,
                "credentials_entered": False,
                "oauth_action_sent": False,
                "network_bearing_input_sent": False,
                "enter_space_escape_semantics": "outside this bounded navigation replay",
                "ctrl_c_behavior": "outside this bounded navigation replay",
                "replay_teardown": "forced child teardown after the bounded read; not a product outcome",
            },
        }
    finally:
        if pid > 0:
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
    report: dict[str, object] = {
        "schema_version": 1,
        "observation_id": "OBS-0084",
        "probe": "hades-standalone-tool-provider-inventory-navigation-edges",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "normalization": [
            "Synthetic HOME/HERMES_HOME paths, PTY paths, timestamps, raw redraw bytes, and full rendered buffers are omitted or represented by stable markers.",
            "Each fresh route reaches the provider inventory and sends only the bounded arrow sequence for its case; no provider choice, credential, OAuth, network-bearing, or persistence action is sent.",
            "Forced child teardown is replay cleanup only and is not a Hades product exit, cancellation, or failure-case claim.",
        ],
        "unknowns": [
            "Provider submission, Enter/Space/Escape semantics, Ctrl+C behavior, credentials, OAuth, network behavior, persistence, discovery completeness, and later provider setup remain outside this replay.",
            "The ambiguous Hermes Ctrl+C cross-tool redraw is not copied into Hades and is not part of this contract.",
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
            run_case(binary, case_id, navigation, args.timeout)
            for case_id, navigation in NAVIGATION_CASES
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
