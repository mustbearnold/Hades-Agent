#!/usr/bin/env python3
"""Probe Hermes remote-shell OSC52-first clipboard behavior in a direct PTY."""

from __future__ import annotations

import argparse
import base64
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


DEFAULT_REFERENCE = Path("/tmp/hades-hermes-ref-X3bLd0")
COLUMNS = 120
ROWS = 40
OSC52_QUERY = b"\x1b]52;c;?\x07"
DA1_SENTINEL = b"\x1b[c"
DA1_RESPONSE = b"\x1b[?62c"
ANSI_SEQUENCE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[()][0-2A-Z])")


class ProbeFailure(RuntimeError):
    def __init__(self, case: str, step: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.case = case
        self.step = step
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {"case": self.case, "step": self.step, "message": self.message, **self.details}


def normalize(raw: bytes) -> str:
    return ANSI_SEQUENCE.sub("", raw.decode("utf-8", errors="replace").replace("\r", ""))


def contains(raw: bytes, marker: str) -> bool:
    text = normalize(raw)
    return marker in text or "".join(marker.split()).lower() in "".join(text.split()).lower()


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
            raise ProbeFailure(
                case,
                step,
                "Hermes exited before the PTY assertion",
                {"exit_status": status, "screen_tail": normalize(buffer)[-2000:]},
            )
        readable, _, _ = select.select([fd], [], [], 0.05)
        if readable:
            buffer += read_available(fd)
    raise ProbeFailure(case, step, f"timed out after {timeout:.1f}s", {"screen_tail": normalize(buffer)[-2000:]})


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


def spawn(
    reference: Path,
    home: Path,
    fake_bin: Path,
    native_payload: str,
    native_log: Path,
) -> tuple[int, int]:
    pid, fd = pty.fork()
    if pid == 0:
        environment = os.environ.copy()
        environment.update(
            {
                "TERM": "xterm-256color",
                "HERMES_HOME": str(home),
                "HOME": str(home),
                "PATH": f"{fake_bin}{os.pathsep}{environment.get('PATH', '')}",
                "HERMES_NATIVE_PAYLOAD": native_payload,
                "HERMES_NATIVE_LOG": str(native_log),
                "SSH_TTY": "/dev/pts/999",
                "UV_NO_CONFIG": "1",
            }
        )
        for key in ("TMUX", "STY", "WAYLAND_DISPLAY", "WSL_INTEROP", "WSL_DISTRO_NAME"):
            environment.pop(key, None)
        os.chdir(reference)
        os.execvpe("uv", ["uv", "run", "hermes", "--tui"], environment)

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLUMNS, 0, 0))
    os.set_blocking(fd, False)
    return pid, fd


def stop(pid: int, fd: int) -> None:
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


def make_fake_xclip(root: Path) -> Path:
    fake_bin = root / "bin"
    fake_bin.mkdir()
    (fake_bin / "xclip").write_text(
        "#!{python}\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['HERMES_NATIVE_LOG']).write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n"
        "sys.stdout.write(os.environ['HERMES_NATIVE_PAYLOAD'])\n".format(python=sys.executable),
        encoding="utf-8",
    )
    (fake_bin / "xclip").chmod(0o755)
    return fake_bin


def query_position(buffer: bytes, start: int) -> int:
    position = buffer.find(OSC52_QUERY, start)
    if position == -1:
        raise ValueError("OSC52 query was not found")
    return position


