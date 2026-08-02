#!/usr/bin/env python3
"""Replay bounded arrow navigation in Hades' provider inventory."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from probe_tui_lifecycle import (
    ProbeError,
    clean_output,
    marker_present,
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
NAVIGATION_CURSOR_MARKER = "→ (○) Nous Subscription"
SELECTED_LOCAL_MARKER = "(●) Local Browser"


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


def run_case(binary: Path, timeout: float) -> dict[str, object]:
    home = Path(tempfile.mkdtemp(prefix="hades-standalone-tool-provider-navigation-home-"))
    pid = -1
    master = -1
    try:
        pid, master, slave_path, output = route_to_provider_inventory(binary, home, timeout)
        config_before_input = config_shape(home / "config.yaml")
        files_before_input = file_inventory(home)
        provider_flags = terminal_flags(slave_path)
        rendered_before = clean_output(output)
        if provider_flags["canonical"] or provider_flags["echo"]:
            raise ProbeError(f"provider inventory did not enter raw mode: {provider_flags}")
        if not process_alive(pid):
            raise ProbeError("provider inventory process exited before navigation")

        send(master, b"\x1b[B")
        wait_for(
            pid,
            master,
            output,
            "provider inventory Down navigation",
            lambda text: marker_present(text, NAVIGATION_CURSOR_MARKER)
            and marker_present(text, SELECTED_LOCAL_MARKER),
            timeout,
        )
        rendered_after = clean_output(output)
        navigation_flags = terminal_flags(slave_path)
        config_after_input = config_shape(home / "config.yaml")
        files_after_input = file_inventory(home)
        alive_after_input = process_alive(pid)
        if navigation_flags["canonical"] or navigation_flags["echo"]:
            raise ProbeError(f"provider inventory left raw mode after Down: {navigation_flags}")
        if not alive_after_input:
            raise ProbeError("provider inventory process exited after Down navigation")
        if config_after_input != config_before_input:
            raise ProbeError("Down navigation changed setup config")
        if set(files_after_input) - set(files_before_input):
            raise ProbeError("Down navigation created an artifact")
        if (home / ".env").exists():
            raise ProbeError("Down navigation created a secrets file")
        if "Provider error" in rendered_after or "HADES_PROVIDER_BASE_URL" in rendered_after:
            raise ProbeError("Down navigation unexpectedly started provider behavior")

        return {
            "id": "down-navigation",
            "status": "passed",
            "input": {
                "route": [
                    {"value": "j", "bytes_hex": "6a"},
                    {"value": "Enter", "bytes_hex": "0d"},
                    {"value": "Ctrl+C", "bytes_hex": "03"},
                    {"value": "Enter", "bytes_hex": "0d"},
                    {"value": "Ctrl+C", "bytes_hex": "03"},
                    {"value": "Escape", "bytes_hex": "1b"},
                    {"value": "Ctrl+C", "bytes_hex": "03"},
                ],
                "navigation": {
                    "value": "Down",
                    "bytes_hex": "1b 5b 42",
                    "meaning": "move the provider cursor without submitting a provider",
                },
            },
            "surfaces": {
                "provider_inventory": {
                    "boundary_markers": list(PROVIDER_BOUNDARY_MARKERS),
                    "option_markers": list(PROVIDER_OPTION_MARKERS),
                    "cursor_before": "Local Browser",
                    "selected_before": "Local Browser",
                    "cursor_after": "Nous Subscription (Browser Use cloud)",
                    "selected_after": "Local Browser",
                    "rendered_before_navigation": rendered_before,
                    "rendered_after_navigation": rendered_after,
                    "terminal_flags_before_navigation": provider_flags,
                    "terminal_flags_after_navigation": navigation_flags,
                    "process_alive_after_navigation": alive_after_input,
                },
                "alternate_screen": {
                    "entered": b"\x1b[?1049h" in output,
                    "left_before_provider_interaction": b"\x1b[?1049l" in output,
                },
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
                "enter_space_escape_semantics": "unknown",
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
        "observation_id": "OBS-0082",
        "probe": "hades-standalone-tool-provider-inventory-navigation",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "normalization": [
            "Synthetic HOME/HERMES_HOME paths, PTY paths, timestamps, raw redraw bytes, and full rendered buffers are omitted or represented by stable markers in the fixture.",
            "The route sends only the bounded setup inputs followed by Down (ESC [ B); no provider choice, credentials, OAuth action, network-bearing input, or persistence action is sent.",
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
        report["cases"] = [run_case(binary, args.timeout)]
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
