#!/usr/bin/env python3
"""Replay setup, persisted local provider/model, prompt, and streamed answer."""

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
import subprocess
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
COLUMNS = 120
ROWS = 40
ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
Predicate = Callable[[str], bool]


class ReplayFailure(RuntimeError):
    def __init__(self, step: str, message: str, output: bytes = b""):
        super().__init__(message)
        self.step = step
        self.message = message
        self.output = output

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "message": self.message,
            "screen_tail": clean_output(self.output)[-2000:],
        }


class VerticalSliceServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self):
        self.request_seen = threading.Event()
        self.first_delta_sent = threading.Event()
        self.release_response = threading.Event()
        self.response_complete = threading.Event()
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
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                chunks = [
                    b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
                    b'data: {"choices":[{"delta":{"content":"First streamed delta. "}}]}\n\n',
                ]
                for chunk in chunks:
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except OSError:
                        return
                owner.first_delta_sent.set()
                owner.release_response.wait(timeout=3.0)
                for chunk in (
                    b'data: {"choices":[{"delta":{"content":"Final streamed answer."}}]}\n\n',
                    b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
                    b"data: [DONE]\n\n",
                ):
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except OSError:
                        return
                    time.sleep(0.03)
                owner.response_complete.set()

        return Handler


def clean_output(output: bytes) -> str:
    return ANSI_ESCAPE.sub("", output.decode("utf-8", errors="replace")).replace("\r", "")


def marker_present(text: str, marker: str) -> bool:
    if marker in text:
        return True
    return "".join(marker.split()) in "".join(text.split())


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
            raise ReplayFailure(step, "Hades exited before the PTY assertion", bytes(output))
        remaining = deadline - time.monotonic()
        select.select([fd], [], [], min(0.05, max(0.0, remaining)))
    read_available(fd, output)
    raise ReplayFailure(step, f"timed out after {timeout:.1f}s", bytes(output))


