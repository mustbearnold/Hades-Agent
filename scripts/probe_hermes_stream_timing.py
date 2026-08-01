#!/usr/bin/env python3
"""Capture Hermes delayed provider deltas and pre-completion cancellation."""

from __future__ import annotations

import argparse
import json
import os
import pty
import re
import shutil
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from probe_hermes_slash_commands import (
    DEFAULT_REFERENCE,
    ProbeFailure,
    clean_exit,
    contains_marker,
    normalized,
    stop,
    wait_for,
    write_bytes,
)
from probe_hermes_terminal_palette import COLUMNS, ROWS, SOURCE_COMMIT, drain, set_window_size


CHAT_PATH = "/v1/chat/completions"
FIRST_DELTA = "HERMES_DELAY_FIRST"
SECOND_DELTA = "HERMES_DELAY_SECOND"
SENSITIVE = re.compile(r"(?:/tmp|/home)/[^\s\r\n]+|synthetic-probe-key", re.IGNORECASE)


def sse_payload(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


class TimingRecorder:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: list[dict[str, Any]] = []
        self.writes: list[dict[str, Any]] = []
        self.first_sent = threading.Event()
        self.release_second = threading.Event()
        self.handler_done = threading.Event()

    def record_request(self, handler: BaseHTTPRequestHandler, body: bytes) -> int:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        messages = payload.get("messages", []) if isinstance(payload, dict) else []
        roles = [message.get("role") for message in messages if isinstance(message, dict)]
        with self.lock:
            self.requests.append(
                {
                    "method": handler.command,
                    "path": handler.path,
                    "content_type": handler.headers.get("Content-Type", ""),
                    "authorization_present": "authorization" in {key.lower() for key in handler.headers},
                    "body_keys": sorted(payload) if isinstance(payload, dict) else [],
                    "model": payload.get("model") if isinstance(payload, dict) else None,
                    "stream": payload.get("stream") if isinstance(payload, dict) else None,
                    "message_roles": roles,
                    "tools_present": bool(payload.get("tools")) if isinstance(payload, dict) else False,
                }
            )
            return len(self.requests) - 1

    def record_write(self, request_index: int, index: int, payload: str, sent: bool, error: str | None = None) -> None:
        with self.lock:
            self.writes.append(
                {
                    "request_index": request_index,
                    "index": index,
                    "marker": payload,
                    "sent": sent,
                    "error": error,
                    "elapsed_ms": None,
                }
            )

    def add_elapsed(self, request_index: int, index: int, elapsed_ms: float) -> None:
        with self.lock:
            for write in self.writes:
                if write["request_index"] == request_index and write["index"] == index:
                    write["elapsed_ms"] = round(elapsed_ms, 1)
                    return

    def snapshot(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with self.lock:
            return list(self.requests), [dict(write) for write in self.writes]

    def request_wait(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if self.requests:
                    return True
            time.sleep(0.02)
        return False


class TimingServer:
    def __init__(self) -> None:
        self.recorder = TimingRecorder()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), TimingHandler)
        self.httpd.recorder = self.recorder
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def start(self) -> None:
        self.thread.start()

    def wait_for_request(self, timeout: float) -> bool:
        return self.recorder.request_wait(timeout)

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


class TimingHandler(BaseHTTPRequestHandler):
    server: ThreadingHTTPServer

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        recorder: TimingRecorder = self.server.recorder
        request_index = recorder.record_request(self, body)
        if self.path == "/api/show":
            encoded = json.dumps(
                {
                    "modelfile": "FROM palette-model",
                    "parameters": "",
                    "template": "",
                    "details": {"family": "synthetic", "families": ["synthetic"]},
                },
                separators=(",", ":"),
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            recorder.handler_done.set()
            return
        if self.path != CHAT_PATH:
            self.send_error(404)
            recorder.handler_done.set()
            return

        chunks = [
            (0, "role", {"id": "delay", "object": "chat.completion.chunk", "model": "palette-model", "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}),
            (1, FIRST_DELTA, {"id": "delay", "object": "chat.completion.chunk", "model": "palette-model", "choices": [{"index": 0, "delta": {"content": FIRST_DELTA}, "finish_reason": None}]}),
            (2, SECOND_DELTA, {"id": "delay", "object": "chat.completion.chunk", "model": "palette-model", "choices": [{"index": 0, "delta": {"content": SECOND_DELTA}, "finish_reason": None}]}),
            (3, "finish", {"id": "delay", "object": "chat.completion.chunk", "model": "palette-model", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        started = time.monotonic()
        try:
            for index, marker, chunk in chunks:
                if index == 2:
                    recorder.release_second.wait(timeout=8)
                self.wfile.write(sse_payload(chunk))
                self.wfile.flush()
                recorder.record_write(request_index, index, marker, True)
                recorder.add_elapsed(request_index, index, (time.monotonic() - started) * 1000)
                if index == 1:
                    recorder.first_sent.set()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            recorder.record_write(request_index, 4, "DONE", True)
            recorder.add_elapsed(request_index, 4, (time.monotonic() - started) * 1000)
        except (BrokenPipeError, ConnectionResetError, OSError) as error:
            recorder.record_write(request_index, 99, "connection-closed", False, type(error).__name__)
        finally:
            recorder.handler_done.set()


def safe_environment(reference: Path, home: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(part in key.upper() for part in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "ACCESS_KEY"))
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
            "UV_NO_CONFIG": "1",
        }
    )
    for key in ("TMUX", "STY", "WAYLAND_DISPLAY", "WSL_INTEROP", "WSL_DISTRO_NAME"):
        environment.pop(key, None)
    return environment


def write_ready_config(home: Path, base_url: str) -> None:
    (home / "config.yaml").write_text(
        "model:\n"
        "  provider: custom\n"
        "  default: palette-model\n"
        f"  base_url: {base_url}\n"
        "  api_key: synthetic-probe-key\n"
        "custom_providers:\n"
        "  - name: palette-loopback\n"
        f"    base_url: {base_url}\n"
        "    api_key: synthetic-probe-key\n"
        "    model: palette-model\n",
        encoding="utf-8",
    )


def start_ready(reference: Path, home: Path, base_url: str, case: str, timeout: float) -> tuple[int, int, bytes]:
    write_ready_config(home, base_url)
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(reference)
        os.execvpe("uv", ["uv", "run", "hermes", "--tui"], safe_environment(reference, home))
    set_window_size(fd, COLUMNS, ROWS)
    os.set_blocking(fd, False)
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


def observe_marker(pid: int, fd: int, buffer: bytes, marker: str, timeout: float, offset: int) -> tuple[bytes, float | None]:
    started = time.monotonic()
    deadline = started + timeout
    while time.monotonic() < deadline:
        if contains_marker(buffer[offset:], marker):
            return buffer, round((time.monotonic() - started) * 1000, 1)
        buffer = drain(pid, fd, buffer, min(0.03, max(0.0, deadline - time.monotonic())))
        if contains_marker(buffer[offset:], marker):
            return buffer, round((time.monotonic() - started) * 1000, 1)
    return buffer, None


def response_prefix(buffer: bytes, offset: int) -> str:
    return SENSITIVE.sub("<redacted>", normalized(buffer[offset:])[-2400:])


def run_case(reference: Path, timeout: float, interrupt: bool) -> dict[str, Any]:
    case = "interrupt-before-completion" if interrupt else "delayed-delta-order"
    root = Path(tempfile.mkdtemp(prefix=f"hades-hermes-stream-{case}-"))
    home = root / "home"
    home.mkdir()
    server = TimingServer()
    pid = fd = -1
    buffer = b""
    try:
        server.start()
        pid, fd, buffer = start_ready(reference, home, server.base_url, case, timeout)
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "composer-ready",
            lambda current: re.search(r"(?m)ready\s*│", normalized(current)[-1200:], re.IGNORECASE) is not None,
            timeout,
        )
        write_bytes(fd, b"stream timing probe")
        buffer = wait_for(pid, fd, buffer, case, "prompt-echo", lambda current: contains_marker(current, "stream timing probe"), timeout)
        write_bytes(fd, b"\r")
        chat_offset = len(buffer)
        if not server.wait_for_request(timeout):
            raise ProbeFailure(case, "request", "timed out waiting for provider request", {"screen_tail": response_prefix(buffer, chat_offset)})
        if not server.recorder.first_sent.wait(timeout):
            raise ProbeFailure(case, "first-write", "timed out waiting for first delayed delta", {"screen_tail": response_prefix(buffer, chat_offset)})
        first_sent_at = time.monotonic()
        buffer, first_visible_ms = observe_marker(pid, fd, buffer, FIRST_DELTA, 2.0, chat_offset)

        if interrupt:
            write_bytes(fd, b"\x03")
            time.sleep(0.25)
            server.recorder.release_second.set()
            buffer = drain(pid, fd, buffer, 0.7)
            interrupted_tail = response_prefix(buffer, chat_offset)
            buffer, exited = clean_exit(pid, fd, buffer, case, timeout)
            requests, writes = server.recorder.snapshot()
            return {
                "id": case,
                "status": "passed",
                "input": [
                    {"kind": "text", "value": "<sanitized prompt>"},
                    {"kind": "key", "value": "Enter"},
                    {"kind": "key", "value": "Ctrl+C", "meaning": "interrupt before delayed second delta"},
                    {"kind": "key", "value": "Ctrl+C", "meaning": "exit from ready/interrupted state"},
                ],
                "requests": requests,
                "writes": writes,
                "timing": {"first_delta_visible_after_first_write_ms": first_visible_ms},
                "visible_state": {
                    "first_delta_visible": first_visible_ms is not None,
                    "second_delta_visible_after_interrupt": contains_marker(buffer[chat_offset:], SECOND_DELTA),
                    "interrupt_surface_observed": bool(re.search(r"interrupt", interrupted_tail, re.IGNORECASE)),
                    "screen_tail": interrupted_tail,
                    "clean_exit": exited,
                },
                "normalization": "Measured write timing and socket outcome are specific to this run; no universal timeout or cancellation claim is made.",
            }

        time.sleep(0.75)
        server.recorder.release_second.set()
        second_release_at = time.monotonic()
        buffer, second_visible_ms = observe_marker(pid, fd, buffer, SECOND_DELTA, timeout, chat_offset)
        buffer = drain(pid, fd, buffer, 0.8)
        server.recorder.handler_done.wait(timeout)
        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)
        requests, writes = server.recorder.snapshot()
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "<sanitized prompt>"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Ctrl+C", "meaning": "bounded cleanup after completion"},
            ],
            "requests": requests,
            "writes": writes,
            "timing": {
                "first_delta_visible_after_first_write_ms": first_visible_ms,
                "second_delta_visible_after_release_ms": second_visible_ms,
                "measured_release_gap_ms": round((second_release_at - first_sent_at) * 1000, 1),
            },
            "visible_state": {
                "first_delta_visible": first_visible_ms is not None,
                "second_delta_visible": second_visible_ms is not None,
                "assistant_response_visible": contains_marker(buffer[chat_offset:], FIRST_DELTA) and contains_marker(buffer[chat_offset:], SECOND_DELTA),
                "clean_exit": exited,
                "screen_tail": response_prefix(buffer, chat_offset),
            },
            "normalization": "Measured write timing is specific to this run; no universal redraw latency claim is made.",
        }
    finally:
        if pid != -1:
            stop(pid, fd)
        server.close()
        shutil.rmtree(root, ignore_errors=True)


def safe_failure(error: BaseException) -> Any:
    if not isinstance(error, ProbeFailure):
        return str(error)
    details = dict(error.details)
    if "screen_tail" in details:
        details["screen_tail"] = SENSITIVE.sub("<redacted>", str(details["screen_tail"]))
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
        "observation_id": "OBS-0052",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY with deterministic delayed loopback HTTP/SSE fixture"},
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, prompt text, credentials, timestamps, process identifiers, and raw redraw noise are omitted or replaced by placeholders.",
            "The provider is a loopback HTTP/SSE fixture owned by this probe; no external network, OAuth flow, or user credential is used.",
            "Request data is reduced to method/path, content type, authorization presence, top-level keys, model, stream flag, message roles, and tool presence.",
            "The timing values describe the measured fixture release and PTY observation in this run; they are not generalized into a Hermes timeout or latency contract.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"].append(run_case(reference, args.timeout, interrupt=False))
        report["cases"].append(run_case(reference, args.timeout, interrupt=True))
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        report["failure"] = safe_failure(error)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized, encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
