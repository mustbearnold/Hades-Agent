#!/usr/bin/env python3
"""Capture the safe configured Hermes /help Escape lifecycle boundary."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from probe_hermes_help_catalog import (
    MAIN_SURFACE_MARKERS,
    panel_state,
    screen_lines,
    wait_for_stable_help,
)
from probe_hermes_slash_commands import (
    DEFAULT_REFERENCE,
    ProbeFailure,
    child_status,
    clean_exit,
    contains_marker,
    drain,
    safe_tail,
    start_ready,
    stop,
    wait_for,
    write_bytes,
)


SOURCE_COMMIT = "e444d165807f489b5c1ab8e4a612c8d09c2e67a2"


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "configured-help-escape-lifecycle"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-help-lifecycle-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        pid, fd, buffer = start_ready(reference, home, case, timeout)
        write_bytes(fd, b"/help\r")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "help-landmarks",
            lambda current: all(
                contains_marker(current, marker)
                for marker in ("Show available commands", "/help for commands")
            ),
            timeout,
        )
        buffer, before_escape, stable_samples = wait_for_stable_help(pid, fd, buffer, timeout)
        before_lines = screen_lines(buffer)
        if not all(
            any(marker in line for line in before_lines)
            for marker in MAIN_SURFACE_MARKERS
        ):
            raise ProbeFailure(case, "before-escape", "stable help surface lost a main marker")

        write_bytes(fd, b"\x1b")
        buffer = drain(pid, fd, buffer, 0.5)
        try:
            after_escape = panel_state(buffer)
        except ProbeFailure:
            after_escape = None
        after_lines = screen_lines(buffer)
        alive_after_escape = not child_status(pid)[0]
        if after_escape is not None:
            lifecycle = "preserved"
        elif alive_after_escape:
            lifecycle = "changed_without_stable_help_panel"
        else:
            lifecycle = "process_exited"

        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)
        if not exited:
            raise ProbeFailure(case, "cleanup", "Hermes did not exit after bounded Ctrl+C cleanup")

        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "/help", "bytes_hex": "2f 68 65 6c 70"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {"kind": "key", "value": "Escape", "bytes_hex": "1b", "meaning": "safe lifecycle probe"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "bounded cleanup"},
            ],
            "before_escape": {
                "help_panel": before_escape,
                "state": "ready",
                "main_surface_markers": list(MAIN_SURFACE_MARKERS),
                "stable_samples": stable_samples,
            },
            "after_escape": {
                "lifecycle": lifecycle,
                "help_panel_preserved": after_escape is not None,
                "composer_preserved": any("❯ /help" in line for line in after_lines),
                "ready_marker_present": any("─ ready │" in line for line in after_lines),
                "process_alive_before_cleanup": alive_after_escape,
            },
            "provider_request": "not observed; configured loopback endpoint was intentionally absent",
            "side_effects": "Only /help, Escape, and bounded Ctrl+C cleanup were exercised; no side-effecting command or external network was used",
            "clean_exit": True,
        }
    except ProbeFailure:
        raise
    finally:
        if pid != -1:
            stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def safe_failure(error: BaseException) -> dict[str, Any] | str:
    if not isinstance(error, ProbeFailure):
        return str(error)
    failure = {"case": error.case, "step": error.step, "message": error.message}
    failure.update(error.details)
    if "screen_tail" not in failure:
        failure["screen_tail"] = safe_tail(b"")
    return failure


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0100",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": 120,
                "rows": 40,
                "capture": "fresh direct PTY with normalized stable landmarks",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, loopback URL, credentials, session IDs, timestamps, dynamic inventories, and raw redraw bytes are omitted or represented by stable markers.",
            "The configured loopback endpoint is intentionally absent; the bounded /help and Escape probe exercises no provider request, credential, OAuth action, or external network.",
            "Escape is probed once as a safe lifecycle key; no side-effecting slash command or inferred argument semantics are exercised.",
            "The complete command catalog, dynamic inventory, focus model, and command-specific help behavior remain unknown.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure(case="reference", step="precondition", message=f"reference checkout does not exist: {reference}")
        report["cases"].append(run_case(reference, args.timeout))
        report["unknowns"] = [
            "The complete slash-command catalog, aliases, arguments, command-specific state, and help pagination remain unknown.",
            "Provider/tool/skill counts, discovery timing, redraw ordering, and dynamic command inventory remain outside this lifecycle boundary.",
            "Only one safe Escape press was observed; other focus, navigation, close, and repeated-help sequences remain unknown.",
        ]
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        report["failure"] = safe_failure(error)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized, encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