def wait_for_exit(pid: int, fd: int, output: bytearray, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        read_available(fd, output)
        done, status = child_done(pid)
        if done and status is not None:
            return status
        remaining = deadline - time.monotonic()
        select.select([fd], [], [], min(0.05, max(0.0, remaining)))
    raise ReplayFailure("cleanup", f"process did not exit within {timeout:.1f}s", bytes(output))


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


def spawn_tui(binary: Path, home: Path) -> tuple[int, int, str]:
    pid, master = pty.fork()
    if pid == 0:
        try:
            set_window_size(0)
            environment = os.environ.copy()
            environment.update(
                {
                    "TERM": "xterm-256color",
                    "COLUMNS": str(COLUMNS),
                    "LINES": str(ROWS),
                    "HERMES_HOME": str(home),
                }
            )
            environment.pop("HADES_PROVIDER_BASE_URL", None)
            environment.pop("HADES_MODEL", None)
            environment.pop("HADES_PROVIDER_API_KEY", None)
            os.execve(str(binary), [str(binary)], environment)
        except BaseException as error:
            os.write(2, f"vertical-slice child failed to start: {error}\n".encode())
            os._exit(127)
    set_window_size(master)
    os.set_blocking(master, False)
    slave_path = slave_path_for_pid(pid)
    retain_slave_descriptor(slave_path)
    return pid, master, slave_path


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


def run_setup(binary: Path, home: Path, server: VerticalSliceServer) -> dict[str, Any]:
    endpoint = f"http://127.0.0.1:{server.server_port}/v1"
    environment = os.environ.copy()
    environment["HERMES_HOME"] = str(home)
    environment.pop("HADES_PROVIDER_BASE_URL", None)
    environment.pop("HADES_MODEL", None)
    environment.pop("HADES_PROVIDER_API_KEY", None)
    result = subprocess.run(
        [str(binary), "setup", "--local", endpoint, "vertical-model"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        raise ReplayFailure("setup", f"setup command failed: {output.strip()}".strip())
    for marker in ("Hades local setup complete", "Provider: loopback", "Model: vertical-model"):
        if marker not in output:
            raise ReplayFailure("setup", f"missing setup marker: {marker}")
    sidecar = home / "hades-local-provider.conf"
    if not sidecar.is_file():
        raise ReplayFailure("setup", "local provider sidecar was not created")
    contents = sidecar.read_text(encoding="utf-8")
    if "vertical-model" not in contents or "api_key" in contents:
        raise ReplayFailure("setup", "sidecar was not sanitized")
    if (home / "config.yaml").exists():
        raise ReplayFailure("setup", "setup overwrote or created Hermes config.yaml")
    return {
        "status": "passed",
        "command": "hades setup --local <loopback-url> vertical-model",
        "provider": "loopback",
        "model": "vertical-model",
        "sidecar": "~/.hermes/hades-local-provider.conf",
        "hermes_config_unchanged": True,
        "credential_persisted": False,
    }


def run_chat(binary: Path, home: Path, server: VerticalSliceServer, timeout: float) -> dict[str, Any]:
    case = "fresh-process-chat"
    pid, fd, slave_path = spawn_tui(binary, home)
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            fd,
            output,
            "startup",
            lambda text: "Hades Agent" in text and marker_present(text, "ready"),
            timeout,
        )
        startup = clean_output(bytes(output))
        if marker_present(startup, "starting agent"):
            raise ReplayFailure("startup", "persisted setup did not reach ready state", bytes(output))
        send(fd, b"vertical prompt\r")
        wait_for(pid, fd, output, "request", lambda _text: server.request_seen.is_set(), timeout)
        wait_for(
            pid,
            fd,
            output,
            "first-delta",
            lambda text: marker_present(text, "First streamed delta."),
            timeout,
        )
        if server.response_complete.is_set():
            raise ReplayFailure("first-delta", "completion arrived before first-delta readback", bytes(output))
        server.release_response.set()
        wait_for(
            pid,
            fd,
            output,
            "completion",
            lambda text: server.response_complete.is_set()
            and marker_present(text, "Final streamed answer.")
            and marker_present(text, "ready"),
            timeout,
        )
        send(fd, b"\x03")
        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
            raise ReplayFailure("cleanup", f"unexpected exit status: {status}", bytes(output))
        raw = bytes(output)
        flags = terminal_flags(slave_path)
        if b"\x1b[?1049l" not in raw or not flags["canonical"] or not flags["echo"]:
            raise ReplayFailure("cleanup", f"terminal restoration failed: {flags}", raw)
        if len(server.records) != 1:
            raise ReplayFailure("request", f"expected one request, got {len(server.records)}", raw)
        record = server.records[0]
        body = record["body"]
        if record["path"] != "/v1/chat/completions":
            raise ReplayFailure("request", f"unexpected request path: {record['path']}", raw)
        if record["content_type"] != "application/json" or record["authorization_present"]:
            raise ReplayFailure("request", "request crossed the sanitized local boundary", raw)
        if body["model"] != "vertical-model" or body["stream"] is not True:
            raise ReplayFailure("request", "persisted provider/model was not used", raw)
        if [message["role"] for message in body["messages"]] != ["system", "user"]:
            raise ReplayFailure("request", "message role boundary was not preserved", raw)
        if body["messages"][-1]["content"] != "vertical prompt":
            raise ReplayFailure("request", "prompt content was not delivered", raw)
        return {
            "status": "passed",
            "fresh_process": True,
            "startup_ready": True,
            "request": {
                "method": "POST",
                "path": record["path"],
                "content_type": record["content_type"],
                "authorization_present": False,
                "body_keys": sorted(body),
                "model": body["model"],
                "message_roles": [message["role"] for message in body["messages"]],
                "prompt_marker": "vertical prompt",
                "stream": body["stream"],
            },
            "stream": {
                "first_delta_visible_before_completion": True,
                "first_delta_marker": "First streamed delta.",
                "final_delta_marker": "Final streamed answer.",
                "ready_after_completion": True,
            },
            "cleanup": {
                "exit": {"kind": "exit", "code": 0},
                "alternate_screen_left": True,
                "terminal_restored": flags,
            },
        }
    finally:
        stop_process(pid, fd, reaped)


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
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=8.0)
    arguments = parser.parse_args()
    binary = arguments.binary.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "command": "replay-vertical-slice",
        "binary": str(binary),
        "dimensions": {"columns": COLUMNS, "rows": ROWS, "emulator": "direct PTY"},
        "steps": [],
        "passed": False,
    }
    home = Path(tempfile.mkdtemp(prefix="hades-vertical-slice-"))
    server = VerticalSliceServer()
    thread = threading.Thread(target=server.serve_forever, name="hades-vertical-slice", daemon=True)
    thread.start()
    try:
        if not binary.is_file():
            raise ReplayFailure("binary", f"binary not found: {binary}")
        report["steps"].append(run_setup(binary, home, server))
        report["steps"].append(run_chat(binary, home, server, arguments.timeout))
        report["passed"] = True
    except (OSError, ReplayFailure, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        report["failure"] = error.as_dict() if isinstance(error, ReplayFailure) else {"message": str(error)}
        return write_report(report, arguments.report.resolve() if arguments.report else None, 1)
    finally:
        server.release_response.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
        shutil.rmtree(home, ignore_errors=True)
    return write_report(report, arguments.report.resolve() if arguments.report else None, 0)


if __name__ == "__main__":
    raise SystemExit(main())
