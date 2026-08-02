#!/usr/bin/env python3
"""Capture the initial Hermes setup wizard and its reversible cancel boundary."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_slash_commands import (
    SOURCE_COMMIT,
    DEFAULT_REFERENCE,
    COLUMNS,
    ROWS,
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
    "Hermes Agent Setup Wizard",
    "Let's configure your Hermes Agent installation.",
    "Press Ctrl+C at any time to exit.",
    "How would you like to set up Hermes?",
    "Quick Setup (Nous Portal)",
    "Full setup",
    "Blank Slate",
    "ESC cancel",
)
MENU_HINT = "↑↓ navigate  ENTER/SPACE select  ESC cancel"
FALLBACK_MARKERS = (
    "Enter for default (1)  Ctrl+C to exit",
    "Select [1-3] (1):",
)


def screen_lines(raw: bytes) -> list[str]:
    screen = Screen(columns=COLUMNS, rows=ROWS)
    screen.feed(raw)
    return [line.rstrip() for line in screen.lines()]


def screen_line(lines: list[str], marker: str) -> str:
    for line in lines:
        if marker in line:
            return line
    raise ProbeFailure(
        "setup-wizard",
        "rendered-screen",
        f"rendered screen did not contain {marker!r}",
        {"screen_lines": lines},
    )


def menu_state(raw: bytes) -> dict[str, Any]:
    lines = screen_lines(raw)
    quick = screen_line(lines, "Quick Setup (Nous Portal)")
    full = screen_line(lines, "Full setup")
    blank = screen_line(lines, "Blank Slate")
    hint = screen_line(lines, MENU_HINT)
    if "●" not in quick or "→" not in quick:
        raise ProbeFailure(
            "setup-wizard",
            "initial-selection",
            "Quick Setup was not the selected cursor row",
            {"screen_lines": lines},
        )
    if "○" not in full or "○" not in blank:
        raise ProbeFailure(
            "setup-wizard",
            "initial-selection",
            "unselected setup rows did not render radio markers",
            {"screen_lines": lines},
        )
    return {
        "hint": MENU_HINT,
        "quick_setup_row": quick,
        "full_setup_row": full,
        "blank_slate_row": blank,
        "hint_row": hint,
        "selected": "Quick Setup (Nous Portal)",
        "cursor": "Quick Setup (Nous Portal)",
    }


def moved_menu_state(raw: bytes) -> dict[str, Any]:
    lines = screen_lines(raw)
    quick = screen_line(lines, "Quick Setup (Nous Portal)")
    full = screen_line(lines, "Full setup")
    blank = screen_line(lines, "Blank Slate")
    if "→" not in full or "○" not in full:
        raise ProbeFailure(
            "setup-wizard-navigation",
            "down-navigation",
            "Down did not move the cursor to Full setup",
            {"screen_lines": lines},
        )
    if "●" not in quick or "→" in quick or "→" in blank:
        raise ProbeFailure(
            "setup-wizard-navigation",
            "down-navigation",
            "Down changed the committed setup choice or another cursor row",
            {"screen_lines": lines},
        )
    return {
        "cursor": "Full setup",
        "selected": "Quick Setup (Nous Portal)",
        "quick_setup_row": quick,
        "full_setup_row": full,
        "blank_slate_row": blank,
    }


def wait_for_setup(pid: int, fd: int, buffer: bytes, case: str, timeout: float) -> bytes:
    return wait_for(
        pid,
        fd,
        buffer,
        case,
        "setup-wizard",
        lambda current: all(contains_marker(current, marker) for marker in SETUP_MARKERS),
        timeout,
    )


def wait_for_stable_menu(
    pid: int, fd: int, buffer: bytes, case: str, timeout: float
) -> tuple[bytes, dict[str, Any]]:
    """Wait for the setup child to hold the rendered radiolist before input.

    The reference emits the first complete radiolist while it is still
    switching the PTY into its interactive cursor mode.  A few equal screen
    samples are not enough to establish that the input reader is ready: a key
    sent in that gap can be consumed by the surrounding command surface.  Keep
    the frame stable for a bounded settling interval before sending a key.
    """
    deadline = time.monotonic() + timeout
    previous: tuple[tuple[str, Any], ...] | None = None
    stable_since: float | None = None
    settle_seconds = 0.5
    while time.monotonic() < deadline:
        try:
            state = menu_state(buffer)
        except ProbeFailure:
            state = None
        if state is not None:
            signature = tuple(sorted(state.items()))
            if signature == previous:
                if stable_since is None:
                    stable_since = time.monotonic()
            else:
                previous = signature
                stable_since = time.monotonic()
            if stable_since is not None and time.monotonic() - stable_since >= settle_seconds:
                return buffer, state
        else:
            previous = None
            stable_since = None
        exited, status = child_status(pid)
        if exited:
            buffer += read_available(fd)
            raise ProbeFailure(
                case,
                "stable-menu",
                "Hermes exited before the setup radiolist stabilized",
                {"exit_status": status, "screen_lines": screen_lines(buffer)},
            )
        buffer = drain(pid, fd, buffer, 0.05)
    raise ProbeFailure(
        case,
        "stable-menu",
        f"timed out after {timeout:.1f}s waiting for a stable setup radiolist",
        {"screen_lines": screen_lines(buffer)},
    )


def open_setup(reference: Path, home: Path, case: str, timeout: float) -> tuple[int, int, bytes]:
    pid, fd, buffer = start_ready(reference, home, case, timeout)
    write_bytes(fd, b"/setup\r")
    buffer = drain(pid, fd, buffer, 0.7)
    # The slash completion is accepted first; the second Enter submits /setup.
    write_bytes(fd, b"\r")
    return pid, fd, wait_for_setup(pid, fd, buffer, case, timeout)


def run_escape(reference: Path, timeout: float) -> dict[str, Any]:
    case = "setup-wizard-escape"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-setup-escape-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        pid, fd, buffer = open_setup(reference, home, case, timeout)
        buffer, initial = wait_for_stable_menu(pid, fd, buffer, case, timeout)
        write_bytes(fd, b"\x1b")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "escape-fallback",
            lambda current: all(contains_marker(current, marker) for marker in FALLBACK_MARKERS),
            timeout,
        )
        buffer = drain(pid, fd, buffer, 0.2)
        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "/setup"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Escape"},
            ],
            "initial_surface": {
                "wizard_markers": list(SETUP_MARKERS),
                "rendered_menu": initial,
            },
            "escape_result": {
                "state": "numbered-fallback",
                "observed_markers": list(FALLBACK_MARKERS),
                "setup_option_submitted": False,
            },
            "cleanup": "Ctrl+C interrupted the fallback prompt and exited cleanly",
            "clean_exit": exited,
        }
    except ProbeFailure:
        raise
    finally:
        if pid != -1:
            stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def run_navigation(reference: Path, timeout: float) -> dict[str, Any]:
    case = "setup-wizard-down-navigation"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-setup-navigation-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        pid, fd, buffer = open_setup(reference, home, case, timeout)
        buffer, initial = wait_for_stable_menu(pid, fd, buffer, case, timeout)
        write_bytes(fd, b"\x1b[B")
        buffer = drain(pid, fd, buffer, 0.8)
        down_encoding_fallback = False
        if not _has_full_setup_cursor(buffer):
            # The reference switches to application-cursor mode on some PTY
            # paths. Treat the equivalent Down encoding as the same key only
            # when the first encoding left the stable menu unchanged.
            write_bytes(fd, b"\x1bOB")
            down_encoding_fallback = True
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "down-navigation",
            lambda current: _has_full_setup_cursor(current),
            timeout,
        )
        buffer = drain(pid, fd, buffer, 0.2)
        moved = moved_menu_state(buffer)
        write_bytes(fd, b"\x03")
        buffer = drain(pid, fd, buffer, 0.3)
        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "/setup"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Enter"},
                {
                    "kind": "key",
                    "value": "Down",
                    "bytes_hex": "1b 5b 42",
                    "fallback_bytes_hex": "1b 4f 42",
                },
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03"},
            ],
            "initial_cursor": initial["cursor"],
            "after_down": moved,
            "down_encoding_fallback": down_encoding_fallback,
            "setup_option_submitted": False,
            "cleanup": "Ctrl+C exited cleanly without selecting a setup option",
            "clean_exit": exited,
        }
    except ProbeFailure:
        raise
    finally:
        if pid != -1:
            stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def _has_full_setup_cursor(raw: bytes) -> bool:
    try:
        return "→" in screen_line(screen_lines(raw), "Full setup")
    except ProbeFailure:
        return False


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
    if "screen_lines" in details:
        details["screen_lines"] = [safe_tail(line.encode()) for line in details["screen_lines"]]
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
        "observation_id": "OBS-0040",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with ANSI screen model and normalized stable markers",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, loopback URL, credentials, session IDs, timestamps, and animated redraw bytes are omitted or replaced by placeholders.",
            "The configured provider points at an intentionally absent loopback endpoint; no external provider, OAuth flow, credential, or model response is exercised.",
            "The setup title and explanation are asserted from the normalized PTY stream; the radiolist rows and cursor are asserted from the 120x40 ANSI screen model.",
            "Escape is sent before any setup option is submitted. Hermes returns from the curses radiolist to its numbered fallback prompt, where Ctrl+C performs the bounded cleanup.",
            "The Down case records cursor movement only and is interrupted before any setup option is submitted.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"].append(run_escape(reference, args.timeout))
        report["cases"].append(run_navigation(reference, args.timeout))
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        report["failure"] = safe_failure(error)
    emit_report(report, args.report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
