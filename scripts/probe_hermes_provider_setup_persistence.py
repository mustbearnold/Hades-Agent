#!/usr/bin/env python3
"""Capture safe Hermes provider-setup cancellation and commit boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_full_setup import full_setup_cursor, rendered_lines, wait_for_continuation_boundary
from probe_hermes_full_setup_model_default import MODEL_PROMPT, wait_for_model_prompt
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
    spawn,
    start_ready,
    stop,
    wait_for,
    write_bytes,
    write_ready_config,
)
from probe_hermes_terminal_palette import child_status, drain, read_available


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
    "ENTER/SPACE select",
    "ESC cancel",
)
READY_MARKERS = ("Hermes Agent", "ready")


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


def redacted_tail(raw: bytes) -> str:
    text = safe_tail(raw)
    return re.sub(r"(?i)Session:\s+\S+", "Session: <session-id>", text)


def surface(raw: bytes) -> str:
    return "\n".join(rendered_lines(raw))


def wait_for_backend(
    pid: int, fd: int, buffer: bytes, case: str, timeout: float
) -> bytes:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = surface(buffer)
        if all(marker in current for marker in BACKEND_MARKERS):
            return buffer
        exited, status = child_status(pid)
        if exited:
            buffer += read_available(fd)
            raise ProbeFailure(
                case,
                "terminal-backend",
                "Hermes exited before the terminal-backend picker",
                {"exit_status": status, "screen_tail": surface(buffer)[-2400:]},
            )
        buffer = drain(pid, fd, buffer, 0.05)
    raise ProbeFailure(
        case,
        "terminal-backend",
        f"timed out after {timeout:.1f}s",
        {"screen_tail": surface(buffer)[-2400:]},
    )


def navigate_to_backend(reference: Path, home: Path, case: str, timeout: float) -> tuple[int, int, bytes]:
    pid, fd, buffer = start_ready(reference, home, case, timeout)
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
    buffer, _ = wait_for_continuation_boundary(pid, fd, buffer, case, timeout)
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
    buffer, _ = wait_for_model_prompt(pid, fd, buffer, case, timeout)
    buffer = drain(pid, fd, buffer, 0.5)
    if not contains_marker(buffer, MODEL_PROMPT):
        raise ProbeFailure(
            case,
            "model-prompt",
            "model prompt was not retained before default acceptance",
            {"screen_tail": surface(buffer)[-2400:]},
        )
    time.sleep(0.2)
    write_bytes(fd, b"\r")
    buffer = drain(pid, fd, buffer, 0.8)
    if MODEL_PROMPT in surface(buffer) and "Select terminal backend:" not in surface(buffer):
        # Ink can consume the first Enter while repainting the prompt. A
        # second Enter is safe only while the prompt is visibly still active.
        write_bytes(fd, b"\r")
        buffer = drain(pid, fd, buffer, 0.8)
    return pid, fd, wait_for_backend(pid, fd, buffer, case, timeout)


def file_inventory(home: Path) -> set[str]:
    return {str(path.relative_to(home)) for path in home.rglob("*") if path.is_file()}


def config_digest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "bytes": 0, "sha256": None}
    content = path.read_bytes()
    return {"exists": True, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def artifact_classes(new_files: set[str]) -> list[str]:
    classes: set[str] = set()
    for name in new_files:
        if name.startswith("config.yaml.bak."):
            classes.add("config.yaml.bak.<timestamp>")
        elif name == ".hermes_history":
            classes.add(".hermes_history")
        elif name == ".update_check":
            classes.add(".update_check")
        else:
            classes.add("<other-file>")
    return sorted(classes)


def cleanup_case(pid: int, fd: int, buffer: bytes, case: str, timeout: float) -> tuple[bytes, bool]:
    buffer = drain(pid, fd, buffer, 0.75)
    return clean_exit(pid, fd, buffer, case, timeout)


def run_cancel_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "provider-setup-cancel-at-backend"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-provider-setup-cancel-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    try:
        write_ready_config(home)
        config_path = home / "config.yaml"
        before = config_digest(config_path)
        files_before = file_inventory(home)
        pid, fd, buffer = navigate_to_backend(reference, home, case, timeout)
        config_at_backend = config_digest(config_path)
        files_at_backend = file_inventory(home)
        screen_tail = redacted_tail(surface(buffer).encode())
        write_bytes(fd, b"\x03")
        _, exited = cleanup_case(pid, fd, buffer, case, timeout)
        after = config_digest(config_path)
        files_after = file_inventory(home)
        new_files = files_after - files_before
        backend_new_files = files_after - files_at_backend
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
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03"},
            ],
            "terminal_backend": list(BACKEND_MARKERS),
            "screen_tail": screen_tail,
            "config_before": before,
            "config_at_backend": config_at_backend,
            "config_after_cancel": after,
            "config_changed_before_backend": before != config_at_backend,
            "config_changed_on_backend_cancel": config_at_backend != after,
            "new_artifact_classes": artifact_classes(new_files),
            "new_artifact_classes_on_backend_cancel": artifact_classes(backend_new_files),
            "clean_exit": exited,
            "cleanup": "Ctrl+C cancelled at the selected Keep current (local) backend without further input",
        }
    finally:
        if pid != -1:
            stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def fresh_process_readback(reference: Path, home: Path, case: str, timeout: float) -> dict[str, Any]:
    pid, fd = spawn(reference, home, configured=False)
    buffer = b""
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not child_status(pid)[0]:
            if all(contains_marker(buffer, marker) for marker in READY_MARKERS):
                screen = redacted_tail(surface(buffer).encode())
                buffer, exited = cleanup_case(pid, fd, buffer, case, timeout)
                return {"ready": True, "screen_tail": screen, "clean_exit": exited}
            buffer = drain(pid, fd, buffer, 0.05)
        buffer += read_available(fd)
        return {
            "ready": False,
            "screen_tail": redacted_tail(surface(buffer).encode()),
            "clean_exit": child_status(pid)[0],
        }
    finally:
        if not child_status(pid)[0]:
            stop(pid, fd)


def run_commit_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "provider-setup-accept-keep-current"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-provider-setup-commit-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    try:
        write_ready_config(home)
        config_path = home / "config.yaml"
        before = config_digest(config_path)
        files_before = file_inventory(home)
        pid, fd, buffer = navigate_to_backend(reference, home, case, timeout)
        config_at_backend = config_digest(config_path)
        files_at_backend = file_inventory(home)
        screen_tail = redacted_tail(surface(buffer).encode())
        # Hermes highlights Keep current (local) in this configured synthetic-home path.
        write_bytes(fd, b"\r")
        buffer = drain(pid, fd, buffer, 1.5)
        post_selection_tail = redacted_tail(surface(buffer).encode())
        if not child_status(pid)[0]:
            buffer, exited = cleanup_case(pid, fd, buffer, case, timeout)
        else:
            exited = True
        after = config_digest(config_path)
        files_after = file_inventory(home)
        new_files = files_after - files_before
        backend_new_files = files_after - files_at_backend
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
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "bounded cleanup if setup remains open"},
            ],
            "terminal_backend": list(BACKEND_MARKERS),
            "screen_before_selection": screen_tail,
            "screen_after_selection": post_selection_tail,
            "config_before": before,
            "config_at_backend": config_at_backend,
            "config_after_selection": after,
            "config_changed_before_backend": before != config_at_backend,
            "config_changed_on_backend_selection": config_at_backend != after,
            "new_artifact_classes": artifact_classes(new_files),
            "new_artifact_classes_on_backend_selection": artifact_classes(backend_new_files),
            "process_clean_exit": exited,
            "fresh_process_readback": readback,
            "cleanup": "Keep current (local) was the only submitted backend; no later setup input was supplied",
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
        "observation_id": "OBS-0055",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY with ANSI screen model"},
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, loopback URL, credentials, session identifiers, timestamps, and redraw bytes are omitted or replaced by placeholders.",
            "Only the configured synthetic loopback provider, displayed palette-model default, and displayed Keep current (local) backend are used; no endpoint, API key, secret, OAuth action, external network, or later backend-specific input is entered.",
            "Config contents are never persisted in the report; only byte counts and SHA-256 digests are recorded, and screen diagnostics pass through path/credential redaction.",
            "The fresh-process readback tests whether the post-selection state is durable; it does not infer persistence from an in-process file change alone.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"].append(run_cancel_case(reference, args.timeout))
        report["cases"].append(run_commit_case(reference, args.timeout))
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        report["failure"] = safe_failure(error)
    emit_report(report, args.report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
