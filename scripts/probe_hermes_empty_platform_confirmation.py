#!/usr/bin/env python3
"""Capture Hermes' empty-platform confirmation boundary safely."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_provider_setup_persistence import (
    BACKEND_MARKERS,
    artifact_classes,
    cleanup_case,
    fresh_process_readback,
    navigate_to_backend,
    redacted_tail,
    surface,
)
from probe_hermes_setup_config_shape import (
    PLATFORM_MARKERS,
    config_shape,
    file_inventory,
    wait_for_platform_picker,
)
from probe_hermes_slash_commands import (
    COLUMNS,
    DEFAULT_REFERENCE,
    ROWS,
    SOURCE_COMMIT,
    ProbeFailure,
    child_status,
    stop,
    write_bytes,
    write_ready_config,
)
from probe_hermes_terminal_palette import drain, read_available


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
        details["screen_tail"] = redacted_tail(str(details["screen_tail"]).encode())
    return {"case": error.case, "step": error.step, "message": error.message, **details}


def platform_marker_lines(rendered: str) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in rendered.splitlines()
        if any(marker in line for marker in PLATFORM_MARKERS)
    )


def stable_platform_surface(
    pid: int, fd: int, buffer: bytes, case: str, timeout: float
) -> tuple[bytes, str, int]:
    """Require repeated identical rendered picker surfaces after confirmation."""
    deadline = time.monotonic() + timeout
    previous: str | None = None
    stable_samples = 0
    while time.monotonic() < deadline:
        current = surface(buffer)
        if all(marker in current for marker in PLATFORM_MARKERS):
            if current == previous:
                stable_samples += 1
            else:
                previous = current
                stable_samples = 1
            if stable_samples >= 3:
                return buffer, current, stable_samples
        exited, status = child_status(pid)
        if exited:
            buffer += read_available(fd)
            raise ProbeFailure(
                case,
                "empty-platform-confirmation",
                "Hermes exited before a stable post-confirmation surface",
                {"exit_status": status, "screen_tail": surface(buffer)[-2400:]},
            )
        buffer = drain(pid, fd, buffer, 0.05)
    raise ProbeFailure(
        case,
        "empty-platform-confirmation",
        f"timed out after {timeout:.1f}s waiting for a stable post-confirmation surface",
        {"screen_tail": surface(buffer)[-2400:]},
    )


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "empty-platform-confirmation"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-empty-platform-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    try:
        write_ready_config(home)
        config_path = home / "config.yaml"
        files_before = file_inventory(home)
        pid, fd, buffer = navigate_to_backend(reference, home, case, timeout)
        write_bytes(fd, b"\r")
        buffer = drain(pid, fd, buffer, 0.4)
        buffer = wait_for_platform_picker(pid, fd, buffer, case, timeout)
        platform_surface_before = surface(buffer)
        config_at_platform = config_shape(config_path)
        files_at_platform = file_inventory(home)

        write_bytes(fd, b"\r")
        buffer = drain(pid, fd, buffer, 0.8)
        buffer, platform_surface_after, stable_samples = stable_platform_surface(
            pid, fd, buffer, case, timeout
        )
        config_after_confirm = config_shape(config_path)
        files_after_confirm = file_inventory(home)
        process_alive_after_confirm = not child_status(pid)[0]
        before_markers = platform_marker_lines(platform_surface_before)
        after_markers = platform_marker_lines(platform_surface_after)

        write_bytes(fd, b"\x03")
        buffer, exited = cleanup_case(pid, fd, buffer, case, timeout)
        config_after_cleanup = config_shape(config_path)
        files_after_cleanup = file_inventory(home)
        readback = fresh_process_readback(reference, home, f"{case}-fresh-process", timeout)
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "/setup"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "j", "bytes_hex": "6a"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Enter"},
                {
                    "kind": "key",
                    "value": "Enter",
                    "meaning": "accept displayed palette-model default",
                },
                {
                    "kind": "key",
                    "value": "Enter",
                    "meaning": "accept displayed Keep current (local) backend",
                },
                {
                    "kind": "key",
                    "value": "Enter",
                    "bytes_hex": "0d",
                    "meaning": "confirm with no platform selected",
                },
                {
                    "kind": "key",
                    "value": "Ctrl+C",
                    "bytes_hex": "03",
                    "meaning": "clean exit from the unchanged platform picker",
                },
            ],
            "backend_markers": list(BACKEND_MARKERS),
            "platform_markers": list(PLATFORM_MARKERS),
            "stable_samples": stable_samples,
            "platform_surface_markers_before": list(before_markers),
            "post_confirmation_screen_markers": list(after_markers),
            "post_confirmation_surface_unchanged": before_markers == after_markers,
            "ready_after_empty_confirmation": "ready" in platform_surface_after.lower(),
            "process_alive_after_empty_confirmation": process_alive_after_confirm,
            "config_at_platform": config_at_platform,
            "config_after_empty_confirmation": config_after_confirm,
            "config_after_cleanup": config_after_cleanup,
            "config_changed_on_empty_confirmation": config_at_platform != config_after_confirm,
            "config_changed_during_cleanup": config_after_confirm != config_after_cleanup,
            "artifact_classes_before_backend": artifact_classes(files_at_platform - files_before),
            "artifact_classes_on_empty_confirmation": artifact_classes(
                files_after_confirm - files_at_platform
            ),
            "artifact_classes_during_cleanup": artifact_classes(
                files_after_cleanup - files_after_confirm
            ),
            "clean_exit": exited,
            "fresh_process_readback": readback,
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
        "observation_id": "OBS-0058",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with redacted ANSI screen model",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, session identifiers, timestamps, raw config values, hashes, and animated redraw bytes are omitted or replaced by placeholders.",
            "The probe accepts only the displayed synthetic loopback/model/backend defaults and confirms the platform picker with no selected platform; no credentials, OAuth action, external network, or platform toggle is used.",
            "Config evidence contains normalized key paths, scalar/container kinds, and byte counts only; screen evidence is reduced to stable picker markers and redacted diagnostics.",
            "The post-confirmation claim is bounded by repeated identical rendered surfaces during a finite observation window; it does not infer behavior beyond that window.",
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
