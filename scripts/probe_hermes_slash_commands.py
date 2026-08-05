#!/usr/bin/env python3
"""Capture a bounded Hermes slash-command/configuration surface through a PTY."""

from __future__ import annotations

import argparse
import json
import os
import pty
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_terminal_palette import (
    COLUMNS,
    DEFAULT_REFERENCE,
    ProbeFailure,
    child_status,
    drain,
    normalized,
    set_window_size,
    stop,
    wait_for,
    write_bytes,
)


ROWS = 40
SOURCE_COMMIT = "e444d165807f489b5c1ab8e4a612c8d09c2e67a2"
BASE_URL = "http://127.0.0.1:8765/v1"
SYNTHETIC_KEY = "synthetic-probe-key"
SENSITIVE_ENV_PARTS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "ACCESS_KEY")
ANSI_OR_PRIVATE = re.compile(r"(?:/tmp|/home)/[^\s\r\n]+|synthetic-probe-key", re.IGNORECASE)


def contains_marker(raw: bytes, marker: str) -> bool:
    text = normalized(raw)
    compact_text = "".join(text.split()).lower()
    compact_marker = "".join(marker.split()).lower()
    return marker.lower() in text.lower() or compact_marker in compact_text


def safe_tail(raw: bytes) -> str:
    """Keep failure diagnostics useful without persisting local paths or secrets."""

    text = normalized(raw)[-2400:]
    text = ANSI_OR_PRIVATE.sub("<redacted>", text)
    text = re.sub(r"(?i)(api[_ -]?key|token|secret|password)\s*[:=]\s*\S+", r"\1=<redacted>", text)
    return text


def write_ready_config(home: Path) -> None:
    (home / "config.yaml").write_text(
        "model:\n"
        "  provider: custom\n"
        "  default: palette-model\n"
        f"  base_url: {BASE_URL}\n"
        f"  api_key: {SYNTHETIC_KEY}\n"
        "custom_providers:\n"
        "  - name: palette-loopback\n"
        f"    base_url: {BASE_URL}\n"
        f"    api_key: {SYNTHETIC_KEY}\n"
        "    model: palette-model\n",
        encoding="utf-8",
    )


def safe_environment(reference: Path, home: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(part in key.upper() for part in SENSITIVE_ENV_PARTS)
    }
    environment.update(
        {
            "TERM": "xterm-256color",
            "COLUMNS": str(COLUMNS),
            "LINES": str(ROWS),
            "HERMES_HOME": str(home),
            "HOME": str(home),
            "HERMES_TUI_DIR": str(reference / "ui-tui"),
            "HERMES_TUI_THEME": "dark",
            "HERMES_TUI_STARTUP_TIMEOUT_MS": "8000",
            "HERMES_TUI_SLASH_TIMEOUT_S": "5",
            "UV_NO_CONFIG": "1",
        }
    )
    for key in (
        "TMUX",
        "STY",
        "WAYLAND_DISPLAY",
        "WSL_INTEROP",
        "WSL_DISTRO_NAME",
        # GUI-only marker: the pinned reference gates its four desktop tools
        # (read_terminal/close_terminal/open_preview/focus_pane) on
        # HERMES_DESKTOP. When this harness runs from inside the Hermes
        # desktop app, the live environment leaks the marker into the
        # reference child and the advertised tool inventory drifts from the
        # anchored 31-tool contract. Strip it so observations match the
        # plain-CLI reference environment.
        "HERMES_DESKTOP",
        # Desktop-app install path: the desktop app exports PYTHONPATH pointing
        # at its own hermes-agent copy, which would shadow the pinned
        # checkout's modules (different tool descriptions/schemas) in the
        # reference child. Strip it so the reference resolves its own code.
        "PYTHONPATH",
        # Hermes runtime markers leaked by desktop-app, kanban-worker, and
        # cron sessions: the reference child would otherwise observe the
        # caller's serve/session/web-dist/ask state instead of a plain CLI
        # launch (same leak class as HERMES_DESKTOP above; OBS-0116 documents
        # the drift). Strip every HERMES_* variable the harness did not set
        # itself so observations match the plain-CLI reference environment
        # regardless of how the gate was launched.
        "HERMES_SERVE_HEADLESS",
        "HERMES_SESSION_ID",
        "HERMES_WEB_DIST",
        "HERMES_EXEC_ASK",
        "HERMES_REAL_HOME",
    ):
        environment.pop(key, None)
    for key in list(environment):
        if key.startswith("HERMES_KANBAN_"):
            environment.pop(key)
    return environment


