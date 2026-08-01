#!/usr/bin/env python3
"""Capture normalized Hermes setup config shape and platform continuation."""

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
from probe_hermes_slash_commands import (
    COLUMNS,
    DEFAULT_REFERENCE,
    ROWS,
    SOURCE_COMMIT,
    ProbeFailure,
    child_status,
    start_ready,
    stop,
    wait_for,
    write_bytes,
    write_ready_config,
)
from probe_hermes_terminal_palette import drain, read_available


PLATFORM_MARKERS = (
    "Select platforms to configure:",
    "SPACE toggle",
    "ENTER confirm",
    "ESC cancel",
    "Mattermost",
    "Signal",
    "(not configured)",
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
        details["screen_tail"] = redacted_tail(str(details["screen_tail"]).encode())
    return {"case": error.case, "step": error.step, "message": error.message, **details}


def scalar_kind(value: str) -> str:
    value = value.strip()
    if not value:
        return "container"
    if value.lower() in {"true", "false"}:
        return "boolean"
    if value.lower() in {"null", "~"}:
        return "null"
    if value.startswith(("[", "- ")):
        return "sequence"
    if value.startswith("{"):
        return "mapping"
    if value[:1] in {"'", '"'}:
        return "string"
    try:
        int(value, 10)
        return "integer"
    except ValueError:
        return "string"


def config_shape(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "bytes": 0, "entries": []}

    content = path.read_bytes()
    stack: list[tuple[int, str]] = []
    entries: set[tuple[str, str]] = set()
    for raw_line in content.decode("utf-8", errors="replace").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if line.startswith("---"):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().strip("'\"")
        if not key:
            continue
        while stack and indent <= stack[-1][0]:
            stack.pop()
        path_parts = [part for _, part in stack] + [key]
        entries.add((".".join(path_parts), scalar_kind(value)))
        if not value.strip():
            stack.append((indent, key))

    return {
        "exists": True,
        "bytes": len(content),
        "entries": [
            {"path": path_value, "kind": kind}
            for path_value, kind in sorted(entries)
        ],
    }


def file_inventory(home: Path) -> set[str]:
    return {str(path.relative_to(home)) for path in home.rglob("*") if path.is_file()}


def wait_for_platform_picker(
    pid: int, fd: int, buffer: bytes, case: str, timeout: float
) -> bytes:
    deadline = time.monotonic() + timeout
    retried = False
    retry_at = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        current = surface(buffer)
        if all(marker in current for marker in PLATFORM_MARKERS):
            return buffer
        if not child_status(pid)[0] and not retried and time.monotonic() >= retry_at:
            if all(marker in current for marker in BACKEND_MARKERS):
                write_bytes(fd, b"\r")
                retried = True
        buffer = drain(pid, fd, buffer, 0.05)
    buffer += read_available(fd)
    raise ProbeFailure(
        case,
        "platform-picker",
        f"timed out after {timeout:.1f}s",
        {"screen_tail": surface(buffer)[-2400:]},
    )


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "setup-config-shape-platform-picker"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-setup-config-shape-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    try:
        write_ready_config(home)
        config_path = home / "config.yaml"
        baseline_shape = config_shape(config_path)
        files_before = file_inventory(home)
        pid, fd, buffer = navigate_to_backend(reference, home, case, timeout)
        backend_shape = config_shape(config_path)
        files_at_backend = file_inventory(home)
        backend_screen = redacted_tail(surface(buffer).encode())

        time.sleep(0.2)
        write_bytes(fd, b"\r")
        buffer = drain(pid, fd, buffer, 0.8)
        buffer = wait_for_platform_picker(pid, fd, buffer, case, timeout)
        platform_shape = config_shape(config_path)
        platform_screen = "\n".join(
            line.strip() for line in surface(buffer).splitlines() if any(marker in line for marker in PLATFORM_MARKERS)
        )
        files_at_platform = file_inventory(home)

        write_bytes(fd, b"\x03")
        buffer, exited = cleanup_case(pid, fd, buffer, case, timeout)
        final_shape = config_shape(config_path)
        files_after = file_inventory(home)
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
                {"kind": "key", "value": "Enter", "meaning": "accept displayed palette-model default"},
                {"kind": "key", "value": "Enter", "meaning": "accept displayed Keep current (local) backend"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "cancel at platform picker"},
            ],
            "backend_markers": list(BACKEND_MARKERS),
            "platform_markers": list(PLATFORM_MARKERS),
            "backend_screen_tail": backend_screen,
            "platform_screen_markers": platform_screen,
            "config_baseline": baseline_shape,
            "config_at_backend": backend_shape,
            "config_at_platform": platform_shape,
            "config_after_cancel": final_shape,
            "config_changed_before_backend": baseline_shape != backend_shape,
            "config_changed_on_backend_selection": backend_shape != platform_shape,
            "config_changed_on_platform_cancel": platform_shape != final_shape,
            "artifact_classes_before_backend": artifact_classes(files_at_backend - files_before),
            "artifact_classes_on_backend_selection": artifact_classes(files_at_platform - files_at_backend),
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
        "observation_id": "OBS-0056",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY with redacted ANSI screen model"},
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, loopback URL, credentials, session identifiers, timestamps, raw config values, hashes, and animated redraw bytes are omitted or replaced by placeholders.",
            "Config shape entries contain only normalized key paths and scalar/container kinds; the report never stores config values or API-key material.",
            "Only the displayed loopback/model/backend defaults are accepted; no credentials, OAuth action, external network, or platform selection is entered.",
            "Screen evidence is reduced to stable platform markers and redacted diagnostics; dynamic platform inventory and unrelated artifact names remain outside the claim.",
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
