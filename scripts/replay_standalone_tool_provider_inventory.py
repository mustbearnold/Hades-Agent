#!/usr/bin/env python3
"""Replay Hades' bounded standalone Browser Automation provider inventory."""

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

# Reuse the established standalone route and PTY setup without widening its
# provider-selection claim.
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


def spawn_and_record(binary: Path, home: Path) -> tuple[int, int, str]:
    return spawn_setup(binary, home)


def run_case(binary: Path, timeout: float) -> dict[str, object]:
    case = "standalone-tool-provider-inventory"
    home = Path(tempfile.mkdtemp(prefix="hades-standalone-tool-provider-inventory-home-"))
    pid, master, slave_path = spawn_and_record(binary, home)
    output = bytearray()
    reaped = False
    try:
        files_before = file_inventory(home)
        wait_for(
            pid,
            master,
            output,
            f"{case} initial surface",
            lambda text: all(marker_present(text, marker) for marker in INITIAL_MARKERS),
            timeout,
        )
        initial_flags = terminal_flags(slave_path)
        config_before = config_shape(home / "config.yaml")

        send(master, b"j\r")
        wait_for(
            pid,
            master,
            output,
            f"{case} continuation",
            lambda text: all(marker_present(text, marker) for marker in CONTINUATION_MARKERS),
            timeout,
        )
        continuation_flags = terminal_flags(slave_path)

        send(master, b"\x03")
        wait_for(
            pid,
            master,
            output,
            f"{case} terminal backend",
            lambda text: all(marker_present(text, marker) for marker in BACKEND_MARKERS),
            timeout,
        )
        backend_flags = terminal_flags(slave_path)

        send(master, b"\r")
        wait_for(
            pid,
            master,
            output,
            f"{case} platform picker",
            lambda text: all(marker_present(text, marker) for marker in PLATFORM_MARKERS),
            timeout,
        )
        platform_flags = terminal_flags(slave_path)

        send(master, b"\x03")
        wait_for(
            pid,
            master,
            output,
            f"{case} tool configuration",
            lambda text: marker_present(text, "Hermes Tool Configuration"),
            timeout,
        )
        tool_configuration_flags = terminal_flags(slave_path)
        config_at_tool_configuration = config_shape(home / "config.yaml")
        files_at_tool_configuration = file_inventory(home)

        send(master, b"\x1b")
        wait_for(
            pid,
            master,
            output,
            f"{case} checklist",
            lambda text: all(marker_present(text, marker) for marker in CHECKLIST_MARKERS),
            timeout,
        )
        checklist_flags = terminal_flags(slave_path)
        if checklist_flags["canonical"] or checklist_flags["echo"]:
            raise ProbeError(f"checklist did not enter raw mode: {checklist_flags}")

        # Ctrl+C is the only input at the checklist boundary. The provider
        # inventory is then read in the restored canonical/echo surface.
        send(master, b"\x03")
        wait_for(
            pid,
            master,
            output,
            f"{case} provider inventory",
            lambda text: all(
                marker_present(text, marker)
                for marker in (*PROVIDER_BOUNDARY_MARKERS, *PROVIDER_OPTION_MARKERS)
            ),
            timeout,
        )
        provider_flags = terminal_flags(slave_path)
        provider_config = config_shape(home / "config.yaml")
        files_at_provider = file_inventory(home)
        provider_alive = process_alive(pid)
        if not provider_flags["canonical"] or not provider_flags["echo"]:
            raise ProbeError(f"provider inventory did not restore terminal flags: {provider_flags}")
        if not provider_alive:
            raise ProbeError("provider inventory process exited before the bounded read completed")
        if provider_config != config_at_tool_configuration:
            raise ProbeError("provider inventory changed the setup config")
        if (home / ".env").exists():
            raise ProbeError("provider inventory created a secrets file")
        rendered = clean_output(output)
        if "Provider error" in rendered or "HADES_PROVIDER_BASE_URL" in rendered:
            raise ProbeError("provider inventory unexpectedly started provider behavior")

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
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "reach provider inventory"},
            ],
            "surfaces": {
                "initial": {"markers": list(INITIAL_MARKERS), "terminal_flags": initial_flags},
                "continuation": {"markers": list(CONTINUATION_MARKERS), "terminal_flags": continuation_flags},
                "terminal_backend": {"markers": list(BACKEND_MARKERS), "terminal_flags": backend_flags},
                "platform_picker": {"markers": list(PLATFORM_MARKERS), "terminal_flags": platform_flags},
                "tool_configuration": {
                    "marker": "Hermes Tool Configuration",
                    "terminal_flags": tool_configuration_flags,
                },
                "checklist": {"markers": list(CHECKLIST_MARKERS), "terminal_flags": checklist_flags},
                "provider_inventory": {
                    "boundary_markers": list(PROVIDER_BOUNDARY_MARKERS),
                    "option_markers": list(PROVIDER_OPTION_MARKERS),
                    "terminal_flags": provider_flags,
                    "process_still_alive": provider_alive,
                    "selected_option": "Local Browser [★ recommended · free]",
                    "selection_controls_observed": True,
                },
            },
            "persistence": {
                "config_before": config_before,
                "config_at_tool_configuration": config_at_tool_configuration,
                "config_at_provider_inventory": provider_config,
                "config_unchanged_after_tool_boundary": provider_config == config_at_tool_configuration,
                "files_before": files_before,
                "files_at_tool_configuration": files_at_tool_configuration,
                "files_at_provider_inventory": files_at_provider,
                "new_artifacts_after_tool_boundary": sorted(
                    set(files_at_provider) - set(files_at_tool_configuration)
                ),
                "secrets_file_created": False,
            },
            "scope": {
                "provider_selection_submitted": False,
                "credentials_entered": False,
                "oauth_action_sent": False,
                "network_bearing_input_sent": False,
                "later_cancellation": "unknown",
                "replay_teardown": "forced child teardown after the bounded provider read; not a product outcome",
            },
        }
    finally:
        if not reaped:
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
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
        "observation_id": "OBS-0080",
        "probe": "hades-standalone-tool-provider-inventory",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "normalization": [
            "Synthetic HOME/HERMES_HOME paths, PTY paths, timestamps, and raw redraw bytes are omitted or replaced by stable markers.",
            "The route enters only Full setup, skips the provider, accepts the local backend, cancels the platform picker, opens the raw CLI checklist, sends Escape then Ctrl+C, and reads the provider inventory without further input.",
            "Provider selection, credentials, OAuth, network activity, persistence, and later cancellation are not submitted or claimed.",
        ],
        "unknowns": [
            "Provider selection semantics, Enter/Space/Escape behavior, provider discovery timing, credentials, OAuth, network behavior, persistence, and later cancellation remain outside this bounded replay.",
            "Forced child teardown is replay cleanup only and is not a Hades product exit or terminal-restoration claim.",
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
