#!/usr/bin/env python3
"""Replay the bounded empty-platform confirmation boundary in Hades setup."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import replay_standalone_terminal_platform as platform_replay
from probe_tui_lifecycle import (
    ProbeError,
    clean_output,
    describe_status,
    marker_present,
    read_available,
    send,
    terminal_flags,
    wait_for,
    wait_for_exit,
)


SAFE_MARKERS = platform_replay.PLATFORM_MARKERS
TOOL_MARKERS = platform_replay.TOOL_CONFIGURATION_MARKERS
COLUMNS = platform_replay.COLUMNS
ROWS = platform_replay.ROWS


def wait_for_unchanged_platform(
    pid: int, master: int, output: bytearray, timeout: float
) -> dict[str, object]:
    """Require repeated platform markers without accepting a hidden transition."""

    deadline = time.monotonic() + min(timeout, 1.0)
    previous: tuple[bool, ...] | None = None
    stable_samples = 0
    while time.monotonic() < deadline:
        read_available(master, output)
        cleaned = clean_output(output)
        if any(marker_present(cleaned, marker) for marker in TOOL_MARKERS):
            raise ProbeError("empty platform confirmation advanced to tool configuration")
        if "Provider error" in cleaned or "HADES_PROVIDER_BASE_URL" in cleaned:
            raise ProbeError("empty platform confirmation started provider behavior")
        signature = tuple(marker_present(cleaned, marker) for marker in SAFE_MARKERS)
        if all(signature):
            if signature == previous:
                stable_samples += 1
            else:
                previous = signature
                stable_samples = 1
            if stable_samples >= 5:
                return {
                    "markers": list(SAFE_MARKERS),
                    "stable_samples": stable_samples,
                    "surface_unchanged": True,
                }
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            raise ProbeError(
                "empty platform confirmation process exited early: "
                f"{describe_status(status)}"
            )
        time.sleep(0.05)
    raise ProbeError("platform picker did not remain unchanged after empty confirmation")


def run_case(binary: Path, timeout: float) -> dict[str, object]:
    home = Path(tempfile.mkdtemp(prefix="hades-empty-platform-confirmation-home-"))
    pid, master, slave_path = platform_replay.spawn_setup(binary, home)
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            master,
            output,
            "empty-platform initial surface",
            lambda text: all(
                marker_present(text, marker) for marker in platform_replay.INITIAL_MARKERS
            ),
            timeout,
        )
        initial_flags = terminal_flags(slave_path)
        config_before = platform_replay.config_shape(home / "config.yaml")

        send(master, b"j\r")
        wait_for(
            pid,
            master,
            output,
            "empty-platform Full setup continuation",
            lambda text: all(
                marker_present(text, marker) for marker in platform_replay.CONTINUATION_MARKERS
            ),
            timeout,
        )
        continuation_flags = terminal_flags(slave_path)
        config_at_continuation = platform_replay.config_shape(home / "config.yaml")

        send(master, b"\x03")
        wait_for(
            pid,
            master,
            output,
            "empty-platform terminal backend",
            lambda text: all(
                marker_present(text, marker)
                for marker in platform_replay.TERMINAL_BACKEND_MARKERS
            ),
            timeout,
        )
        terminal_backend_flags = terminal_flags(slave_path)

        send(master, b"\r")
        wait_for(
            pid,
            master,
            output,
            "empty-platform picker",
            lambda text: all(marker_present(text, marker) for marker in SAFE_MARKERS),
            timeout,
        )
        platform_flags_before = terminal_flags(slave_path)
        config_at_platform = platform_replay.config_shape(home / "config.yaml")
        leaves_before_confirmation = bytes(output).count(b"\x1b[?1049l")

        send(master, b"\r")
        unchanged = wait_for_unchanged_platform(pid, master, output, timeout)
        platform_flags_after = terminal_flags(slave_path)
        config_after_confirmation = platform_replay.config_shape(home / "config.yaml")
        leaves_after_confirmation = bytes(output).count(b"\x1b[?1049l")
        if leaves_after_confirmation != leaves_before_confirmation:
            raise ProbeError("empty platform confirmation left the alternate screen")
        if config_after_confirmation != config_at_platform:
            raise ProbeError("empty platform confirmation changed the setup config")
        if (home / ".env").exists():
            raise ProbeError("empty platform confirmation created a secrets file")
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done:
            raise ProbeError("empty platform confirmation unexpectedly exited the process")

        send(master, b"\x03")
        wait_for(
            pid,
            master,
            output,
            "empty-platform cancellation after confirmation",
            lambda text: all(marker_present(text, marker) for marker in TOOL_MARKERS),
            timeout,
        )
        first_cancel_flags = terminal_flags(slave_path)
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done:
            raise ProbeError("platform cancellation unexpectedly exited the setup process")
        leaves_after_cancel = bytes(output).count(b"\x1b[?1049l")
        if leaves_after_cancel <= leaves_before_confirmation:
            raise ProbeError("platform cancellation did not leave the alternate screen")

        send(master, b"\x03")
        status = wait_for_exit(pid, master, output, timeout)
        reaped = True
        exit_status = describe_status(status)
        if exit_status != {"kind": "exit", "code": 130}:
            raise ProbeError(f"unexpected empty-platform cleanup status: {exit_status}")
        cleanup_flags = terminal_flags(slave_path)
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeError(f"terminal was not restored after cleanup: {cleanup_flags}")

        config_after = platform_replay.config_shape(home / "config.yaml")
        if config_after != config_at_platform:
            raise ProbeError("platform cancellation changed the bounded setup config")
        cleaned = clean_output(output)
        if "Provider error" in cleaned or "HADES_PROVIDER_BASE_URL" in cleaned:
            raise ProbeError("empty-platform replay unexpectedly started provider behavior")

        return {
            "id": "standalone-empty-platform-confirmation",
            "status": "passed",
            "arguments": ["setup"],
            "dimensions": {"columns": COLUMNS, "rows": ROWS},
            "input": [
                {"kind": "key", "value": "j", "bytes_hex": "6a"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d", "meaning": "submit Full setup"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "skip provider"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d", "meaning": "accept Keep current (local)"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d", "meaning": "confirm with no platform selected"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "leave platform picker"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "SIGINT cleanup"},
            ],
            "platform_picker": {
                "markers": list(SAFE_MARKERS),
                "terminal_flags_before_confirmation": platform_flags_before,
                "terminal_flags_after_confirmation": platform_flags_after,
                **unchanged,
                "process_alive_after_confirmation": True,
                "alternate_screen_left_after_confirmation": False,
            },
            "cancellation": {
                "tool_configuration_markers": list(TOOL_MARKERS),
                "first_ctrl_c_terminal_flags": first_cancel_flags,
                "second_ctrl_c_exit": exit_status,
                "alternate_screen_entered": b"\x1b[?1049h" in bytes(output),
                "alternate_screen_left": b"\x1b[?1049l" in bytes(output),
                "cleanup_terminal_flags": cleanup_flags,
            },
            "persistence": {
                "config_before": config_before,
                "config_at_continuation": config_at_continuation,
                "config_at_platform": config_at_platform,
                "config_after_confirmation": config_after_confirmation,
                "config_after_cleanup": config_after,
                "unchanged_on_empty_confirmation": config_after_confirmation == config_at_platform,
                "secrets_file_created": False,
            },
            "scope": {
                "credentials_entered": False,
                "oauth_started": False,
                "network_requested": False,
                "provider_started": False,
                "space_semantics": "unknown and not sent",
                "platform_selection": "none",
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
        "observation_id": "OBS-0087",
        "reference_observation": "OBS-0058",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "probe": "hades-standalone-empty-platform-confirmation",
        "normalization": [
            "Synthetic HOME/HERMES_HOME paths, PTY paths, timestamps, and raw redraw bytes are omitted or represented by stable markers.",
            "The route accepts only the displayed Full setup, Keep current (local) backend, and an empty platform confirmation; no platform, credential, OAuth, provider, or network action is entered.",
            "The replay requires the same platform markers and raw terminal state after Enter, process liveness, no alternate-screen exit, unchanged config/artifacts, and bounded Ctrl+C cleanup.",
        ],
        "unknowns": [
            "Space semantics, platform cursor movement, toggling, confirmation with one or more platforms, platform-specific setup, credentials, OAuth, network behavior, and later setup remain outside this replay.",
            "The safe no-op is an explicit Hades action boundary; it does not infer that Hermes can eventually complete an empty setup beyond the observed window.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not binary.is_file():
            raise ProbeError(f"Hades binary not found: {binary}")
        report["cases"] = [run_case(binary, args.timeout)]
        report["passed"] = True
    except (OSError, ProbeError) as error:
        report["error"] = str(error)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(serialized)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(serialized + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
