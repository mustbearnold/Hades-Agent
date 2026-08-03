#!/usr/bin/env python3
"""Replay the OBS-0034 palette controls against the Hades binary."""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import pty
import select
import shutil
import signal
import struct
import sys
import tempfile
import termios
import time
from pathlib import Path
from typing import Any, Callable

from replay_composer import finish_hold_provider, hold_provider_environment, start_hold_provider
from probe_hermes_terminal_palette import (
    COLUMNS,
    ROWS,
    Screen,
    child_status,
    contains_marker,
    normalized,
    sgr_summary,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BINARY = ROOT / "target/debug/hades"
DEFAULT_CONTRACT = ROOT / "tests/fixtures/parity/OBS-0035-hades-terminal-palette.json"
SOURCE_COMMIT = "e444d165807f489b5c1ab8e4a612c8d09c2e67a2"
Predicate = Callable[[bytes], bool]


class ReplayFailure(RuntimeError):
    """Raised when a Hades palette replay assertion fails."""

    def __init__(self, case: str, step: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.case = case
        self.step = step
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {"case": self.case, "step": self.step, "message": self.message, **self.details}


def read_available(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        try:
            chunk = os.read(fd, 65_536)
        except OSError as error:
            if error.errno in {errno.EIO, errno.EAGAIN}:
                break
            raise
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def write_bytes(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        offset += os.write(fd, payload[offset:])


def set_window_size(fd: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLUMNS, 0, 0))


def wait_for(
    pid: int,
    fd: int,
    buffer: bytes,
    case: str,
    step: str,
    predicate: Predicate,
    timeout: float,
) -> bytes:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(buffer):
            return buffer
        if child_status(pid)[0]:
            buffer += read_available(fd)
            if predicate(buffer):
                return buffer
            raise ReplayFailure(case, step, "Hades exited before the PTY assertion", {
                "screen_tail": normalized(buffer)[-2000:],
            })
        readable, _, _ = select.select([fd], [], [], min(0.05, max(0.0, deadline - time.monotonic())))
        if readable:
            buffer += read_available(fd)
    raise ReplayFailure(case, step, f"timed out after {timeout:.1f}s", {
        "screen_tail": normalized(buffer)[-2000:],
    })


def drain(pid: int, fd: int, buffer: bytes, duration: float = 0.12) -> bytes:
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        if child_status(pid)[0]:
            return buffer + read_available(fd)
        readable, _, _ = select.select([fd], [], [], min(0.02, max(0.0, deadline - time.monotonic())))
        if readable:
            buffer += read_available(fd)
    return buffer


def spawn(binary: Path, home: Path, provider_environment: dict[str, str]) -> tuple[int, int]:
    pid, fd = pty.fork()
    if pid == 0:
        environment = os.environ.copy()
        environment.update(
            {
                "TERM": "xterm-256color",
                "COLUMNS": str(COLUMNS),
                "LINES": str(ROWS),
                "HERMES_HOME": str(home),
                "HOME": str(home),
                **provider_environment,
            }
        )
        os.execve(str(binary), [str(binary)], environment)
    set_window_size(fd)
    os.set_blocking(fd, False)
    return pid, fd


def stop(pid: int, fd: int) -> None:
    if not child_status(pid)[0]:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
    try:
        os.close(fd)
    except OSError:
        pass


def surface_record(raw_delta: bytes, full_buffer: bytes, markers: list[str]) -> dict[str, Any]:
    screen = Screen()
    screen.feed(full_buffer)
    sgr = sgr_summary(raw_delta)
    return {
        "raw_delta": sgr,
        "marker_styles": {marker: screen.marker_style(marker) for marker in markers},
        "screen_tail": normalized(full_buffer)[-1200:],
    }


def load_contract(path: Path) -> dict[str, Any]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReplayFailure("contract", "load", str(error)) from error
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise ReplayFailure("contract", "load", "unsupported OBS-0035 contract")
    steps = contract.get("steps")
    if not isinstance(steps, list):
        raise ReplayFailure("contract", "load", "OBS-0035 steps must be an array")
    expected = {"startup", "composer", "busy", "interrupted", "setup-required"}
    actual = {step.get("id") for step in steps if isinstance(step, dict)}
    if actual != expected:
        raise ReplayFailure("contract", "load", f"step ids must be {sorted(expected)}")
    return contract


def step_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {step["id"]: step for step in contract["steps"]}


def assert_surface(case: str, step_id: str, observed: dict[str, Any], expected: dict[str, Any]) -> None:
    markers = expected.get("landmark_styles", {})
    if not isinstance(markers, dict):
        raise ReplayFailure(case, step_id, "landmark_styles must be an object")
    observed_markers = observed["marker_styles"]
    for marker, expected_landmark in markers.items():
        actual = observed_markers.get(marker)
        if actual is None:
            raise ReplayFailure(case, step_id, f"landmark marker was not rendered: {marker}")
        expected_style = expected_landmark.get("style", expected_landmark)
        if actual["style"] != expected_style:
            raise ReplayFailure(
                case,
                step_id,
                f"style mismatch for {marker}",
                {"expected": expected_style, "actual": actual["style"]},
            )

    observed_sequences = {entry["bytes_hex"] for entry in observed["raw_delta"]["sgr_sequences"]}
    for sequence in expected.get("required_sgr_sequences_hex", []):
        if sequence not in observed_sequences:
            raise ReplayFailure(case, step_id, f"required SGR sequence was not emitted: {sequence}")


def run_ready_sequence(binary: Path, steps: dict[str, dict[str, Any]], timeout: float) -> dict[str, Any]:
    case = "ready-palette"
    home = Path(tempfile.mkdtemp(prefix="had035-ready-"))
    provider, provider_thread = start_hold_provider()
    pid, fd = spawn(binary, home, hold_provider_environment(provider))
    buffer = b""
    try:
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "startup",
            lambda current: all(
                contains_marker(current, marker)
                for marker in ("Hades Agent", "Hades", "Available Tools", "Available Skills", "ready")
            ),
            timeout,
        )
        startup = surface_record(buffer, buffer, [
            "Hades Agent", "Hades", "Available Tools", "Available Skills", "ready"
        ])
        assert_surface(case, "startup", startup, steps["startup"]["output"])

        composer_start = len(buffer)
        write_bytes(fd, b"palette-ready")
        buffer = wait_for(pid, fd, buffer, case, "composer", lambda current: contains_marker(current, "palette-ready"), timeout)
        buffer = drain(pid, fd, buffer)
        composer = surface_record(buffer[composer_start:], buffer, ["palette-ready", "ready"])
        assert_surface(case, "composer", composer, steps["composer"]["output"])

        busy_start = len(buffer)
        write_bytes(fd, b"\r")
        buffer = wait_for(pid, fd, buffer, case, "busy", lambda current: contains_marker(current, "Ctrl+C to interrupt"), timeout)
        buffer = drain(pid, fd, buffer, 0.05)
        busy = surface_record(buffer[busy_start:], buffer, ["Ctrl+C to interrupt"])
        assert_surface(case, "busy", busy, steps["busy"]["output"])

        interrupted_start = len(buffer)
        write_bytes(fd, b"\x03")
        buffer = wait_for(pid, fd, buffer, case, "interrupted", lambda current: contains_marker(current, "interrupted"), timeout)
        buffer = drain(pid, fd, buffer)
        interrupted = surface_record(buffer[interrupted_start:], buffer, ["interrupted", "✓"])
        assert_surface(case, "interrupted", interrupted, steps["interrupted"]["output"])

        write_bytes(fd, b"\x03")
        wait_for(pid, fd, buffer, case, "cleanup", lambda current: child_status(pid)[0], timeout)
        return {
            "id": case,
            "status": "passed",
            "surfaces": {
                "startup": startup,
                "composer": composer,
                "busy": busy,
                "interrupted": interrupted,
            },
            "cleanup": "busy turn interrupted and ready process exited cleanly",
        }
    finally:
        stop(pid, fd)
        finish_hold_provider(provider, provider_thread)
        shutil.rmtree(home, ignore_errors=True)


def run_setup_case(binary: Path, steps: dict[str, dict[str, Any]], timeout: float) -> dict[str, Any]:
    case = "setup-required-palette"
    home = Path(tempfile.mkdtemp(prefix="had035-setup-"))
    provider, provider_thread = start_hold_provider()
    provider_environment = hold_provider_environment(provider)
    provider_environment["HADES_PROVIDER_BASE_URL"] = ""
    pid, fd = spawn(binary, home, provider_environment)
    buffer = b""
    try:
        buffer = wait_for(pid, fd, buffer, case, "startup", lambda current: contains_marker(current, "Hades Agent"), timeout)
        setup_start = len(buffer)
        write_bytes(fd, b"/help\r")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "setup-required",
            lambda current: contains_marker(current, "Setup Required"),
            max(timeout, 12.0),
        )
        buffer = drain(pid, fd, buffer)
        setup = surface_record(buffer[setup_start:], buffer, ["Setup Required", "model provider", "/model", "/setup", "/help"])
        assert_surface(case, "setup-required", setup, steps["setup-required"]["output"])

        write_bytes(fd, b"\x03")
        buffer = drain(pid, fd, buffer, 0.15)
        write_bytes(fd, b"\x03")
        wait_for(pid, fd, buffer, case, "cleanup", lambda current: child_status(pid)[0], timeout)
        return {
            "id": case,
            "status": "passed",
            "surfaces": {"setup-required": setup},
            "cleanup": "two Ctrl+C presses exited cleanly from setup-required",
        }
    finally:
        stop(pid, fd)
        finish_hold_provider(provider, provider_thread)
        shutil.rmtree(home, ignore_errors=True)


def emit_report(report: dict[str, Any], path: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    binary = args.binary.resolve()
    contract_path = args.contract.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "command": "replay-terminal-palette",
        "observation_id": "OBS-0035",
        "reference_observation": "OBS-0034",
        "binary": "<hades-binary>",
        "contract": "tests/fixtures/parity/OBS-0035-hades-terminal-palette.json",
        "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY raw bytes"},
        "cases": [],
        "passed": False,
    }
    try:
        if not binary.is_file():
            raise ReplayFailure("precondition", "binary", f"Hades binary does not exist: {binary}")
        contract = load_contract(contract_path)
        steps = step_map(contract)
        report["cases"].append(run_ready_sequence(binary, steps, args.timeout))
        report["cases"].append(run_setup_case(binary, steps, args.timeout))
        report["passed"] = True
    except (OSError, ReplayFailure, RuntimeError, ValueError) as error:
        report["failure"] = error.as_dict() if isinstance(error, ReplayFailure) else str(error)
    emit_report(report, args.report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
