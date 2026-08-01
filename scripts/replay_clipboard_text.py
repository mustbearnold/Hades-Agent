#!/usr/bin/env python3
"""Replay Hades successful text clipboard parity in an isolated direct PTY."""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import pty
import re
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


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "tests/fixtures/parity/OBS-0023-hades-text-clipboard.json"
DEFAULT_BINARY = ROOT / "target/debug/hades"
ANSI_SEQUENCE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[()][0-2A-Z])")
COLUMNS = 120
ROWS = 40


class ClipboardReplayFailure(RuntimeError):
    def __init__(self, case: str, step: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.case = case
        self.step = step
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {"case": self.case, "step": self.step, "message": self.message, **self.details}


def emit_report(report: dict[str, Any], path: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


def normalize(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").replace("\r", "")
    return ANSI_SEQUENCE.sub("", text).replace("\x08", "")


def contains_marker(raw: bytes, marker: str) -> bool:
    text = normalize(raw)
    compact_text = "".join(text.split()).lower()
    compact_marker = "".join(marker.split()).lower()
    return marker in text or compact_marker in compact_text


def set_window_size(fd: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLUMNS, 0, 0))


def read_available(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        try:
            chunk = os.read(fd, 65_536)
        except OSError as error:
            if error.errno in (errno.EIO, errno.EAGAIN):
                break
            raise
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def child_status(pid: int) -> tuple[bool, int | None]:
    try:
        waited_pid, status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True, None
    if waited_pid == 0:
        return False, None
    return True, status


def wait_for(
    pid: int,
    fd: int,
    buffer: bytes,
    case: str,
    step: str,
    predicate: Callable[[bytes], bool],
    timeout: float,
) -> bytes:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(buffer):
            return buffer
        exited, status = child_status(pid)
        if exited:
            buffer += read_available(fd)
            if predicate(buffer):
                return buffer
            raise ClipboardReplayFailure(
                case,
                step,
                "process exited before the PTY assertion",
                {"exit_status": status, "screen_tail": normalize(buffer)[-2000:]},
            )
        readable, _, _ = select.select([fd], [], [], min(0.05, max(0.0, deadline - time.monotonic())))
        if readable:
            buffer += read_available(fd)
    raise ClipboardReplayFailure(
        case,
        step,
        f"timed out after {timeout:.1f}s",
        {"screen_tail": normalize(buffer)[-2000:]},
    )


def drain(pid: int, fd: int, buffer: bytes, duration: float = 0.1) -> bytes:
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        exited, _ = child_status(pid)
        if exited:
            return buffer + read_available(fd)
        readable, _, _ = select.select([fd], [], [], min(0.02, max(0.0, deadline - time.monotonic())))
        if readable:
            buffer += read_available(fd)
    return buffer


def write_bytes(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        offset += os.write(fd, payload[offset:])


def create_xclip(provider_dir: Path, payload_path: Path, log_path: Path) -> None:
    provider_dir.mkdir(parents=True, exist_ok=True)
    xclip = provider_dir / "xclip"
    xclip.write_text(
        "#!{python}\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['HADES_CLIPBOARD_LOG']).write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n"
        "sys.stdout.buffer.write(Path(os.environ['HADES_CLIPBOARD_PAYLOAD']).read_bytes())\n".format(
            python=sys.executable
        ),
        encoding="utf-8",
    )
    xclip.chmod(0o755)
    payload_path.touch()
    log_path.touch()


def spawn(binary: Path, home: Path, provider_dir: Path, payload_path: Path, log_path: Path) -> tuple[int, int]:
    pid, fd = pty.fork()
    if pid == 0:
        environment = os.environ.copy()
        environment.update(
            {
                "TERM": "xterm-256color",
                "HERMES_HOME": str(home),
                "HOME": str(home),
                "PATH": f"{provider_dir}{os.pathsep}{environment.get('PATH', '')}",
                "HADES_CLIPBOARD_PAYLOAD": str(payload_path),
                "HADES_CLIPBOARD_LOG": str(log_path),
            }
        )
        for key in ("WAYLAND_DISPLAY", "WSL_INTEROP", "WSL_DISTRO_NAME"):
            environment.pop(key, None)
        os.execve(str(binary), [str(binary)], environment)

    set_window_size(fd)
    os.set_blocking(fd, False)
    return pid, fd


def stop_child(pid: int, fd: int) -> None:
    exited, _ = child_status(pid)
    if not exited:
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


def load_contract(path: Path) -> dict[str, Any]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ClipboardReplayFailure("contract", "load", str(error)) from error
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise ClipboardReplayFailure("contract", "load", "unsupported clipboard contract")
    steps = contract.get("steps")
    required = {"successful-text", "empty-provider-control"}
    ids = {step.get("id") for step in steps if isinstance(step, dict)} if isinstance(steps, list) else set()
    if ids != required:
        raise ClipboardReplayFailure("contract", "load", f"step ids must be {sorted(required)}")
    return contract


def input_bytes(event: dict[str, str]) -> bytes:
    try:
        return bytes.fromhex(event["bytes_hex"])
    except (KeyError, ValueError) as error:
        raise ClipboardReplayFailure("contract", "input", f"invalid input bytes: {error}") from error


def run_case(binary: Path, case: dict[str, Any], timeout: float, ordinal: int) -> dict[str, Any]:
    case_id = case["id"]
    home = Path(tempfile.mkdtemp(prefix=f"had023-{case_id}-{ordinal}-"))
    provider_dir = home / "bin"
    payload_path = home / "clipboard.payload"
    log_path = home / "clipboard.args"
    payload_path.write_bytes(case.get("provider_payload", "").encode("utf-8"))
    create_xclip(provider_dir, payload_path, log_path)
    pid: int | None = None
    fd: int | None = None
    buffer = b""
    try:
        pid, fd = spawn(binary, home, provider_dir, payload_path, log_path)
        startup_markers = ("Hermes Agent", "Nous Research", "Available Tools", "Available Skills")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case_id,
            "startup",
            lambda current: all(contains_marker(current, marker) for marker in startup_markers),
            timeout,
        )

        for event in case["input_sequence"]:
            write_bytes(fd, input_bytes(event))
            buffer = drain(pid, fd, buffer)

        expected = case["output"]
        markers = expected["screen_markers"]
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case_id,
            "clipboard",
            lambda current: all(contains_marker(current, marker) for marker in markers),
            timeout,
        )
        for marker in expected.get("screen_absent_markers", []):
            if contains_marker(buffer, marker):
                raise ClipboardReplayFailure(case_id, "screen", f"unexpected marker: {marker}")

        buffer = wait_for(
            pid,
            fd,
            buffer,
            case_id,
            "provider",
            lambda _current: log_path.read_text(encoding="utf-8") == expected["provider_arguments"],
            timeout,
        )

        exited, status = child_status(pid)
        if exited:
            raise ClipboardReplayFailure(
                case_id,
                "ready-state",
                "process exited before cleanup",
                {"exit_status": status, "screen_tail": normalize(buffer)[-2000:]},
            )
        write_bytes(fd, b"\x03")
        buffer = wait_for(pid, fd, buffer, case_id, "exit", lambda _current: child_status(pid)[0], timeout)

        return {
            "id": case_id,
            "status": "passed",
            "input_bytes": [event["bytes_hex"] for event in case["input_sequence"]],
            "provider_arguments": expected["provider_arguments"],
            "observed": {
                "screen_markers": markers,
                "screen_absent_markers": expected.get("screen_absent_markers", []),
                "cleanup": "Ctrl+C exits from ready without submission",
            },
            "capture": "direct PTY with TIOCSWINSZ 120x40",
        }
    finally:
        if pid is not None and fd is not None:
            stop_child(pid, fd)
        shutil.rmtree(home, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=5.0)
    arguments = parser.parse_args()
    binary = arguments.binary.resolve()
    contract_path = arguments.contract.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "command": "replay-clipboard-text",
        "passed": False,
        "binary": str(binary),
        "contract": str(contract_path),
        "checks": [],
    }

    try:
        if not binary.is_file():
            raise ClipboardReplayFailure("input", "binary", f"binary not found: {binary}")
        contract = load_contract(contract_path)
        report["contract_observation"] = contract["observation_id"]
        report["reference_observation"] = contract.get("reference_observation")
        report["dimensions"] = contract["reference"]["terminal"]
        for ordinal, case in enumerate(contract["steps"], start=1):
            report["checks"].append(run_case(binary, case, arguments.timeout, ordinal))
        report["passed"] = True
    except ClipboardReplayFailure as error:
        report["failure"] = error.as_dict()
    except (OSError, TypeError, ValueError, KeyError) as error:
        report["failure"] = {"case": "report", "step": "runtime", "message": str(error)}

    try:
        emit_report(report, arguments.report.resolve() if arguments.report else None)
    except OSError as error:
        print(json.dumps({"passed": False, "error": f"could not write report: {error}"}))
        return 2
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
