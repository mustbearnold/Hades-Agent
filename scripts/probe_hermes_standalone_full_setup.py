#!/usr/bin/env python3
"""Capture the first reversible Full setup surface from standalone Hermes setup."""

from __future__ import annotations

import argparse
import json
import os
import pty
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_slash_commands import (
    COLUMNS,
    DEFAULT_REFERENCE,
    ROWS,
    SOURCE_COMMIT,
    ProbeFailure,
    contains_marker,
    safe_environment,
    safe_tail,
)
from probe_hermes_terminal_palette import (
    child_status,
    drain,
    read_available,
    set_window_size,
    stop,
    write_bytes,
)
from probe_tui_lifecycle import (
    describe_status,
    retain_slave_descriptor,
    slave_path_for_pid,
    terminal_flags,
)


INITIAL_MARKERS = (
    "Hermes Agent Setup Wizard",
    "Let's configure your Hermes Agent installation.",
    "How would you like to set up Hermes?",
    "Quick Setup (Nous Portal)",
    "Full setup",
    "Blank Slate",
    "ESC cancel",
)
FULL_CURSOR_MARKER = "→ (○) Full setup"
CONTINUATION_MARKERS = (
    "Configuration Location",
    "Config file:",
    "Secrets file:",
    "Data folder:",
    "Install dir:",
    "You can edit these files directly or use 'hermes config edit'",
    "Inference Provider",
    "Choose how to connect to your main chat model.",
)
PROVIDER_SKIP_MARKERS = (
    "Provider setup skipped.",
    "Terminal Backend",
    "Select terminal backend:",
    "Keep current (local)",
)
FALLBACK_MARKERS = (
    "Select terminal backend:",
    "Enter for default (8)",
    "Ctrl+C to exit",
    "Select [1-8] (8):",
)


def emit_report(report: dict[str, Any], path: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")


def file_inventory(home: Path) -> set[str]:
    return {str(path.relative_to(home)) for path in home.rglob("*") if path.is_file()}


def file_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "bytes": 0}
    return {"exists": True, "bytes": "<nonzero>"}


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


def spawn_setup(reference: Path, home: Path) -> tuple[int, int, str]:
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(reference)
        os.execvpe("uv", ["uv", "run", "hermes", "setup"], safe_environment(reference, home))
    set_window_size(fd, COLUMNS, ROWS)
    os.set_blocking(fd, False)
    slave_path = slave_path_for_pid(pid)
    retain_slave_descriptor(slave_path)
    return pid, fd, slave_path


def wait_for_markers(
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


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "standalone-full-setup-continuation"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-standalone-full-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        pid, fd, slave_path = spawn_setup(reference, home)
        files_before = file_inventory(home)
        config_before = file_state(home / "config.yaml")
        secrets_before = (home / ".env").exists()
        buffer = wait_for_markers(pid, fd, buffer, case, "initial-surface", INITIAL_MARKERS, timeout)
        initial_flags = terminal_flags(slave_path)

        write_bytes(fd, b"j")
        buffer = wait_for_markers(
            pid, fd, buffer, case, "full-setup-cursor", (FULL_CURSOR_MARKER,), timeout
        )
        full_cursor_flags = terminal_flags(slave_path)
        write_bytes(fd, b"\r")
        buffer = wait_for_markers(
            pid,
            fd,
            buffer,
            case,
            "continuation-surface",
            CONTINUATION_MARKERS,
            timeout,
        )
        continuation_flags = terminal_flags(slave_path)
        continuation_tail = safe_tail(buffer)

        write_bytes(fd, b"\x03")
        buffer = wait_for_markers(
            pid,
            fd,
            buffer,
            case,
            "provider-skip",
            PROVIDER_SKIP_MARKERS,
            timeout,
        )
        provider_skip_flags = terminal_flags(slave_path)
        provider_skip_tail = safe_tail(buffer)

        write_bytes(fd, b"\x03")
        buffer = wait_for_markers(
            pid,
            fd,
            buffer,
            case,
            "numbered-fallback",
            FALLBACK_MARKERS,
            timeout,
        )
        fallback_flags = terminal_flags(slave_path)
        fallback_tail = safe_tail(buffer)

        write_bytes(fd, b"\x03")
        buffer, exit_status = wait_for_exit(pid, fd, buffer, case, timeout)
        cleanup_flags = terminal_flags(slave_path)
        files_after = file_inventory(home)
        config_after = file_state(home / "config.yaml")
        secrets_after = (home / ".env").exists()
        if exit_status != {"kind": "exit", "code": 1}:
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
                {"kind": "key", "value": "j", "bytes_hex": "6a"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "skip provider setup"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "open numbered fallback"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "cancel from numbered fallback"},
            ],
            "initial_surface": {
                "markers": list(INITIAL_MARKERS),
                "terminal_flags": initial_flags,
            },
            "full_setup_cursor": {
                "marker": FULL_CURSOR_MARKER,
                "terminal_flags": full_cursor_flags,
            },
            "continuation_surface": {
                "markers": list(CONTINUATION_MARKERS),
                "screen_tail": continuation_tail,
                "terminal_flags": continuation_flags,
            },
            "cancellation_chain": {
                "ctrl_c_presses": 3,
                "first": {
                    "markers": list(PROVIDER_SKIP_MARKERS),
                    "terminal_flags": provider_skip_flags,
                    "screen_tail": provider_skip_tail,
                    "outcome": "provider setup skipped; Terminal Backend surface opened",
                },
                "second": {
                    "markers": list(FALLBACK_MARKERS),
                    "terminal_flags": fallback_flags,
                    "screen_tail": fallback_tail,
                    "outcome": "numbered fallback opened",
                },
                "third": {"outcome": "process exited with reference cancellation status"},
            },
            "config_before": config_before,
            "config_after": config_after,
            "config_changed": config_before != config_after,
            "artifact_classes": artifact_classes(files_after - files_before),
            "config_created": not config_before["exists"] and config_after["exists"],
            "secrets_file_created": not secrets_before and secrets_after,
            "exit": exit_status,
            "cleanup": {
                "terminal_flags": cleanup_flags,
                "alternate_screen_entered": b"\x1b[?1049h" in buffer,
                "alternate_screen_left": b"\x1b[?1049l" in buffer,
                "ctrl_c_presses": 3,
                "credentials_entered": False,
                "oauth_started": False,
                "network_requested": False,
            },
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
        "observation_id": "OBS-0071",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with normalized stable landmarks and synthetic-home boundary",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, PTY paths, credentials, timestamps, and raw redraw bytes are omitted or replaced by stable markers.",
            "The fresh synthetic home has no config, provider endpoint, credentials, OAuth action, external network, or model selection.",
            "Full setup is submitted only to reach the first continuation surface; no provider row, secret, OAuth action, save action, or later setup page is entered.",
            "Screen tails are retained only as redacted diagnostics; the contract is limited to the named stable setup surfaces and cleanup state.",
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
