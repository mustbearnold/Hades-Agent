#!/usr/bin/env python3
"""Replay safe Hades provider failure recovery and explicit follow-up prompts."""

from __future__ import annotations

import argparse
import errno
import json
import os
import pty
import shutil
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from probe_hermes_terminal_palette import Screen as AnsiScreen
from probe_tui_lifecycle import retain_slave_descriptor, slave_path_for_pid
from replay_vertical_slice import (
    COLUMNS,
    DEFAULT_BINARY,
    ReplayFailure,
    marker_present,
    run_setup,
    send,
    set_window_size,
    stop_process,
    terminal_flags,
    wait_for,
    wait_for_exit,
    write_report,
)


CHAT_PATH = "/v1/chat/completions"
CASES = ("http-error", "malformed-sse", "incomplete-stream")
FOLLOW_UP = "recovery follow-up"
FIRST_PROMPT = "failure probe prompt"
RECOVERED_ANSWER = "Recovered answer."
PARTIAL_ANSWER = "Partial answer before failure."
SENSITIVE_ENV_PARTS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "ACCESS_KEY")


def sse_payload(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


class RecoveryServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        self.case = ""
        self.records: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.recovered = threading.Event()
        super().__init__(("127.0.0.1", 0), self._handler())

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/v1"

    def reset(self, case: str) -> None:
        with self.lock:
            self.case = case
            self.records.clear()
        self.recovered.clear()

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(record) for record in self.records]

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                try:
                    payload = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    payload = {}
                with owner.lock:
                    owner.records.append(
                        {
                            "method": self.command,
                            "path": self.path,
                            "content_type": self.headers.get("Content-Type", ""),
                            "authorization_present": self.headers.get("Authorization") is not None,
                            "body": payload,
                        }
                    )
                    request_number = len(owner.records)
                    case = owner.case

                if self.path != CHAT_PATH:
                    self.send_error(404)
                    return

                if request_number == 1 and case == "http-error":
                    body = b'{"error":{"message":"synthetic provider failure"}}'
                    self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(body)
                    return

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()

                if request_number == 1 and case == "malformed-sse":
                    self.wfile.write(b"data: {not-json}\n\n")
                    self.wfile.flush()
                    return

                if request_number == 1 and case == "incomplete-stream":
                    for chunk in (
                        sse_payload({"choices": [{"delta": {"role": "assistant"}}]}),
                        sse_payload({"choices": [{"delta": {"content": PARTIAL_ANSWER}}]}),
                    ):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    return

                for chunk in (
                    sse_payload({"choices": [{"delta": {"role": "assistant"}}]}),
                    sse_payload({"choices": [{"delta": {"content": RECOVERED_ANSWER}}]}),
                    sse_payload({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                    b"data: [DONE]\n\n",
                ):
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except OSError:
                        return
                    time.sleep(0.02)
                owner.recovered.set()

        return Handler


def modeled_marker(output: bytearray, marker: str) -> bool:
    screen = AnsiScreen()
    screen.feed(bytes(output))
    return marker_present("\n".join(screen.lines()), marker)


def spawn_isolated(binary: Path, home: Path) -> tuple[int, int, str]:
    pid, master = pty.fork()
    if pid == 0:
        try:
            set_window_size(0)
            environment = {
                key: value
                for key, value in os.environ.items()
                if not any(part in key.upper() for part in SENSITIVE_ENV_PARTS)
            }
            environment.update(
                {
                    "TERM": "xterm-256color",
                    "COLUMNS": str(COLUMNS),
                    "LINES": "40",
                    "HERMES_HOME": str(home),
                }
            )
            for key in ("HADES_PROVIDER_BASE_URL", "HADES_MODEL", "HADES_PROVIDER_API_KEY"):
                environment.pop(key, None)
            os.execve(str(binary), [str(binary)], environment)
        except BaseException as error:
            os.write(2, f"provider recovery child failed to start: {error}\n".encode())
            os._exit(127)
    set_window_size(master)
    os.set_blocking(master, False)
    slave_path = slave_path_for_pid(pid)
    retain_slave_descriptor(slave_path)
    return pid, master, slave_path


def read_available(fd: int, output: bytearray) -> None:
    while True:
        try:
            chunk = os.read(fd, 65_536)
        except OSError as error:
            if error.errno in {errno.EIO, errno.EAGAIN}:
                return
            raise
        if not chunk:
            return
        output.extend(chunk)


def run_case(binary: Path, home: Path, server: RecoveryServer, case: str, timeout: float) -> dict[str, Any]:
    server.reset(case)
    pid, fd, slave_path = spawn_isolated(binary, home)
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            fd,
            output,
            f"{case}-startup",
            lambda text: "Hermes Agent" in text and marker_present(text, "ready"),
            timeout,
        )
        send(fd, FIRST_PROMPT.encode())
        time.sleep(0.1)
        send(fd, b"\r")
        wait_for(
            pid,
            fd,
            output,
            f"{case}-failure-request",
            lambda _text: len(server.snapshot()) >= 1,
            timeout,
        )
        wait_for(
            pid,
            fd,
            output,
            f"{case}-failure-visible",
            lambda _text: modeled_marker(output, "Provider error:"),
            timeout,
        )
        time.sleep(0.25)
        read_available(fd, output)
        if len(server.snapshot()) != 1:
            raise ReplayFailure(
                f"{case}-no-automatic-follow-up",
                f"failure caused an automatic follow-up request (count={len(server.snapshot())})",
                bytes(output),
            )
        if modeled_marker(output, "Ctrl+C to interrupt"):
            raise ReplayFailure(
                f"{case}-ready-state",
                "provider failure left the busy interrupt surface active",
                bytes(output),
            )
        partial_visible = modeled_marker(output, PARTIAL_ANSWER)
        if case == "incomplete-stream" and not partial_visible:
            raise ReplayFailure(
                f"{case}-partial-response",
                "incomplete stream discarded already-rendered assistant text",
                bytes(output),
            )

        send(fd, FOLLOW_UP.encode())
        wait_for(
            pid,
            fd,
            output,
            f"{case}-notice-cleared",
            lambda _text: modeled_marker(output, FOLLOW_UP)
            and not modeled_marker(output, "Provider error:"),
            timeout,
        )
        send(fd, b"\r")
        wait_for(
            pid,
            fd,
            output,
            f"{case}-follow-up-request",
            lambda _text: len(server.snapshot()) >= 2,
            timeout,
        )
        wait_for(
            pid,
            fd,
            output,
            f"{case}-recovered-answer",
            lambda _text: modeled_marker(output, RECOVERED_ANSWER),
            timeout,
        )
        if not server.recovered.wait(timeout):
            raise ReplayFailure(f"{case}-recovered-answer", "follow-up stream did not complete", bytes(output))
        time.sleep(0.2)
        if len(server.snapshot()) != 2:
            raise ReplayFailure(
                f"{case}-request-count",
                f"follow-up caused an unexpected request count (count={len(server.snapshot())})",
                bytes(output),
            )

        send(fd, b"\x03")
        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        raw = bytes(output)
        if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
            raise ReplayFailure(f"{case}-cleanup", f"unexpected exit status: {status}", raw)
        flags = terminal_flags(slave_path)
        if b"\x1b[?1049l" not in raw or not flags["canonical"] or not flags["echo"]:
            raise ReplayFailure(f"{case}-cleanup", f"terminal restoration failed: {flags}", raw)

        records = server.snapshot()
        if len(records) != 2:
            raise ReplayFailure(f"{case}-request-count", f"expected two requests, got {len(records)}", raw)
        prompts = [record["body"].get("messages", [])[-1].get("content") for record in records]
        for record in records:
            body = record["body"]
            if (
                record["method"] != "POST"
                or record["path"] != CHAT_PATH
                or record["content_type"] != "application/json"
                or record["authorization_present"]
                or body.get("model") != "vertical-model"
                or body.get("stream") is not True
            ):
                raise ReplayFailure(f"{case}-request-boundary", "request crossed the local sanitized boundary", raw)
        if prompts != [FIRST_PROMPT, FOLLOW_UP]:
            raise ReplayFailure(f"{case}-request-boundary", f"unexpected prompt sequence: {prompts!r}", raw)

        return {
            "id": case,
            "status": "passed",
            "failure": {
                "provider_error_visible": True,
                "ready_after_failure": True,
                "automatic_follow_up_requests": 0,
                "partial_response_preserved": partial_visible,
            },
            "follow_up": {
                "prompt": FOLLOW_UP,
                "notice_cleared_on_edit": True,
                "recovered_answer": RECOVERED_ANSWER,
                "request_count": 2,
            },
            "requests": [
                {
                    "method": record["method"],
                    "path": record["path"],
                    "content_type": record["content_type"],
                    "authorization_present": record["authorization_present"],
                    "model": record["body"].get("model"),
                    "message_roles": [
                        message.get("role") for message in record["body"].get("messages", [])
                    ],
                    "prompt": prompt,
                    "stream": record["body"].get("stream"),
                }
                for record, prompt in zip(records, prompts, strict=True)
            ],
            "cleanup": {
                "exit": {"kind": "exit", "code": 0},
                "alternate_screen_left": True,
                "terminal_restored": flags,
            },
        }
    finally:
        stop_process(pid, fd, reaped)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=8.0)
    arguments = parser.parse_args()
    binary = arguments.binary.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "command": "replay-provider-recovery",
        "binary": str(binary),
        "dimensions": {"columns": COLUMNS, "rows": 40, "emulator": "direct PTY"},
        "steps": [],
        "passed": False,
    }
    home = Path(tempfile.mkdtemp(prefix="hades-provider-recovery-"))
    server = RecoveryServer()
    thread = threading.Thread(target=server.serve_forever, name="hades-provider-recovery", daemon=True)
    thread.start()
    try:
        if not binary.is_file():
            raise ReplayFailure("binary", f"binary not found: {binary}")
        report["steps"].append(run_setup(binary, home, server))
        for case in CASES:
            report["steps"].append(run_case(binary, home, server, case, arguments.timeout))
        if (home / "config.yaml").exists():
            raise ReplayFailure("config-boundary", "Hermes config.yaml was created or changed")
        report["boundaries"] = {
            "automatic_retries": False,
            "follow_up_is_user_submitted": True,
            "provider": "loopback",
            "credentials": "none",
            "hermes_config_mutation": False,
        }
        report["passed"] = True
    except (OSError, ReplayFailure, ValueError, KeyError, TypeError) as error:
        report["failure"] = error.as_dict() if isinstance(error, ReplayFailure) else {"message": str(error)}
        return write_report(report, arguments.report.resolve() if arguments.report else None, 1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
        shutil.rmtree(home, ignore_errors=True)
    return write_report(report, arguments.report.resolve() if arguments.report else None, 0)


if __name__ == "__main__":
    raise SystemExit(main())
