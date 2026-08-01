#!/usr/bin/env python3
"""Capture the first reversible Hermes Full setup continuation surface."""

from __future__ import annotations

import argparse
import json
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
    clean_exit,
    contains_marker,
    safe_tail,
    start_ready,
    stop,
    wait_for,
    write_bytes,
)
from probe_hermes_terminal_palette import Screen, child_status, drain, read_available


SETUP_MARKERS = (
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
    "You can edit these files directly or use 'hermes config edit'",
    "Inference Provider",
    "Choose how to connect to your main chat model.",
)


def rendered_lines(raw: bytes) -> list[str]:
    screen = Screen(columns=COLUMNS, rows=ROWS)
    screen.feed(raw)
    return [line.rstrip() for line in screen.lines()]


def full_setup_cursor(raw: bytes) -> bool:
    return any("Full setup" in line and "→" in line for line in rendered_lines(raw))


def continuation_surface(raw: bytes) -> str:
    return "\n".join(rendered_lines(raw))


def wait_for_continuation_boundary(
    pid: int, fd: int, buffer: bytes, case: str, timeout: float
) -> tuple[bytes, bool]:
    """Wait for Full setup to advance, retrying only while its cursor remains visible."""

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
                "Hermes exited before the Full setup continuation surface",
                {"exit_status": status, "screen_tail": continuation_surface(buffer)[-2400:]},
            )
        if not retried and time.monotonic() >= retry_at:
            if full_setup_cursor(buffer):
                write_bytes(fd, b"\r")
                retried = True
            # The first Enter can be consumed while Ink is repainting the
            # radio list. Never send a duplicate unless Full is still visibly
            # selected and the continuation surface has not appeared.
        buffer = drain(pid, fd, buffer, 0.05)
    raise ProbeFailure(
        case,
        "continuation-surface",
        f"timed out after {timeout:.1f}s",
        {"screen_tail": continuation_surface(buffer)[-2400:]},
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


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "setup-full-continuation"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-full-setup-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    config_before = b""
    try:
        pid, fd, buffer = start_ready(reference, home, case, timeout)
        config_path = home / "config.yaml"
        config_before = config_path.read_bytes()
        secrets_path = home / ".env"
        secrets_before = secrets_path.exists()
        files_before = {
            str(path.relative_to(home)) for path in home.rglob("*") if path.is_file()
        }

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
        buffer = drain(pid, fd, buffer, 0.3)
        time.sleep(0.15)
        write_bytes(fd, b"\r")
        buffer, full_selection_retried = wait_for_continuation_boundary(
            pid, fd, buffer, case, timeout
        )
        buffer = drain(pid, fd, buffer, 0.5)

        # Stop at the first provider boundary. No provider row, secret, OAuth,
        # persistence action, or network request is selected or entered.
        write_bytes(fd, b"\x03")
        buffer = drain(pid, fd, buffer, 0.75)
        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)

        config_after = config_path.read_bytes() if config_path.exists() else b""
        files_after = {
            str(path.relative_to(home)) for path in home.rglob("*") if path.is_file()
        }
        new_files = files_after - files_before
        new_config_backup = any(name.startswith("config.yaml.bak.") for name in new_files)
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "/setup"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "j", "bytes_hex": "6a"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03"},
            ],
            "initial_surface": list(SETUP_MARKERS),
            "continuation_surface": list(CONTINUATION_MARKERS),
            "selected_path": "Full setup via j then Enter",
            "setup_option_persisted": config_after != config_before,
            "config_yaml_unchanged": config_after == config_before,
            "secrets_file_created": secrets_path.exists() and not secrets_before,
            "new_config_backup_created": new_config_backup,
            "new_synthetic_files_count": len(new_files),
            "full_selection_retried": full_selection_retried,
            "cleanup": "Ctrl+C interrupted the first provider boundary and exited cleanly",
            "clean_exit": exited,
        }
    except ProbeFailure:
        raise
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
        "observation_id": "OBS-0042",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with normalized stable landmarks and synthetic-home persistence check",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, config/secrets/data/install paths, credentials, session IDs, timestamps, and animated redraw bytes are omitted or replaced by placeholders.",
            "The configured provider points at an intentionally absent loopback endpoint; no external provider, credential, OAuth flow, model response, or network request is exercised.",
            "The Full setup choice is submitted only to reach the first continuation surface; no provider row, secret, OAuth action, save action, or later setup page is entered.",
            "The probe compares the synthetic config file before and after cleanup and records only boolean persistence results plus bounded artifact flags.",
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
