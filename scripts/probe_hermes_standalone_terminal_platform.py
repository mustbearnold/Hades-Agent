#!/usr/bin/env python3
"""Capture standalone Hermes setup through the first platform-picker boundary."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from probe_hermes_setup_config_shape import config_shape
from probe_hermes_slash_commands import (
    COLUMNS,
    DEFAULT_REFERENCE,
    ROWS,
    SOURCE_COMMIT,
    ProbeFailure,
    contains_marker,
    normalized,
    safe_environment,
    safe_tail,
)
from probe_hermes_terminal_palette import (
    Screen,
    child_status,
    drain,
    read_available,
    set_window_size,
    stop,
    write_bytes,
)
from probe_tui_lifecycle import describe_status, terminal_flags


INITIAL_MARKERS = (
    "Hermes Agent Setup Wizard",
    "Let's configure your Hermes Agent installation.",
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
BACKEND_MARKERS = (
    "Select terminal backend:",
    "Local - run directly on this machine (default)",
    "Docker - isolated container with configurable resources",
    "Modal - serverless cloud sandbox",
    "SSH - run on a remote machine",
    "Daytona - persistent cloud development environment",
    "Vercel Sandbox - cloud microVM with snapshot filesystem persistence",
    "Singularity/Apptainer - HPC-friendly container",
    "Keep current (local)",
)
PLATFORM_MARKERS = (
    "Select platforms to configure:",
    "SPACE toggle",
    "ENTER confirm",
    "ESC cancel",
    "Mattermost",
    "Signal",
    "(not configured)",
)
TOOL_CONFIGURATION_MARKERS = (
    "No platforms selected. Run 'hermes setup gateway' later to configure.",
    "Hermes Tool Configuration",
    "Enable or disable tools per platform.",
    "Tools that need API keys will be configured when enabled.",
)


def emit_report(report: dict[str, Any], path: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")


def file_inventory(home: Path) -> set[str]:
    return {str(path.relative_to(home)) for path in home.rglob("*") if path.is_file()}


def artifact_classes(new_files: set[str]) -> list[str]:
    classes: set[str] = set()
    for name in new_files:
        if name == "config.yaml":
            classes.add("config.yaml")
        elif name == "SOUL.md":
            classes.add("SOUL.md")
        elif name.startswith(".cache/uv/"):
            classes.add(".cache/uv/<artifact>")
        elif name.startswith("logs/"):
            classes.add("logs/<artifact>")
        else:
            classes.add("<other-file>")
    return sorted(classes)


def rendered_text(raw: bytes) -> str:
    screen = Screen(columns=COLUMNS, rows=ROWS)
    screen.feed(raw)
    return "\n".join(screen.lines())


def rendered_marker_lines(raw: bytes, markers: tuple[str, ...]) -> list[str]:
    return [
        line.strip()
        for line in rendered_text(raw).splitlines()
        if any(marker in line for marker in markers)
    ]


def spawn_setup(reference: Path, home: Path) -> tuple[int, int, str]:
    environment = safe_environment(reference, home)
    for key in (
        "HADES_PROVIDER_BASE_URL",
        "HADES_PROVIDER_API_KEY",
        "HADES_MODEL",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
    ):
        environment.pop(key, None)
    pid, fd = os.forkpty()
    if pid == 0:
        os.chdir(reference)
        os.execvpe("uv", ["uv", "run", "hermes", "setup"], environment)
    set_window_size(fd, COLUMNS, ROWS)
    os.set_blocking(fd, False)
    return pid, fd, os.readlink(f"/proc/{pid}/fd/0")


def spawn_tui(reference: Path, home: Path) -> tuple[int, int]:
    environment = safe_environment(reference, home)
    for key in (
        "HADES_PROVIDER_BASE_URL",
        "HADES_PROVIDER_API_KEY",
        "HADES_MODEL",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
    ):
        environment.pop(key, None)
    pid, fd = os.forkpty()
    if pid == 0:
        os.chdir(reference)
        os.execvpe("uv", ["uv", "run", "hermes", "--tui"], environment)
    set_window_size(fd, COLUMNS, ROWS)
    os.set_blocking(fd, False)
    return pid, fd


def wait_for_rendered(
    pid: int,
    fd: int,
    buffer: bytes,
    case: str,
    step: str,
    markers: tuple[str, ...],
    timeout: float,
) -> bytes:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(contains_marker(buffer, marker) for marker in markers):
            return buffer
        exited, status = child_status(pid)
        if exited:
            buffer += read_available(fd)
            raise ProbeFailure(
                case,
                step,
                "Hermes exited before the PTY assertion",
                {"exit_status": status, "screen_tail": safe_tail(buffer)},
            )
        buffer = drain(pid, fd, buffer, 0.05)
    raise ProbeFailure(
        case,
        step,
        f"timed out after {timeout:.1f}s",
        {"screen_tail": safe_tail(buffer)},
    )


def wait_for_exit(
    pid: int, fd: int, buffer: bytes, case: str, timeout: float
) -> tuple[bytes, dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        exited, status = child_status(pid)
        if exited:
            buffer += read_available(fd)
            return buffer, describe_status(status) if status is not None else {"kind": "reaped"}
        buffer += read_available(fd)
        time.sleep(0.05)
    raise ProbeFailure(
        case,
        "cleanup",
        f"timed out after {timeout:.1f}s",
        {"screen_tail": safe_tail(buffer)},
    )


def bounded_fresh_process_readback(reference: Path, home: Path, timeout: float) -> dict[str, Any]:
    case = "standalone-terminal-platform-fresh-process"
    pid, fd = spawn_tui(reference, home)
    buffer = b""
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not child_status(pid)[0]:
            if contains_marker(buffer, "Hermes Agent"):
                startup = normalized(buffer)
                write_bytes(fd, b"\x03")
                buffer, exited = bounded_cleanup(pid, fd, buffer, case, timeout)
                return {
                    "base_marker_visible": "Hermes Agent" in startup,
                    "setup_required_visible": "Setup Required" in startup,
                    "starting_agent_visible": "starting agent" in startup,
                    "clean_exit": exited,
                }
            buffer = drain(pid, fd, buffer, 0.05)
        return {
            "base_marker_visible": contains_marker(buffer, "Hermes Agent"),
            "setup_required_visible": contains_marker(buffer, "Setup Required"),
            "starting_agent_visible": contains_marker(buffer, "starting agent"),
            "clean_exit": child_status(pid)[0],
        }
    finally:
        if not child_status(pid)[0]:
            stop(pid, fd)


def bounded_cleanup(
    pid: int, fd: int, buffer: bytes, case: str, timeout: float
) -> tuple[bytes, bool]:
    for _ in range(2):
        if child_status(pid)[0]:
            break
        try:
            write_bytes(fd, b"\x03")
        except OSError:
            break
        buffer = drain(pid, fd, buffer, 0.25)
    buffer, _ = wait_for_exit(pid, fd, buffer, case, timeout)
    return buffer, True


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "standalone-full-terminal-platform-boundary"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-standalone-terminal-platform-"))
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
        buffer = wait_for_rendered(pid, fd, buffer, case, "full-setup-cursor", ("Full setup",), timeout)
        full_setup_flags = terminal_flags(slave_path)
        write_bytes(fd, b"\r")
        buffer = wait_for_rendered(
            pid, fd, buffer, case, "continuation-surface", CONTINUATION_MARKERS, timeout
        )
        continuation_flags = terminal_flags(slave_path)
        config_at_continuation = config_shape(home / "config.yaml")
        files_at_continuation = file_inventory(home)

        write_bytes(fd, b"\x03")
        buffer = wait_for_rendered(pid, fd, buffer, case, "terminal-backend", BACKEND_MARKERS, timeout)
        backend_flags = terminal_flags(slave_path)
        config_at_backend = config_shape(home / "config.yaml")
        files_at_backend = file_inventory(home)

        write_bytes(fd, b"\r")
        buffer = wait_for_rendered(pid, fd, buffer, case, "platform-picker", PLATFORM_MARKERS, timeout)
        platform_flags = terminal_flags(slave_path)
        config_at_platform = config_shape(home / "config.yaml")
        files_at_platform = file_inventory(home)
        platform_screen = rendered_marker_lines(buffer, PLATFORM_MARKERS)
        alternate_screen_leaves_before_platform_cancel = buffer.count(b"\x1b[?1049l")

        write_bytes(fd, b"\x03")
        buffer = wait_for_rendered(
            pid,
            fd,
            buffer,
            case,
            "tool-configuration",
            TOOL_CONFIGURATION_MARKERS,
            timeout,
        )
        first_cancel_flags = terminal_flags(slave_path)
        first_cancel_alive = not child_status(pid)[0]
        config_after_first_cancel = config_shape(home / "config.yaml")
        tool_configuration_screen = rendered_marker_lines(buffer, TOOL_CONFIGURATION_MARKERS)

        write_bytes(fd, b"\x03")
        buffer, exit_status = wait_for_exit(pid, fd, buffer, case, timeout)
        cleanup_flags = terminal_flags(slave_path)
        files_after = file_inventory(home)
        config_after = config_shape(home / "config.yaml")
        if exit_status != {"kind": "exit", "code": 130}:
            raise ProbeFailure(
                case,
                "cleanup",
                f"unexpected cancellation exit status: {exit_status}",
                {"screen_tail": safe_tail(buffer)},
            )
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeFailure(
                case,
                "cleanup",
                f"terminal was not restored: {cleanup_flags}",
                {"screen_tail": safe_tail(buffer)},
            )

        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "key", "value": "j", "bytes_hex": "6a", "meaning": "move to Full setup"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d", "meaning": "submit Full setup"},
                {
                    "kind": "key",
                    "value": "Ctrl+C",
                    "bytes_hex": "03",
                    "meaning": "skip the unconfigured provider step",
                },
                {
                    "kind": "key",
                    "value": "Enter",
                    "bytes_hex": "0d",
                    "meaning": "accept highlighted Keep current (local) backend",
                },
                {
                    "kind": "key",
                    "value": "Ctrl+C",
                    "bytes_hex": "03",
                    "meaning": "leave the platform picker without selecting a platform",
                },
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "bounded cleanup"},
            ],
            "surfaces": {
                "initial": {"markers": list(INITIAL_MARKERS), "terminal_flags": initial_flags},
                "full_setup_cursor": {
                    "marker": "Full setup",
                    "terminal_flags": full_setup_flags,
                },
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
                    "screen_markers": platform_screen,
                    "terminal_flags": platform_flags,
                },
                "tool_configuration_after_platform_cancel": {
                    "markers": list(TOOL_CONFIGURATION_MARKERS),
                    "screen_markers": tool_configuration_screen,
                    "terminal_flags": first_cancel_flags,
                },
            },
            "persistence": {
                "config_before": config_before,
                "config_at_continuation": config_at_continuation,
                "config_at_backend": config_at_backend,
                "config_at_platform": config_at_platform,
                "config_after_first_cancel": config_after_first_cancel,
                "config_after_cancel": config_after,
                "config_created_at_backend": not config_before["exists"] and config_at_backend["exists"],
                "config_changed_on_backend_selection": config_at_backend != config_at_platform,
                "config_changed_on_platform_cancel": config_at_platform != config_after_first_cancel,
                "config_unchanged_after_cleanup": config_after_first_cancel == config_after,
                "artifact_classes_before_backend": artifact_classes(files_at_backend - files_before),
                "artifact_classes_on_backend_selection": artifact_classes(
                    files_at_platform - files_at_backend
                ),
                "artifact_classes_after_cleanup": artifact_classes(files_after - files_at_platform),
                "secrets_file_created": (home / ".env").exists(),
            },
            "cancellation": {
                "first_ctrl_c": {
                    "process_still_alive": first_cancel_alive,
                    "terminal_flags": first_cancel_flags,
                    "alternate_screen_left": buffer.count(b"\x1b[?1049l")
                    > alternate_screen_leaves_before_platform_cancel,
                    "outcome": "platform cancellation advanced to Hermes Tool Configuration with no platforms selected while terminal input was restored",
                },
                "second_ctrl_c": {"exit": exit_status, "terminal_flags": cleanup_flags},
                "alternate_screen_entered": b"\x1b[?1049h" in buffer,
                "alternate_screen_left": b"\x1b[?1049l" in buffer,
                "credentials_entered": False,
                "oauth_started": False,
                "network_requested": False,
            },
            "fresh_process_readback": bounded_fresh_process_readback(reference, home, timeout),
        }
    finally:
        if pid != -1:
            stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def safe_failure(error: BaseException) -> Any:
    if not isinstance(error, ProbeFailure):
        return str(error)
    details = dict(error.details)
    if "screen_tail" in details:
        details["screen_tail"] = safe_tail(str(details["screen_tail"]).encode())
    return {"case": error.case, "step": error.step, "message": error.message, **details}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0073",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "fresh synthetic home with direct PTY and ANSI screen model",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, PTY paths, credentials, timestamps, and raw redraw bytes are omitted or replaced by stable markers.",
            "The fresh standalone setup starts without configuration or provider environment; no provider value, model value, credential, OAuth action, external network, or platform selection is entered.",
            "Config evidence contains only existence, byte counts, and normalized YAML key paths/types; screen evidence contains only stable platform landmarks and redacted diagnostics.",
            "The first platform Ctrl+C and the second cleanup Ctrl+C are recorded separately because the reference restores terminal input before exiting the setup process.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"].append(run_case(reference, args.timeout))
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        report["failure"] = safe_failure(error)
    emit_report(report, args.report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
