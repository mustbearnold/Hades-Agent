#!/usr/bin/env python3
"""Capture the first Hermes provider-selection continuation boundary."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_full_setup import full_setup_cursor, rendered_lines
from probe_hermes_full_setup_provider import (
    PROVIDER_MARKERS,
    provider_surface,
    wait_for_provider_boundary,
)
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


SELECTION_MARKERS = ("Model name [palette-model]:",)


def normalized_tail(raw: bytes) -> str:
    text = safe_tail(raw)
    for value in ("http://127.0.0.1:8765/v1", "127.0.0.1:8765/v1"):
        text = text.replace(value, "<loopback-url>")
    return text


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


def selection_surface(raw: bytes) -> str:
    return "\n".join(rendered_lines(raw))


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "setup-full-provider-selection"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-full-provider-selection-"))
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
            lambda current: all(
                contains_marker(current, marker)
                for marker in (
                    "How would you like to set up Hermes?",
                    "Quick Setup (Nous Portal)",
                    "Full setup",
                    "Blank Slate",
                    "ESC cancel",
                )
            ),
            timeout,
        )
        write_bytes(fd, b"j")
        buffer = wait_for(pid, fd, buffer, case, "full-setup-cursor", full_setup_cursor, timeout)
        buffer = drain(pid, fd, buffer, 0.8)
        time.sleep(0.4)
        write_bytes(fd, b"\r")
        buffer, full_selection_retried = wait_for_provider_boundary(pid, fd, buffer, case, timeout)
        buffer = drain(pid, fd, buffer, 0.8)
        if not all(contains_marker(buffer, marker) for marker in PROVIDER_MARKERS):
            raise ProbeFailure(
                case,
                "provider-menu",
                "provider menu did not expose all stable markers",
                {"screen_tail": provider_surface(buffer)[-2400:]},
            )

        # Submit only the already-active provider row. Do not send any further
        # input until the first continuation surface has been recorded.
        time.sleep(0.4)
        selection_start = len(buffer)
        write_bytes(fd, b"\r")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "provider-selection",
            lambda current: all(contains_marker(current, marker) for marker in SELECTION_MARKERS),
            min(timeout, 5.0),
        )
        buffer = drain(pid, fd, buffer, 0.5)
        selection_delta = buffer[selection_start:]
        selected_screen = selection_surface(buffer)
        selection_delta_screen = selection_surface(selection_delta)
        selected_lines = [line for line in selected_screen.splitlines() if line.strip()]
        delta_lines = [line for line in selection_delta_screen.splitlines() if line.strip()]
        selected_markers = [marker for marker in SELECTION_MARKERS if contains_marker(selection_delta, marker)]
        selection_opened = all(
            contains_marker(selection_delta, marker) for marker in SELECTION_MARKERS
        )

        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)
        config_after = config_path.read_bytes() if config_path.exists() else b""
        files_after = {str(path.relative_to(home)) for path in home.rglob("*") if path.is_file()}
        new_files = files_after - files_before
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "/setup"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "j", "bytes_hex": "6a"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03"},
            ],
            "selected_path": "Full setup via j then Enter, then active loopback provider Enter",
            "full_selection_retried": full_selection_retried,
            "provider_selection_submitted": True,
            "selection_opened_continuation": selection_opened,
            "selection_markers": selected_markers,
            "selection_screen_tail": normalized_tail("\n".join(selected_lines).encode()),
            "selection_delta_tail": normalized_tail("\n".join(delta_lines).encode()),
            "selection_prompt_stable": selection_opened,
            "config_yaml_unchanged": config_after == config_before,
            "config_changed_after_selection": config_after != config_before,
            "new_files": sorted(new_files),
            "new_config_backup_files": sorted(
                name for name in new_files if name.startswith("config.yaml.bak.")
            ),
            "clean_exit": exited,
            "cleanup": "Ctrl+C was sent immediately after the first post-selection surface capture",
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
        "observation_id": "OBS-0046",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with normalized first provider-selection continuation and synthetic-home artifact check",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, loopback URL, credentials, session IDs, timestamps, and animated redraw bytes are omitted or replaced by placeholders.",
            "The configured provider is an intentionally absent loopback endpoint; the probe stops after one active-provider Enter and does not enter an endpoint, secret, OAuth action, save action, model request, or network-dependent behavior.",
            "Selection output is retained only as redacted screen-tail diagnostics until stable labels are reviewed and normalized into the checked-in fixture.",
            "The probe compares config bytes before and after cleanup and records only normalized artifact classes; temporary synthetic-home contents are removed after each case.",
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