def spawn(reference: Path, home: Path, *, configured: bool) -> tuple[int, int]:
    if configured:
        write_ready_config(home)
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(reference)
        os.execvpe("uv", ["uv", "run", "hermes", "--tui"], safe_environment(reference, home))
    set_window_size(fd, COLUMNS, ROWS)
    os.set_blocking(fd, False)
    return pid, fd


def wait_for_exit(pid: int, fd: int, buffer: bytes, case: str, timeout: float) -> tuple[bytes, bool]:
    deadline = time.monotonic() + timeout
    while not child_status(pid)[0] and time.monotonic() < deadline:
        buffer = drain(pid, fd, buffer, min(0.05, max(0.0, deadline - time.monotonic())))
    return buffer, child_status(pid)[0]


def clean_exit(pid: int, fd: int, buffer: bytes, case: str, timeout: float) -> tuple[bytes, bool]:
    """Use the observed ready-state exit control, tolerating a setup child."""

    for _ in range(2):
        if child_status(pid)[0]:
            break
        try:
            write_bytes(fd, b"\x03")
        except OSError:
            break
        buffer = drain(pid, fd, buffer, 0.25)
    buffer, exited = wait_for_exit(pid, fd, buffer, case, timeout)
    if not exited:
        raise ProbeFailure(case, "cleanup", "Hermes did not exit after bounded Ctrl+C cleanup", {"screen_tail": safe_tail(buffer)})
    return buffer, exited


def start_ready(reference: Path, home: Path, case: str, timeout: float) -> tuple[int, int, bytes]:
    pid, fd = spawn(reference, home, configured=True)
    try:
        buffer = wait_for(
            pid,
            fd,
            b"",
            case,
            "startup",
            lambda current: contains_marker(current, "Hermes Agent") and contains_marker(current, "ready"),
            timeout,
        )
        return pid, fd, buffer
    except BaseException:
        stop(pid, fd)
        raise


