#!/usr/bin/env python3
"""Probe Hermes Ctrl+V text handling with a synthetic xclip provider."""

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
from typing import Any


DEFAULT_REFERENCE = Path("/tmp/hades-hermes-ref-X3bLd0")
COLUMNS = 120
ROWS = 40
SENSITIVE_ENV_PARTS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "ACCESS_KEY")
ANSI_SEQUENCE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[()][0-2A-Z])")


def normalize(raw: bytes) -> str:
    return ANSI_SEQUENCE.sub("", raw.decode("utf-8", errors="replace").replace("\r", ""))


def contains(raw: bytes, marker: str) -> bool:
    text = normalize(raw)
    return marker in text or "".join(marker.split()).lower() in "".join(text.split()).lower()


def child_exited(pid: int) -> bool:
    try:
        return os.waitpid(pid, os.WNOHANG)[0] != 0
    except ChildProcessError:
        return True


def drain(fd: int, buffer: bytes, duration: float = 0.1) -> bytes:
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        readable, _, _ = select.select([fd], [], [], 0.02)
        if readable:
            try:
                chunk = os.read(fd, 65_536)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            buffer += chunk
    return buffer


def wait_for(pid: int, fd: int, buffer: bytes, markers: list[str], timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(contains(buffer, marker) for marker in markers):
            return buffer
        if child_exited(pid):
            buffer = drain(fd, buffer)
            raise RuntimeError(f"Hermes exited before markers {markers!r}: {normalize(buffer)[-1600:]}")
        readable, _, _ = select.select([fd], [], [], 0.05)
        if readable:
            buffer = drain(fd, buffer, 0.02)
    raise RuntimeError(f"timed out waiting for {markers!r}: {normalize(buffer)[-1600:]}")


def spawn(reference: Path, home: Path, fake_bin: Path, payload: str, log: Path) -> tuple[int, int]:
    pid, fd = pty.fork()
    if pid == 0:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not any(part in key.upper() for part in SENSITIVE_ENV_PARTS)
        }
        environment.update(
            {
                "TERM": "xterm-256color",
                "HERMES_HOME": str(home),
                "HOME": str(home),
                "PATH": f"{fake_bin}:{environment.get('PATH', '')}",
                "HERMES_CLIPBOARD_PAYLOAD": payload,
                "HERMES_CLIPBOARD_LOG": str(log),
                "UV_NO_CONFIG": "1",
            }
        )
        os.chdir(reference)
        os.execvpe("uv", ["uv", "run", "hermes", "--tui"], environment)

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLUMNS, 0, 0))
    os.set_blocking(fd, False)
    return pid, fd


def stop(pid: int, fd: int) -> None:
    if not child_exited(pid):
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


def run_case(reference: Path, name: str, payload: str, draft: str, timeout: float) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix=f"had022-{name}-"))
    fake_bin = root / "bin"
    fake_bin.mkdir()
    log = root / "xclip.log"
    fake_xclip = fake_bin / "xclip"
    fake_xclip.write_text(
        "#!/bin/sh\nprintf '%s' \"$HERMES_CLIPBOARD_PAYLOAD\"\nprintf '%s\\n' \"$*\" >> \"$HERMES_CLIPBOARD_LOG\"\n",
        encoding="utf-8",
    )
    fake_xclip.chmod(0o755)
    home = root / "home"
    home.mkdir()
    pid, fd = spawn(reference, home, fake_bin, payload, log)
    buffer = b""
    try:
        buffer = wait_for(pid, fd, buffer, ["Hermes Agent", "Available Tools"], timeout)
        os.write(fd, draft.encode())
        buffer = wait_for(pid, fd, buffer, [draft], timeout)
        os.write(fd, b"\x16")
        if payload:
            buffer = wait_for(pid, fd, buffer, ["clip-one", "clip-two"], timeout)
            if contains(buffer, "interrupt"):
                raise RuntimeError(f"successful text paste entered busy state: {normalize(buffer)[-1600:]}")
            status = "passed"
            observation = "text inserted with internal newline and trailing newlines removed"
        else:
            buffer = drain(fd, buffer, min(timeout, 1.5))
            if not contains(buffer, draft) or contains(buffer, "interrupt"):
                raise RuntimeError(f"empty provider changed submission state: {normalize(buffer)[-1600:]}")
            status = "environment-sensitive"
            observation = "xclip returned empty; image-fallback response was not observable without a gateway response"
        provider_log = log.read_text(encoding="utf-8") if log.exists() else ""
        if "-selection clipboard -out" not in provider_log:
            raise RuntimeError(f"xclip provider was not called as expected: {provider_log!r}")
        if not child_exited(pid):
            os.write(fd, b"\x03")
            buffer = drain(fd, buffer, 0.2)
        if not child_exited(pid):
            os.write(fd, b"\x03")
        deadline = time.monotonic() + timeout
        while not child_exited(pid) and time.monotonic() < deadline:
            buffer = drain(fd, buffer, 0.05)
        if not child_exited(pid):
            raise RuntimeError("Hermes did not exit after Ctrl+C")
        return {
            "id": name,
            "payload": payload,
            "draft": draft,
            "provider": "synthetic xclip",
            "provider_log": provider_log.strip(),
            "screen_tail": normalize(buffer)[-1600:],
            "status": status,
            "observation": observation,
        }
    finally:
        stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    report: dict[str, Any] = {
        "schema_version": 1,
        "reference": str(args.reference.resolve()),
        "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY with raw bytes"},
        "cases": [],
    }
    try:
        report["cases"].append(
            run_case(args.reference.resolve(), "successful-text", "clip-one  \nclip-two\n\n", "seed:", args.timeout)
        )
        report["cases"].append(run_case(args.reference.resolve(), "empty-provider", "", "empty-seed", args.timeout))
        report["passed"] = True
    except (OSError, RuntimeError, ValueError) as error:
        report["passed"] = False
        report["failure"] = str(error)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