def run_case(reference: Path, name: str, respond: bool, timeout: float) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix=f"had024-{name}-"))
    fake_bin = make_fake_xclip(root)
    home = root / "home"
    home.mkdir()
    native_log = root / "xclip.log"
    native_payload = "native-fallback\n"
    pid, fd = spawn(reference, home, fake_bin, native_payload, native_log)
    buffer = b""
    try:
        buffer = wait_for(pid, fd, buffer, name, "startup", lambda current: contains(current, "Hermes Agent"), timeout)
        draft = "remote-seed" if respond else "fallback-seed"
        write_bytes(fd, draft.encode("utf-8"))
        buffer = wait_for(pid, fd, buffer, name, "draft", lambda current: contains(current, draft), timeout)
        start = len(buffer)
        write_bytes(fd, b"\x16")
        buffer = wait_for(pid, fd, buffer, name, "osc52-query", lambda current: OSC52_QUERY in current[start:], timeout)
        query_at = query_position(buffer, start)

        osc_payload = "osc-remote  \nline-two\n\n"
        response_at = query_at + len(OSC52_QUERY)
        if respond:
            response = b"\x1b]52;c;" + base64.b64encode(osc_payload.encode("utf-8")) + b"\x07"
            write_bytes(fd, response)
            buffer = wait_for(
                pid,
                fd,
                buffer,
                name,
                "osc52-flush",
                lambda current: DA1_SENTINEL in current[response_at:],
                timeout,
            )
            sentinel_at = buffer.find(DA1_SENTINEL, response_at)
            barrier_count = max(1, buffer.count(DA1_SENTINEL))
            write_bytes(fd, DA1_RESPONSE * barrier_count)
            buffer = wait_for(pid, fd, buffer, name, "osc52-text", lambda current: contains(current, "osc-remote"), timeout)
            buffer = drain(pid, fd, buffer, 0.2)
            if native_log.exists():
                raise ProbeFailure(name, "provider-order", "native xclip ran after a usable OSC52 response")
            outcome = {
                "status": "passed",
                "path": "OSC52 response won before native provider",
                "osc52_query_offset": query_at,
                "osc52_sentinel_offset": sentinel_at,
                "osc52_query_bytes_hex": OSC52_QUERY.hex(" "),
                "osc52_response_bytes_hex": response.hex(" "),
                "osc52_text": osc_payload[:-2],
                "da1_barriers_answered": barrier_count,
                "native_provider": "not invoked",
            }
        else:
            buffer = wait_for(
                pid,
                fd,
                buffer,
                name,
                "osc52-timeout-flush",
                lambda current: DA1_SENTINEL in current[response_at:],
                timeout,
            )
            sentinel_at = buffer.find(DA1_SENTINEL, response_at)
            barrier_count = max(1, buffer.count(DA1_SENTINEL))
            write_bytes(fd, DA1_RESPONSE * barrier_count)
            buffer = wait_for(pid, fd, buffer, name, "native-fallback", lambda current: contains(current, "native-fallback"), timeout)
            provider_log = native_log.read_text(encoding="utf-8") if native_log.exists() else ""
            if provider_log != "-selection clipboard -out":
                raise ProbeFailure(name, "provider-order", f"unexpected native provider log: {provider_log!r}")
            if contains(buffer, "osc-remote"):
                raise ProbeFailure(name, "fallback", "OSC52 text appeared without a response")
            outcome = {
                "status": "passed",
                "path": "OSC52 timeout flushed, then native provider fallback ran",
                "osc52_query_offset": query_at,
                "osc52_sentinel_offset": sentinel_at,
                "osc52_query_bytes_hex": OSC52_QUERY.hex(" "),
                "osc52_response": "not sent",
                "da1_barriers_answered": barrier_count,
                "native_provider": "xclip",
                "native_provider_arguments": provider_log,
            }

        if not child_status(pid)[0]:
            write_bytes(fd, b"\x03")
            buffer = drain(pid, fd, buffer, 0.2)
        if not child_status(pid)[0]:
            write_bytes(fd, b"\x03")
        deadline = time.monotonic() + timeout
        while not child_status(pid)[0] and time.monotonic() < deadline:
            buffer = drain(pid, fd, buffer, 0.05)
        if not child_status(pid)[0]:
            raise ProbeFailure(name, "cleanup", "Hermes did not exit after Ctrl+C")

        return {
            "id": name,
            "draft": draft,
            "ssh_marker": "SSH_TTY=/dev/pts/999",
            "input_bytes_hex": [draft.encode("utf-8").hex(" "), "16"],
            "outcome": outcome,
            "screen_tail": normalize(buffer)[-2000:],
        }
    finally:
        stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "reference": str(reference),
        "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY with raw bytes"},
        "cases": [],
        "passed": False,
    }
    try:
        report["cases"].append(run_case(reference, "osc52-response", True, args.timeout))
        report["cases"].append(run_case(reference, "osc52-timeout-native-control", False, args.timeout))
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        report["failure"] = error.as_dict() if isinstance(error, ProbeFailure) else str(error)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