def run_help(reference: Path, timeout: float) -> dict[str, Any]:
    case = "configured-help"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-slash-help-"))
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
            "help-surface",
            lambda current: all(
                contains_marker(current, marker)
                for marker in ("/help", "Show available commands", "Available Skills", "/help for commands")
            ),
            timeout,
        )
        buffer = drain(pid, fd, buffer)
        buffer, _ = clean_exit(pid, fd, buffer, case, timeout)
        return {
            "id": case,
            "status": "passed",
            "input": [{"kind": "text", "value": "/help"}, {"kind": "key", "value": "Enter"}],
            "observed_markers": ["/help", "Show available commands", "Available Skills", "/help for commands"],
            "state": "ready",
            "model_request": "not observed",
            "cleanup": "Ctrl+C exited cleanly from the ready surface",
        }
    except ProbeFailure:
        raise
    finally:
        if pid != -1:
            stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def run_model(reference: Path, timeout: float) -> dict[str, Any]:
    case = "configured-model-picker"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-slash-model-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        pid, fd, buffer = start_ready(reference, home, case, timeout)
        write_bytes(fd, b"/model\r")
        buffer = drain(pid, fd, buffer, 0.5)
        write_bytes(fd, b"\r")
        markers = [
            "Select provider (step 1/2)",
            "Full model IDs on the next step",
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
            "model-picker",
            lambda current: all(contains_marker(current, marker) for marker in markers),
            timeout,
        )
        write_bytes(fd, b"\x1b")
        buffer = drain(pid, fd, buffer, 0.35)
        buffer, _ = clean_exit(pid, fd, buffer, case, timeout)
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "/model"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Enter"},
            ],
            "observed_markers": markers,
            "state": "provider-picker",
            "dynamic_surface": "provider rows, counts, spinner text, and discovery timing are not fixed by this observation",
            "cleanup": "Escape closed the picker; bounded Ctrl+C cleanup exited cleanly",
        }
    except ProbeFailure:
        raise
    finally:
        if pid != -1:
            stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def run_setup(reference: Path, timeout: float) -> dict[str, Any]:
    case = "configured-setup-handoff"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-slash-setup-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        pid, fd, buffer = start_ready(reference, home, case, timeout)
        write_bytes(fd, b"/setup\r")
        buffer = drain(pid, fd, buffer, 0.5)
        write_bytes(fd, b"\r")
        markers = [
            "Hermes Agent Setup Wizard",
            "Let's configure your Hermes Agent installation.",
            "Press Ctrl+C at any time to exit.",
            "How would you like to set up Hermes?",
            "Quick Setup (Nous Portal)",
            "Full setup",
            "Blank Slate",
            "ESC cancel",
        ]
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "setup-wizard",
            lambda current: all(contains_marker(current, marker) for marker in markers),
            timeout,
        )
        buffer = drain(pid, fd, buffer, 0.2)
        buffer, _ = clean_exit(pid, fd, buffer, case, timeout)
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "/setup"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Enter"},
            ],
            "observed_markers": markers,
            "state": "external-setup-wizard",
            "side_effects": "No setup option was selected; OAuth, credentials, and network configuration were not exercised",
            "cleanup": "Ctrl+C exited the setup flow cleanly",
        }
    except ProbeFailure:
        raise
    finally:
        if pid != -1:
            stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def run_unknown(reference: Path, timeout: float) -> dict[str, Any]:
    case = "configured-unknown-command"
    command = "/not-a-real-hermes-command"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-slash-unknown-"))
    home = root / "home"
    home.mkdir()
    pid = fd = -1
    buffer = b""
    try:
        pid, fd, buffer = start_ready(reference, home, case, timeout)
        write_bytes(fd, f"{command}\r".encode("utf-8"))
        buffer = drain(pid, fd, buffer, 0.5)
        write_bytes(fd, b"\r")
        markers = ["Unknown command:", command, "Type /help for available commands"]
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "unknown-command",
            lambda current: all(contains_marker(current, marker) for marker in markers),
            timeout,
        )
        buffer = drain(pid, fd, buffer)
        buffer, _ = clean_exit(pid, fd, buffer, case, timeout)
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": command},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Enter"},
            ],
            "observed_markers": markers,
            "state": "ready",
            "outcome": "unknown command is reported in the transcript and does not enter a model/busy turn",
            "cleanup": "Ctrl+C exited cleanly from the ready surface",
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
        "observation_id": "OBS-0036",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY normalized markers"},
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, loopback URL, credentials, session IDs, timestamps, and animated redraw bytes are omitted or replaced by placeholders.",
            "The configured provider uses a loopback endpoint that is intentionally not served; no external provider, OAuth flow, credential, or model response is exercised.",
            "The provider list, tool counts, spinner text, discovery timing, and redraw ordering are dynamic; only stable text landmarks are asserted.",
            "The first Enter accepts slash completion and the second Enter submits /model, /setup, and the unknown command in this captured interaction.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"].append(run_help(reference, args.timeout))
        report["cases"].append(run_model(reference, args.timeout))
        report["cases"].append(run_setup(reference, args.timeout))
        report["cases"].append(run_unknown(reference, args.timeout))
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        report["failure"] = error.as_dict() if isinstance(error, ProbeFailure) else str(error)
    emit_report(report, args.report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
