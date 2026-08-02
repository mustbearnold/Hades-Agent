#!/usr/bin/env python3
"""Replay successful Hades conversation context and failed-turn isolation."""

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
    clean_output,
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
SYSTEM_PROMPT = "You are Hades Agent. Respond concisely to the user."
FIRST_PROMPT = "first context prompt"
FIRST_ANSWER = "First context answer."
SECOND_PROMPT = "second context prompt"
SECOND_ANSWER = "Second context answer."
FAILED_PROMPT = "failed context prompt"
PARTIAL_ANSWER = "Failed partial diagnostic."
FOLLOW_UP = "recovered context prompt"
RECOVERED_ANSWER = "Recovered context answer."
SENSITIVE_ENV_PARTS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "ACCESS_KEY")


def sse_payload(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


class ContextServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.completed_count = 0
        self.lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), self._handler())

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(record) for record in self.records]

    def completion_count(self) -> int:
        with self.lock:
            return self.completed_count

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

                if self.path != CHAT_PATH:
                    self.send_error(404)
                    return

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()

                if request_number == 3:
                    chunks = (
                        sse_payload({"choices": [{"delta": {"role": "assistant"}}]}),
                        sse_payload({"choices": [{"delta": {"content": PARTIAL_ANSWER}}]}),
                    )
                    for chunk in chunks:
                        try:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        except OSError:
                            return
                    return

                answer = {
                    1: FIRST_ANSWER,
                    2: SECOND_ANSWER,
                    4: RECOVERED_ANSWER,
                }.get(request_number)
                if answer is None:
                    self.send_error(500)
                    return
                for chunk in (
                    sse_payload({"choices": [{"delta": {"role": "assistant"}}]}),
                    sse_payload({"choices": [{"delta": {"content": answer}}]}),
                    sse_payload({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                    b"data: [DONE]\n\n",
                ):
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except OSError:
                        return
                    time.sleep(0.02)
                with owner.lock:
                    owner.completed_count += 1

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
            os.write(2, f"conversation context child failed to start: {error}\n".encode())
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


def messages(record: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        (message.get("role", ""), message.get("content", ""))
        for message in record["body"].get("messages", [])
    ]


def run_chat(binary: Path, home: Path, server: ContextServer, timeout: float) -> dict[str, Any]:
    pid, fd, slave_path = spawn_isolated(binary, home)
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            fd,
            output,
            "startup",
            lambda text: "Hermes Agent" in text and marker_present(text, "ready"),
            timeout,
        )

        send(fd, FIRST_PROMPT.encode() + b"\r")
        wait_for(pid, fd, output, "first-request", lambda _text: len(server.snapshot()) >= 1, timeout)
        wait_for(
            pid,
            fd,
            output,
            "first-completion",
            lambda _text: server.completion_count() >= 1
            and modeled_marker(output, FIRST_ANSWER)
            and modeled_marker(output, "ready"),
            timeout,
        )

        send(fd, SECOND_PROMPT.encode() + b"\r")
        wait_for(pid, fd, output, "second-request", lambda _text: len(server.snapshot()) >= 2, timeout)
        wait_for(
            pid,
            fd,
            output,
            "second-completion",
            lambda _text: server.completion_count() >= 2 and modeled_marker(output, SECOND_ANSWER),
            timeout,
        )

        send(fd, FAILED_PROMPT.encode() + b"\r")
        wait_for(pid, fd, output, "failed-request", lambda _text: len(server.snapshot()) >= 3, timeout)
        wait_for(
            pid,
            fd,
            output,
            "failed-partial",
            lambda _text: modeled_marker(output, PARTIAL_ANSWER),
            timeout,
        )
        wait_for(
            pid,
            fd,
            output,
            "failed-visible",
            lambda _text: modeled_marker(output, "Provider error:"),
            timeout,
        )
        time.sleep(0.2)
        read_available(fd, output)
        if len(server.snapshot()) != 3:
            raise ReplayFailure(
                "failed-no-automatic-follow-up",
                f"incomplete turn caused an automatic request (count={len(server.snapshot())})",
                bytes(output),
            )

        send(fd, FOLLOW_UP.encode())
        wait_for(
            pid,
            fd,
            output,
            "follow-up-edit",
            lambda _text: modeled_marker(output, FOLLOW_UP)
            and not modeled_marker(output, "Provider error:"),
            timeout,
        )
        send(fd, b"\r")
        wait_for(pid, fd, output, "follow-up-request", lambda _text: len(server.snapshot()) >= 4, timeout)
        wait_for(
            pid,
            fd,
            output,
            "follow-up-completion",
            lambda _text: server.completion_count() >= 3 and modeled_marker(output, RECOVERED_ANSWER),
            timeout,
        )

        send(fd, b"\x03")
        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        raw = bytes(output)
        if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
            raise ReplayFailure("cleanup", f"unexpected exit status: {status}", raw)
        flags = terminal_flags(slave_path)
        if b"\x1b[?1049l" not in raw or not flags["canonical"] or not flags["echo"]:
            raise ReplayFailure("cleanup", f"terminal restoration failed: {flags}", raw)

        records = server.snapshot()
        if len(records) != 4:
            raise ReplayFailure("request-count", f"expected four requests, got {len(records)}", raw)
        expected = [
            [("system", SYSTEM_PROMPT), ("user", FIRST_PROMPT)],
            [
                ("system", SYSTEM_PROMPT),
                ("user", FIRST_PROMPT),
                ("assistant", FIRST_ANSWER),
                ("user", SECOND_PROMPT),
            ],
            [
                ("system", SYSTEM_PROMPT),
                ("user", FIRST_PROMPT),
                ("assistant", FIRST_ANSWER),
                ("user", SECOND_PROMPT),
                ("assistant", SECOND_ANSWER),
                ("user", FAILED_PROMPT),
            ],
            [
                ("system", SYSTEM_PROMPT),
                ("user", FIRST_PROMPT),
                ("assistant", FIRST_ANSWER),
                ("user", SECOND_PROMPT),
                ("assistant", SECOND_ANSWER),
                ("user", FOLLOW_UP),
            ],
        ]
        actual = [messages(record) for record in records]
        if actual != expected:
            raise ReplayFailure("request-context", f"unexpected conversation context: {actual!r}", raw)
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
                raise ReplayFailure("request-boundary", "request crossed the local sanitized boundary", raw)

        return {
            "status": "passed",
            "successful_turns_preserved": True,
            "failed_partial_turn_visible": True,
            "failed_turn_excluded_from_follow_up": True,
            "automatic_requests": 0,
            "requests": [
                {
                    "method": record["method"],
                    "path": record["path"],
                    "content_type": record["content_type"],
                    "authorization_present": record["authorization_present"],
                    "model": record["body"].get("model"),
                    "messages": messages(record),
                    "stream": record["body"].get("stream"),
                }
                for record in records
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
        "command": "replay-conversation-context",
        "binary": str(binary),
        "dimensions": {"columns": COLUMNS, "rows": 40, "emulator": "direct PTY"},
        "steps": [],
        "passed": False,
    }
    home = Path(tempfile.mkdtemp(prefix="hades-conversation-context-"))
    server = ContextServer()
    thread = threading.Thread(target=server.serve_forever, name="hades-conversation-context", daemon=True)
    thread.start()
    try:
        if not binary.is_file():
            raise ReplayFailure("binary", f"binary not found: {binary}")
        report["steps"].append(run_setup(binary, home, server))
        report["steps"].append(run_chat(binary, home, server, arguments.timeout))
        if (home / "config.yaml").exists():
            raise ReplayFailure("config-boundary", "Hermes config.yaml was created or changed")
        report["boundaries"] = {
            "provider": "loopback",
            "credentials": "none",
            "hermes_config_mutation": False,
            "successful_context": "completed turns only",
            "failed_context": "diagnostic display only",
        }
        report["passed"] = True
    except (OSError, ReplayFailure, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
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
