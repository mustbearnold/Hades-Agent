#!/usr/bin/env python3
"""Capture the Hermes model-picker model stage and bounded back controls."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from probe_hermes_slash_commands import (
    DEFAULT_REFERENCE,
    COLUMNS,
    ProbeFailure,
    clean_exit,
    drain,
    safe_tail,
    start_ready,
    stop,
    wait_for,
    write_bytes,
)
from probe_hermes_terminal_palette import Screen


ROWS = 40
SOURCE_COMMIT = "e444d165807f489b5c1ab8e4a612c8d09c2e67a2"


def screen_contains(raw: bytes, marker: str) -> bool:
    """Assert against the rendered PTY screen, not one incremental redraw."""

    screen = Screen()
    screen.feed(raw)
    text = "\n".join(screen.lines())
    compact_text = "".join(text.split()).lower()
    compact_marker = "".join(marker.split()).lower()
    return marker.lower() in text.lower() or compact_marker in compact_text


def screen_has_all(raw: bytes, markers: list[str]) -> bool:
    return all(screen_contains(raw, marker) for marker in markers)


def type_text(pid: int, fd: int, buffer: bytes, value: str) -> bytes:
    """Send printable picker input one key at a time across Ink redraws."""

    for byte in value.encode("utf-8"):
        write_bytes(fd, bytes([byte]))
        buffer = drain(pid, fd, buffer, 0.15)
    return buffer


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "model-picker-model-stage"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-model-picker-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        pid, fd, buffer = start_ready(reference, home, case, timeout)

        write_bytes(fd, b"/model\r")
        buffer = drain(pid, fd, buffer, 0.5)
        write_bytes(fd, b"\r")
        provider_markers = [
            "Select provider (step 1/2)",
            "Current: palette-model",
            "type to filter",
            "persist: session",
            "Esc clear/back",
            "q close",
        ]
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "provider-picker",
            lambda current: screen_has_all(current, provider_markers),
            timeout,
        )

        buffer = type_text(pid, fd, buffer, "palette")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "provider-filter",
            lambda current: screen_contains(current, "filter: palette")
            and screen_contains(current, "palette-loopback"),
            timeout,
        )
        write_bytes(fd, b"\r")
        model_markers = [
            "Select model (step 2/2)",
            "palette-loopback",
            "type to filter",
            "palette-model",
            "persist: session",
            "Esc clear/back",
            "q close",
        ]
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "model-stage",
            lambda current: screen_has_all(current, model_markers),
            timeout,
        )

        buffer = type_text(pid, fd, buffer, "palette")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "model-filter",
            lambda current: screen_contains(current, "filter: palette")
            and screen_contains(current, "palette-model"),
            timeout,
        )

        write_bytes(fd, b"\x1b")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "clear-model-filter",
            lambda current: screen_contains(current, "Select model (step 2/2)")
            and screen_contains(current, "type to filter"),
            timeout,
        )

        write_bytes(fd, b"\x1b")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "back-to-provider-picker",
            lambda current: screen_contains(current, "Select provider (step 1/2)"),
            timeout,
        )

        write_bytes(fd, b"q")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "close-picker",
            lambda current: screen_contains(current, "ready"),
            timeout,
        )
        buffer, _ = clean_exit(pid, fd, buffer, case, timeout)
        return {
            "id": case,
            "status": "passed",
            "input_sequence": [
                {"kind": "text", "value": "/model"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Enter"},
                {"kind": "text", "value": "palette"},
                {"kind": "key", "value": "Enter"},
                {"kind": "text", "value": "palette"},
                {"kind": "key", "value": "Escape"},
                {"kind": "key", "value": "Escape"},
                {"kind": "key", "value": "q"},
            ],
            "observed": {
                "provider_stage": provider_markers,
                "provider_filter": ["filter: palette", "palette-loopback"],
                "model_stage": model_markers,
                "model_filter": ["filter: palette", "palette-model"],
                "escape_with_filter": "cleared the model-stage filter and remained on the model stage",
                "escape_without_filter": "returned to the provider stage",
                "q": "closed the picker and returned to ready",
            },
            "selection": "The provider was only used to enter the model stage; no model was selected or persisted and no setup or network side effect was exercised.",
            "cleanup": "Ctrl+C exited cleanly after q closed the picker",
        }
    except ProbeFailure:
        raise
    finally:
        if pid != -1:
            stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def emit_report(report: dict[str, Any], path: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0038",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY rendered screen markers"},
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, loopback URL, credentials, provider counts, loading text, session IDs, timestamps, and animated redraw bytes are omitted or replaced by placeholders.",
            "The custom provider is reached only through a type-to-filter interaction and Enter advances to the model stage; no model is selected or persisted and no external service is served.",
            "Exact provider/model row ordering, model inventories, discovery timing, spinner text, warning text, and visual styling are dynamic; stable stage and control landmarks are asserted.",
            "Printable filter input is sent one key at a time and the full ANSI stream is modeled because the picker redraws incrementally.",
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
        if isinstance(error, ProbeFailure):
            details = error.as_dict()
            if "screen_tail" in details:
                details["screen_tail"] = safe_tail(str(details["screen_tail"]).encode())
            report["failure"] = details
        else:
            report["failure"] = str(error)
    emit_report(report, args.report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
