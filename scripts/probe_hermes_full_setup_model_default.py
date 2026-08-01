#!/usr/bin/env python3
"""Capture the first Hermes continuation after accepting the model default."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_full_setup import full_setup_cursor, rendered_lines
from probe_hermes_full_setup_provider import PROVIDER_MARKERS, wait_for_provider_boundary
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


MODEL_PROMPT = "Model name [palette-model]:"
DEFAULT_CONTINUATION_MARKERS = (
    "Provider: palette-loopback",
    "URL:",
    "Current: palette-model",
    "Fetching available models...",
    "Could not fetch models from endpoint.",
    "Model name [palette-model]:",
    "Select terminal backend:",
    "Keep current (local)",
)


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
        details["screen_tail"] = normalized_tail(str(details["screen_tail"]).encode())
    return {"case": error.case, "step": error.step, "message": error.message, **details}


def surface(raw: bytes) -> str:
    return "\n".join(rendered_lines(raw))


def wait_for_model_prompt(
    pid: int, fd: int, buffer: bytes, case: str, timeout: float
) -> tuple[bytes, bool]:
    """Wait for the model prompt, retrying only if the active row is still visible."""

    deadline = time.monotonic() + timeout
    retry_at = time.monotonic() + 2.0
    retried = False
    while time.monotonic() < deadline:
        if contains_marker(buffer, MODEL_PROMPT):
            return buffer, retried
        if not retried and time.monotonic() >= retry_at:
            if all(contains_marker(buffer, marker) for marker in PROVIDER_MARKERS):
                write_bytes(fd, b"\r")
                retried = True
        buffer = drain(pid, fd, buffer, 0.05)
    raise ProbeFailure(
        case,
        "model-prompt",
        f"timed out after {timeout:.1f}s",
        {"screen_tail": surface(buffer)[-2400:]},
    )


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "setup-full-model-default"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-full-model-default-"))
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
                {"screen_tail": surface(buffer)[-2400:]},
            )

        time.sleep(0.4)
        write_bytes(fd, b"\r")
        buffer, model_prompt_retried = wait_for_model_prompt(pid, fd, buffer, case, timeout)
        buffer = drain(pid, fd, buffer, 0.5)

        default_start = len(buffer)
        write_bytes(fd, b"\r")
        time.sleep(0.2)
        buffer = drain(pid, fd, buffer, 0.8)
        default_delta = buffer[default_start:]
        default_screen = surface(buffer)
        default_delta_screen = surface(default_delta)
        default_lines = [line for line in default_screen.splitlines() if line.strip()]
        delta_lines = [line for line in default_delta_screen.splitlines() if line.strip()]
        continuation_markers = [
            marker for marker in DEFAULT_CONTINUATION_MARKERS if contains_marker(default_delta, marker)
        ]

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
                {"kind": "key", "value": "Enter", "bytes_hex": "0d", "meaning": "accept displayed palette-model default"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03"},
            ],
            "selected_path": "Full setup via active loopback provider, then default model acceptance",
            "full_selection_retried": full_selection_retried,
            "provider_selection_submitted": True,
            "model_prompt_retried": model_prompt_retried,
            "model_default_submitted": True,
            "continuation_markers": continuation_markers,
            "continuation_screen_tail": normalized_tail("\n".join(default_lines).encode()),
            "continuation_delta_tail": normalized_tail("\n".join(delta_lines).encode()),
            "config_yaml_unchanged": config_after == config_before,
            "new_files": sorted(new_files),
            "new_config_backup_files": sorted(
                name for name in new_files if name.startswith("config.yaml.bak.")
            ),
            "clean_exit": exited,
            "cleanup": "Ctrl+C was sent immediately after the first default-acceptance continuation capture",
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
        "observation_id": "OBS-0048",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with normalized model-default continuation and synthetic-home artifact check",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, loopback URL, credentials, session IDs, timestamps, dynamic inventory, and animated redraw bytes are omitted or replaced by placeholders.",
            "Only Enter is sent at Model name [palette-model]: to accept the displayed default; no endpoint, API key, secret, OAuth action, save action, model request, or network-dependent behavior is entered.",
            "The first continuation is retained as redacted screen-tail diagnostics until stable labels are reviewed and normalized into the checked-in fixture.",
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
