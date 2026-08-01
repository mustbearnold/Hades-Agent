#!/usr/bin/env python3
"""Capture the pre-selection Hermes Full setup provider menu boundary."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_full_setup import CONTINUATION_MARKERS, full_setup_cursor, rendered_lines
from probe_hermes_slash_commands import (
    COLUMNS,
    DEFAULT_REFERENCE,
    ROWS,
    SOURCE_COMMIT,
    ProbeFailure,
    clean_exit,
    contains_marker,
    safe_tail,
    start_ready,
    stop,
    wait_for,
    write_bytes,
)
from probe_hermes_terminal_palette import drain
from probe_hermes_terminal_palette import child_status, read_available


SETUP_MARKERS = (
    "How would you like to set up Hermes?",
    "Quick Setup (Nous Portal)",
    "Full setup",
    "Blank Slate",
    "ESC cancel",
)
PROVIDER_MARKERS = (
    "Current model:",
    "Active provider:",
    "Select provider:",
    "palette-loopback",
    "palette-model",
    "Custom endpoint (enter URL manually)",
    "Remove a saved custom provider",
)


def emit_report(report: dict[str, Any], path: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")


def safe_failure(error: BaseException) -> Any:
    if not isinstance(error, ProbeFailure):
        return str(error)
    details = dict(error.details)
    if "screen_tail" in details:
        details["screen_tail"] = safe_tail(str(details["screen_tail"]).encode())
    return {"case": error.case, "step": error.step, "message": error.message, **details}


def provider_surface(raw: bytes) -> str:
    return "\n".join(rendered_lines(raw))


def wait_for_provider_boundary(
    pid: int, fd: int, buffer: bytes, case: str, timeout: float
) -> tuple[bytes, bool]:
    """Wait for the provider picker and retry only while Full is still selected."""

    deadline = time.monotonic() + timeout
    retry_at = time.monotonic() + 2.0
    retried = False
    while time.monotonic() < deadline:
        if all(contains_marker(buffer, marker) for marker in CONTINUATION_MARKERS):
            return buffer, retried
        exited, status = child_status(pid)
        if exited:
            buffer += read_available(fd)
            raise ProbeFailure(
                case,
                "continuation-surface",
                "Hermes exited before the provider boundary",
                {"exit_status": status, "screen_tail": provider_surface(buffer)[-2400:]},
            )
        if not retried and time.monotonic() >= retry_at:
            if full_setup_cursor(buffer):
                write_bytes(fd, b"\r")
                retried = True
            # The first Enter may have been consumed while the screen model
            # is catching up; never send a second Enter unless the Full radio
            # cursor is still visibly selected.
        buffer = drain(pid, fd, buffer, 0.05)
    raise ProbeFailure(
        case,
        "continuation-surface",
        f"timed out after {timeout:.1f}s",
        {"screen_tail": provider_surface(buffer)[-2400:]},
    )


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "setup-full-provider-menu"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-full-provider-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        pid, fd, buffer = start_ready(reference, home, case, timeout)
        config_path = home / "config.yaml"
        config_before = config_path.read_bytes()
        files_before = {str(path.relative_to(home)) for path in home.rglob("*") if path.is_file()}

        write_bytes(fd, b"/setup\r")
        buffer = drain(pid, fd, buffer, 0.7)
        write_bytes(fd, b"\r")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "initial-wizard",
            lambda current: all(contains_marker(current, marker) for marker in SETUP_MARKERS),
            timeout,
        )
        write_bytes(fd, b"j")
        buffer = wait_for(pid, fd, buffer, case, "full-setup-cursor", full_setup_cursor, timeout)
        # Let the final radio redraw settle before submitting Full setup. The
        # reference can otherwise consume an immediate Enter while Ink is
        # still repainting the cursor, leaving the probe on the initial list.
        buffer = drain(pid, fd, buffer, 0.8)
        time.sleep(0.4)
        write_bytes(fd, b"\r")
        buffer, full_selection_retried = wait_for_provider_boundary(pid, fd, buffer, case, timeout)
        buffer = drain(pid, fd, buffer, 0.8)
        surface = provider_surface(buffer)
        if not all(contains_marker(buffer, marker) for marker in PROVIDER_MARKERS):
            raise ProbeFailure(
                case,
                "provider-menu",
                "provider menu did not expose all stable markers",
                {"screen_tail": surface[-2400:]},
            )

        # Move the provider cursor once without pressing Enter. This keeps the
        # observation before any provider, secret, OAuth, save, or network path.
        write_bytes(fd, b"\x1b[B")
        buffer = drain(pid, fd, buffer, 0.4)
        write_bytes(fd, b"\x03")
        buffer = drain(pid, fd, buffer, 0.75)
        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)

        config_after = config_path.read_bytes() if config_path.exists() else b""
        files_after = {str(path.relative_to(home)) for path in home.rglob("*") if path.is_file()}
        new_files = files_after - files_before
        backup_files = sorted(name for name in new_files if name.startswith("config.yaml.bak."))
        extra_files = sorted(new_files - set(backup_files))
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "/setup"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "j", "bytes_hex": "6a"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Down", "bytes_hex": "1b 5b 42"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03"},
            ],
            "initial_surface": list(SETUP_MARKERS),
            "continuation_surface": list(CONTINUATION_MARKERS),
            "provider_menu": list(PROVIDER_MARKERS),
            "selected_path": "Full setup via j then Enter",
            "full_selection_retried": full_selection_retried,
            "provider_selection_submitted": False,
            "provider_navigation": "Down moved the provider cursor without Enter",
            "setup_option_persisted": config_after != config_before,
            "config_yaml_unchanged": config_after == config_before,
            "new_files_count": len(new_files),
            "new_files": sorted(new_files),
            "new_config_backup_files": backup_files,
            "new_files_beyond_config_backup": extra_files,
            "cleanup": "Ctrl+C from the provider menu exited cleanly",
            "clean_exit": exited,
        }
    finally:
        if pid != -1:
            stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0044",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with normalized provider-menu landmarks and synthetic-home artifact check",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, loopback URL, credentials, session IDs, timestamps, and animated redraw bytes are omitted or replaced by placeholders.",
            "The configured provider is an intentionally absent loopback endpoint; no external provider, OAuth flow, credential, model response, or network request is exercised.",
            "The Full setup choice is submitted only to reach the provider picker; one Down navigation is sent without Enter and the probe stops before any provider selection or credential flow.",
            "The probe records stable current-model/provider and cancellation landmarks and compares synthetic-home files before and after cleanup.",
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
