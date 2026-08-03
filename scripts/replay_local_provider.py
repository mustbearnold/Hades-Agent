#!/usr/bin/env python3
"""Replay the opt-in Hades loopback provider worker through a real PTY."""

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
import tempfile
import termios
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from probe_tui_lifecycle import retain_slave_descriptor, slave_path_for_pid


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BINARY = ROOT / "target/debug/hades"
DEFAULT_CONTRACT = ROOT / "tests/fixtures/parity/OBS-0051-hades-local-provider-stream.json"
COLUMNS = 120
ROWS = 40
ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
Predicate = Callable[[str], bool]


class ReplayFailure(RuntimeError):
    """Raised when a bounded local-provider replay assertion fails."""

    def __init__(self, case: str, step: str, message: str, output: bytes = b""):
        super().__init__(message)
        self.case = case
        self.step = step
        self.message = message
        self.output = output

    def as_dict(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "step": self.step,
            "message": self.message,
            "screen_tail": clean_output(self.output)[-2000:],
        }


class LocalProviderServer(ThreadingHTTPServer):
    """Small deterministic OpenAI-compatible response fixture."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, block_response: bool):
        self.block_response = block_response
        self.request_seen = threading.Event()
        self.release_response = threading.Event()
        self.records: list[dict[str, Any]] = []
        super().__init__(("127.0.0.1", 0), self._handler())

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                owner.records.append(
                    {
                        "path": self.path,
                        "content_type": self.headers.get("Content-Type", ""),
                        "authorization_present": self.headers.get("Authorization") is not None,
                        "body": json.loads(body.decode("utf-8")),
                    }
                )
                owner.request_seen.set()
                if owner.block_response:
                    owner.release_response.wait(timeout=3.0)
                    return

                chunks = [
                    b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
                    b'data: {"choices":[{"delta":{"content":"Synthetic loopback response."}}]}\n\n',
                    b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
                    b"data: [DONE]\n\n",
                ]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                for chunk in chunks:
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except OSError:
                        return
                    time.sleep(0.02)

        return Handler


def clean_output(output: bytes) -> str:
    return ANSI_ESCAPE.sub("", output.decode("utf-8", errors="replace")).replace("\r", "")


def marker_present(text: str, marker: str) -> bool:
    if marker in text:
        return True
    compact_text = "".join(text.split())
    compact_marker = "".join(marker.split())
    return compact_marker in compact_text


def set_window_size(fd: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLUMNS, 0, 0))


def read_available(fd: int, output: bytearray) -> None:
    while True:
        try:
            chunk = os.read(fd, 65_536)
        except OSError as error:
            if error.errno in {errno.EAGAIN, errno.EIO}:
                return
            raise
        if not chunk:
            return
        output.extend(chunk)


def child_done(pid: int) -> tuple[bool, int | None]:
    waited, status = os.waitpid(pid, os.WNOHANG)
    return waited != 0, status if waited else None


def wait_for(
    pid: int,
    fd: int,
    output: bytearray,
    case: str,
    step: str,
    predicate: Predicate,
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        read_available(fd, output)
        if predicate(clean_output(bytes(output))):
            return
        done, _ = child_done(pid)
        if done:
            read_available(fd, output)
            raise ReplayFailure(case, step, "Hades exited before the PTY assertion", bytes(output))
        remaining = deadline - time.monotonic()
        select.select([fd], [], [], min(0.05, max(0.0, remaining)))
    read_available(fd, output)
    raise ReplayFailure(case, step, f"timed out after {timeout:.1f}s", bytes(output))


def wait_for_exit(pid: int, fd: int, output: bytearray, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        read_available(fd, output)
        done, status = child_done(pid)
        if done and status is not None:
            return status
        remaining = deadline - time.monotonic()
        select.select([fd], [], [], min(0.05, max(0.0, remaining)))
    raise ReplayFailure("cleanup", "exit", f"process did not exit within {timeout:.1f}s", bytes(output))


def send(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def terminal_flags(slave_path: str) -> dict[str, bool]:
    local_flags = termios.tcgetattr(retain_slave_descriptor(slave_path))[3]
    return {
        "canonical": bool(local_flags & termios.ICANON),
        "echo": bool(local_flags & termios.ECHO),
    }


def spawn(binary: Path, base_url: str | None) -> tuple[int, int, str, Path]:
    home = Path(tempfile.mkdtemp(prefix="hades-local-provider-"))
    pid, master = pty.fork()
    if pid == 0:
        environment = os.environ.copy()
        environment.update(
            {
                "TERM": "xterm-256color",
                "COLUMNS": str(COLUMNS),
                "LINES": str(ROWS),
                "HOME": str(home),
                "HERMES_HOME": str(home),
            }
        )
        environment.pop("HADES_PROVIDER_API_KEY", None)
        if base_url is None:
            environment.pop("HADES_PROVIDER_BASE_URL", None)
        else:
            environment["HADES_PROVIDER_BASE_URL"] = base_url
        environment["HADES_MODEL"] = "palette-model"
        os.execve(str(binary), [str(binary)], environment)
    set_window_size(master)
    os.set_blocking(master, False)
    slave_path = slave_path_for_pid(pid)
    retain_slave_descriptor(slave_path)
    return pid, master, slave_path, home


def stop_process(pid: int, fd: int, reaped: bool) -> None:
    if not reaped:
        try:
            os.kill(pid, signal.SIGKILL)
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


def start_server(block_response: bool) -> tuple[LocalProviderServer, threading.Thread]:
    server = LocalProviderServer(block_response)
    thread = threading.Thread(target=server.serve_forever, name="hades-local-provider", daemon=True)
    thread.start()
    return server, thread


def finish_server(server: LocalProviderServer, thread: threading.Thread) -> None:
    server.release_response.set()
    server.shutdown()
    server.server_close()
    thread.join(timeout=2.0)


def assert_clean_exit(status: int, case: str) -> None:
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        raise ReplayFailure(case, "cleanup", f"unexpected exit status: {status}")


def run_stream_case(binary: Path, timeout: float) -> dict[str, Any]:
    case = "local-provider-stream"
    server, server_thread = start_server(block_response=False)
    pid, fd, slave_path, home = spawn(binary, f"http://127.0.0.1:{server.server_port}/v1")
    output = bytearray()
    reaped = False
    try:
        wait_for(pid, fd, output, case, "startup", lambda text: "Hades Agent" in text and "ready" in text, timeout)
        send(fd, b"sanitized prompt\r")
        wait_for(pid, fd, output, case, "request", lambda _text: server.request_seen.is_set(), timeout)
        wait_for(
            pid,
            fd,
            output,
            case,
            "response",
            lambda text: marker_present(text, "Synthetic loopback response.") and marker_present(text, "ready"),
            timeout,
        )
        send(fd, b"\x03")
        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        assert_clean_exit(status, case)
        raw = bytes(output)
        if b"\x1b[?1049l" not in raw:
            raise ReplayFailure(case, "cleanup", "alternate screen was not restored", raw)
        flags = terminal_flags(slave_path)
        if not flags["canonical"] or not flags["echo"]:
            raise ReplayFailure(case, "cleanup", f"terminal flags were not restored: {flags}", raw)
        if len(server.records) != 1:
            raise ReplayFailure(case, "request", f"expected one request, got {len(server.records)}", raw)
        record = server.records[0]
        body = record["body"]
        if record["path"] != "/v1/chat/completions":
            raise ReplayFailure(case, "request", f"unexpected request path: {record['path']}", raw)
        if record["content_type"] != "application/json" or record["authorization_present"]:
            raise ReplayFailure(case, "request", "request headers crossed the local sanitized boundary", raw)
        if sorted(body) != ["max_tokens", "messages", "model", "stream", "stream_options", "tools"]:
            raise ReplayFailure(case, "request", f"unexpected body keys: {sorted(body)}", raw)
        if body["model"] != "palette-model" or body["stream"] is not True:
            raise ReplayFailure(case, "request", "model/stream markers were not preserved", raw)
        if [message["role"] for message in body["messages"]] != ["system", "user"]:
            raise ReplayFailure(case, "request", "message role boundary was not preserved", raw)
        return {
            "id": case,
            "status": "passed",
            "request": {
                "method": "POST",
                "path": record["path"],
                "content_type": record["content_type"],
                "authorization_present": False,
                "body_keys": sorted(body),
                "model": body["model"],
                "stream": body["stream"],
                "message_roles": [message["role"] for message in body["messages"]],
                "tools_present": bool(body["tools"]),
            },
            "response": {
                "content_type": "text/event-stream",
                "chunk_count": 3,
                "done_marker_sent": True,
                "assistant_text_marker": "Synthetic loopback response.",
            },
            "visible_state": {
                "returned_to_ready": True,
                "assistant_text_rendered": True,
                "cleanup": "Ctrl+C exited cleanly",
            },
        }
    finally:
        stop_process(pid, fd, reaped)
        finish_server(server, server_thread)
        shutil.rmtree(home, ignore_errors=True)


def run_missing_config_case(binary: Path, timeout: float) -> dict[str, Any]:
    case = "missing-provider-config"
    pid, fd, slave_path, home = spawn(binary, None)
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            fd,
            output,
            case,
            "startup",
            lambda text: "Hades Agent" in text and marker_present(text, "starting agent"),
            timeout,
        )
        send(fd, b"missing endpoint\r")
        wait_for(
            pid,
            fd,
            output,
            case,
            "draft",
            lambda text: marker_present(text, "missing endpoint"),
            timeout,
        )
        visible_text = clean_output(bytes(output))
        if marker_present(visible_text, "Provider error"):
            raise ReplayFailure(case, "input", "unconfigured startup rendered a provider error", bytes(output))
        prompt_visible = marker_present(visible_text, "missing endpoint")
        send(fd, b"\x03")
        time.sleep(0.05)
        send(fd, b"\x03")
        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        assert_clean_exit(status, case)
        return {
            "id": case,
            "status": "passed",
            "visible_state": {
                "unconfigured_startup": True,
                "prompt_visible": prompt_visible,
                "prompt_ignored": False,
                "provider_request_started": False,
                "cleanup": "two Ctrl+C presses exited cleanly",
            },
        }
    finally:
        stop_process(pid, fd, reaped)
        shutil.rmtree(home, ignore_errors=True)


def run_interrupt_case(binary: Path, timeout: float) -> dict[str, Any]:
    case = "interrupt-active-provider"
    server, server_thread = start_server(block_response=True)
    pid, fd, _slave_path, home = spawn(binary, f"http://127.0.0.1:{server.server_port}/v1")
    output = bytearray()
    reaped = False
    try:
        wait_for(pid, fd, output, case, "startup", lambda text: "Hades Agent" in text and "ready" in text, timeout)
        send(fd, b"interrupt me\r")
        wait_for(pid, fd, output, case, "request", lambda _text: server.request_seen.is_set(), timeout)
        send(fd, b"\x03")
        wait_for(pid, fd, output, case, "interrupt", lambda text: "interrupted" in text, timeout)
        send(fd, b"\x03")
        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        assert_clean_exit(status, case)
        return {
            "id": case,
            "status": "passed",
            "visible_state": {
                "request_started": True,
                "interrupt_marker": True,
                "late_response_released": False,
                "cleanup": "Ctrl+C interrupted and then exited cleanly",
            },
        }
    finally:
        stop_process(pid, fd, reaped)
        finish_server(server, server_thread)
        shutil.rmtree(home, ignore_errors=True)


def write_report(report: dict[str, Any], path: Path | None, status: int) -> int:
    text = json.dumps(report, indent=2, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=8.0)
    arguments = parser.parse_args()
    binary = arguments.binary.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "command": "replay-local-provider",
        "binary": str(binary),
        "contract": str(arguments.contract.resolve()),
        "dimensions": {"columns": COLUMNS, "rows": ROWS, "emulator": "direct PTY"},
        "cases": [],
        "passed": False,
    }
    try:
        if not binary.is_file():
            raise ReplayFailure("report", "binary", f"binary not found: {binary}")
        report["cases"] = [
            run_stream_case(binary, arguments.timeout),
            run_missing_config_case(binary, arguments.timeout),
            run_interrupt_case(binary, arguments.timeout),
        ]
        report["passed"] = True
    except (OSError, ReplayFailure, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        report["failure"] = error.as_dict() if isinstance(error, ReplayFailure) else {"message": str(error)}
        return write_report(report, arguments.report.resolve() if arguments.report else None, 1)
    return write_report(report, arguments.report.resolve() if arguments.report else None, 0)


if __name__ == "__main__":
    raise SystemExit(main())
