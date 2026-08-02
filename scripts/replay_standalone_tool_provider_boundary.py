#!/usr/bin/env python3
"""Replay Hades' bounded standalone tool-checklist/provider boundary."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from probe_tui_lifecycle import (
    ProbeError,
    clean_output,
    marker_present,
    read_available,
    send,
    set_window_size,
    terminal_flags,
    wait_for,
)


COLUMNS = 120
ROWS = 40
INITIAL_MARKERS = (
    "Hermes Agent Setup Wizard",
    "Let's configure your Hermes Agent installation.",
    "Press Ctrl+C at any time to exit.",
    "How would you like to set up Hermes?",
    "Quick Setup (Nous Portal)",
    "Full setup",
    "Blank Slate",
    "ESC cancel",
)
CONTINUATION_MARKERS = (
    "Configuration Location",
    "Config file:",
    "Secrets file:",
    "Data folder:",
    "Install dir:",
    "Inference Provider",
    "Choose how to connect to your main chat model.",
)
BACKEND_MARKERS = ("Select terminal backend:", "Keep current (local)")
PLATFORM_MARKERS = ("Mattermost", "Signal", "WhatsApp", "(not configured)")
TOOL_CONFIGURATION_MARKERS = (
    "No platforms selected. Run 'hermes setup gateway' later to configure.",
    "Hermes Tool Configuration",
    "Enable or disable tools per platform.",
    "Tools that need API keys will be configured when enabled.",
)
CHECKLIST_MARKERS = (
    "Tools for 🖥️  CLI",
    "SPACE toggle",
    "ENTER confirm",
    "ESC cancel",
    "Web Search & Scraping",
    "Browser Automation",
    "Terminal & Processes",
    "File Operations",
)
PROVIDER_MARKERS = (
    "Configuring 6 tool(s):",
    "Browser Automation",
    "Computer Use (macOS/Windows/Linux)",
    "Image Generation",
    "Text-to-Speech",
    "Vision / Image Analysis",
    "Web Search & Scraping",
    "Browser Automation - Choose a provider",
)


def spawn_setup(binary: Path, home: Path) -> tuple[int, int, str]:
    import pty

    pid, master = pty.fork()
    if pid == 0:
        try:
            set_window_size(0, COLUMNS, ROWS)
            environment = os.environ.copy()
            environment.update(
                {
                    "TERM": "xterm-256color",
                    "COLUMNS": str(COLUMNS),
                    "LINES": str(ROWS),
                    "HOME": str(home),
                    "HERMES_HOME": str(home),
                }
            )
            for key in (
                "HADES_PROVIDER_BASE_URL",
                "HADES_PROVIDER_API_KEY",
                "HADES_MODEL",
                "OPENAI_BASE_URL",
                "OPENAI_API_KEY",
            ):
                environment.pop(key, None)
            os.execvpe(str(binary), [str(binary), "setup"], environment)
        except BaseException as error:
            os.write(2, f"standalone tool-provider replay child failed: {error}\n".encode())
            os._exit(127)

    set_window_size(master, COLUMNS, ROWS)
    os.set_blocking(master, False)
    return pid, master, os.readlink(f"/proc/{pid}/fd/0")


def config_shape(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"exists": False, "bytes": 0}
    text = path.read_text(encoding="utf-8")
    return {
        "exists": True,
        "bytes": len(text.encode("utf-8")),
        "contains_non_secret_baseline": "mode: full" in text and "provider: unconfigured" in text,
        "contains_credential_like_field": any(
            marker in text.lower() for marker in ("api_key", "oauth", "token")
        ),
    }


def file_inventory(root: Path) -> list[str]:
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
    )


def process_alive(pid: int) -> bool:
    done, _ = os.waitpid(pid, os.WNOHANG)
    return not done


def run_case(binary: Path, timeout: float) -> dict[str, object]:
    home = Path(tempfile.mkdtemp(prefix="hades-standalone-tool-provider-home-"))
    pid, master, slave_path = spawn_setup(binary, home)
    output = bytearray()
    reaped = False
    try:
        files_before = file_inventory(home)
        wait_for(
            pid,
            master,
            output,
            "standalone tool-provider initial surface",
            lambda text: all(marker_present(text, marker) for marker in INITIAL_MARKERS),
            timeout,
        )
        initial_flags = terminal_flags(slave_path)
        if initial_flags["canonical"] or initial_flags["echo"]:
            raise ProbeError(f"initial setup surface did not enter raw mode: {initial_flags}")
        config_before = config_shape(home / "config.yaml")

        send(master, b"j\r")
        wait_for(
            pid,
            master,
            output,
            "standalone Full setup continuation",
            lambda text: all(marker_present(text, marker) for marker in CONTINUATION_MARKERS),
            timeout,
        )
        continuation_flags = terminal_flags(slave_path)
        config_at_continuation = config_shape(home / "config.yaml")

        send(master, b"\x03")
        wait_for(
            pid,
            master,
            output,
            "standalone terminal backend",
            lambda text: all(marker_present(text, marker) for marker in BACKEND_MARKERS),
            timeout,
        )
        backend_flags = terminal_flags(slave_path)

        send(master, b"\r")
        wait_for(
            pid,
            master,
            output,
            "standalone platform picker",
            lambda text: all(marker_present(text, marker) for marker in PLATFORM_MARKERS),
            timeout,
        )
        platform_flags = terminal_flags(slave_path)
        leaves_before_platform_cancel = bytes(output).count(b"\x1b[?1049l")

        send(master, b"\x03")
        wait_for(
            pid,
            master,
            output,
            "standalone plain Tool Configuration boundary",
            lambda text: all(marker_present(text, marker) for marker in TOOL_CONFIGURATION_MARKERS),
            timeout,
        )
        tool_configuration_flags = terminal_flags(slave_path)
        if not tool_configuration_flags["canonical"] or not tool_configuration_flags["echo"]:
            raise ProbeError(
                "plain Tool Configuration boundary did not restore canonical input and echo: "
                f"{tool_configuration_flags}"
            )
        leaves_after_platform_cancel = bytes(output).count(b"\x1b[?1049l")
        if leaves_after_platform_cancel <= leaves_before_platform_cancel:
            raise ProbeError("platform cancellation did not leave the alternate screen")
        config_at_tool_configuration = config_shape(home / "config.yaml")
        files_at_tool_configuration = file_inventory(home)

        checklist_offset = len(clean_output(output))
        send(master, b"\x1b")
        wait_for(
            pid,
            master,
            output,
            "standalone raw tool checklist",
            lambda text: all(
                marker_present(text[output_marker_offset:], marker)
                for output_marker_offset in (checklist_offset,)
                for marker in CHECKLIST_MARKERS
            ),
            timeout,
        )
        checklist_flags = terminal_flags(slave_path)
        if checklist_flags["canonical"] or checklist_flags["echo"]:
            raise ProbeError(f"tool checklist did not enter raw mode: {checklist_flags}")
        if not process_alive(pid):
            raise ProbeError("tool checklist process exited before bounded navigation")

        navigation_offset = len(output)
        send(master, b"j")
        time.sleep(0.10)
        navigation_bytes = bytes(output)[navigation_offset:]
        if not process_alive(pid):
            raise ProbeError("j unexpectedly exited the tool checklist process")
        if any(marker.encode("utf-8") in navigation_bytes for marker in PROVIDER_MARKERS):
            raise ProbeError("j unexpectedly crossed the provider boundary")
        navigation_flags = terminal_flags(slave_path)

        provider_offset = len(output)
        send(master, b"\x03")
        provider_deadline = time.monotonic() + 0.20
        while time.monotonic() < provider_deadline:
            read_available(master, output)
            provider_text = clean_output(bytes(output)[provider_offset:])
            if all(marker_present(provider_text, marker) for marker in PROVIDER_MARKERS):
                break
            time.sleep(0.01)
        provider_bytes = bytes(output)[provider_offset:]
        provider_text = clean_output(provider_bytes)
        provider_markers = {
            marker: marker_present(provider_text, marker) for marker in PROVIDER_MARKERS
        }
        if not all(provider_markers.values()):
            raise ProbeError(
                f"provider boundary markers did not render: {provider_markers}\n"
                f"tail={provider_text[-1200:]}"
            )
        provider_flags = terminal_flags(slave_path)
        if not provider_flags["canonical"] or not provider_flags["echo"]:
            raise ProbeError(f"provider boundary did not restore terminal flags: {provider_flags}")
        provider_alive = process_alive(pid)
        if not provider_alive:
            raise ProbeError("checklist Ctrl+C unexpectedly exited at the provider boundary")

        config_at_provider_boundary = config_shape(home / "config.yaml")
        files_at_provider_boundary = file_inventory(home)
        if config_at_provider_boundary != config_at_tool_configuration:
            raise ProbeError("bounded checklist/provider route changed the setup config")
        if (home / ".env").exists():
            raise ProbeError("bounded checklist/provider route created a secrets file")
        cleaned = clean_output(output)
        if "Provider error" in cleaned or "HADES_PROVIDER_BASE_URL" in cleaned:
            raise ProbeError("bounded standalone setup unexpectedly started provider behavior")

        return {
            "case": "standalone-tool-provider-boundary",
            "arguments": ["setup"],
            "dimensions": {"columns": COLUMNS, "rows": ROWS},
            "startup": {"markers": list(INITIAL_MARKERS), "terminal_flags": initial_flags},
            "continuation": {
                "markers": list(CONTINUATION_MARKERS),
                "terminal_flags": continuation_flags,
                "config": config_at_continuation,
            },
            "terminal_backend": {"markers": list(BACKEND_MARKERS), "terminal_flags": backend_flags},
            "platform_picker": {"markers": list(PLATFORM_MARKERS), "terminal_flags": platform_flags},
            "tool_configuration": {
                "markers": list(TOOL_CONFIGURATION_MARKERS),
                "terminal_flags": tool_configuration_flags,
                "process_still_alive": True,
            },
            "checklist": {
                "markers": list(CHECKLIST_MARKERS),
                "terminal_flags": checklist_flags,
                "process_still_alive": True,
                "navigation": {
                    "key": "j",
                    "bytes_hex": "6a",
                    "terminal_flags": navigation_flags,
                    "mutated_selection": False,
                    "confirmed_tool": False,
                    "provider_boundary_crossed": False,
                    "observation_window_ms": 100,
                },
            },
            "provider_boundary": {
                "markers": list(PROVIDER_MARKERS),
                "markers_in_delta": provider_markers,
                "terminal_flags": provider_flags,
                "process_still_alive": provider_alive,
                "provider_choice_submitted": False,
            },
            "cancellation": {
                "input": [
                    "j",
                    "Enter",
                    "Ctrl+C (skip provider)",
                    "Enter (accept Keep current local backend)",
                    "Ctrl+C (leave platform picker)",
                    "Escape (open raw tool checklist)",
                    "j (non-mutating navigation)",
                    "Ctrl+C (bounded provider handoff)",
                ],
                "alternate_screen_entered": b"\x1b[?1049h" in bytes(output),
                "alternate_screen_left_before_checklist": leaves_after_platform_cancel
                > leaves_before_platform_cancel,
                "credentials_entered": False,
                "oauth_started": False,
                "network_requested": False,
                "later_cancellation_status": "unknown; replay stops at the provider boundary",
                "replay_teardown": "forced child teardown after the bounded evidence window; not a product outcome",
            },
            "persistence": {
                "config_before": config_before,
                "config_at_tool_configuration": config_at_tool_configuration,
                "config_at_provider_boundary": config_at_provider_boundary,
                "config_unchanged_through_provider_boundary": config_at_provider_boundary
                == config_at_tool_configuration,
                "files_before": files_before,
                "files_at_tool_configuration": files_at_tool_configuration,
                "files_at_provider_boundary": files_at_provider_boundary,
                "secrets_file_created": False,
            },
            "status": "passed",
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
        "observation_id": "OBS-0078",
        "probe": "hades-standalone-tool-provider-boundary",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "normalization": [
            "Synthetic HOME/HERMES_HOME paths, PTY paths, timestamps, and raw redraw bytes are omitted or replaced by stable markers.",
            "The safe route enters only Full setup, skips the provider, accepts the local backend, cancels the platform picker, opens the raw CLI checklist, sends one non-mutating j, sends one Ctrl+C, and stops at the first provider boundary.",
            "Provider choice, API keys, OAuth, network activity, tool persistence, and later cancellation are not submitted or claimed.",
        ],
        "unknowns": [
            "Provider inventories, provider selection semantics, API-key prompts, OAuth, network behavior, tool persistence, and later cancellation remain outside this bounded replay.",
            "The forced child teardown is replay cleanup only and is not a Hades product exit or terminal-restoration claim.",
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
