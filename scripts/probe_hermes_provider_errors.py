#!/usr/bin/env python3
"""Capture Hermes provider HTTP, malformed-stream, and incomplete-stream behavior."""

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
from http import HTTPStatus
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
PARTIAL_MARKER = "HERMES_PARTIAL_ERROR"
SENSITIVE = re.compile(r"(?:/tmp|/home)/[^\s\r\n]+|synthetic-probe-key", re.IGNORECASE)
ERROR_MARKERS = ("Connection error", "API call failed", "Provider error", "failed", "interrupted", "ready", PARTIAL_MARKER)


def sse_payload(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


class ErrorServer:
    def __init__(self, case: str) -> None:
        self.case = case
        self.records: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.request_seen = threading.Event()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.httpd.owner = self
        self.thread = threading.Thread(target=self.httpd.serve_forever, name=f"hermes-error-{case}", daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_port}/v1"

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
                messages = payload.get("messages", []) if isinstance(payload, dict) else []
                record = {
                    "path": self.path,
                    "method": self.command,
                    "content_type": self.headers.get("Content-Type", ""),
                    "authorization_present": self.headers.get("Authorization") is not None,
                    "body_keys": sorted(payload) if isinstance(payload, dict) else [],
                    "model": payload.get("model") if isinstance(payload, dict) else None,
                    "stream": payload.get("stream") if isinstance(payload, dict) else None,
                    "message_roles": [message.get("role") for message in messages if isinstance(message, dict)],
                    "tools_present": bool(payload.get("tools")) if isinstance(payload, dict) else False,
                }
                with owner.lock:
                    owner.records.append(record)
                owner.request_seen.set()

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
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(encoded)
                    return
                if self.path != CHAT_PATH:
                    self.send_error(404)
                    return

                if owner.case == "http-error":
                    body = b'{"error":{"message":"synthetic provider failure"}}'
                    self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(body)
                    return

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                if owner.case == "malformed-sse":
                    self.wfile.write(b"data: {not-json}\n\n")
                    self.wfile.flush()
                    return

                self.wfile.write(sse_payload({"choices": [{"delta": {"role": "assistant"}}]}))
                self.wfile.write(sse_payload({"choices": [{"delta": {"content": PARTIAL_MARKER}}]}))
                self.wfile.flush()
                # Deliberately close without [DONE]. Hermes must decide what to
                # show and whether to issue another request; the probe records
                # that behavior without naming it a retry.

        return Handler

    def start(self) -> None:
        self.thread.start()

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(record) for record in self.records]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


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


def wait_for_quiet(pid: int, fd: int, buffer: bytes, server: ErrorServer, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    quiet_since: float | None = None
    previous_count = 0
    while time.monotonic() < deadline:
        buffer = drain(pid, fd, buffer, 0.05)
        count = len(server.snapshot())
        if count:
            if count != previous_count:
                previous_count = count
                quiet_since = time.monotonic()
            elif quiet_since is not None and time.monotonic() - quiet_since >= 0.75:
                return buffer
        time.sleep(0.05)
    return buffer


def safe_tail(raw: bytes) -> str:
    return SENSITIVE.sub("<redacted>", normalized(raw)[-2600:])


def marker_in_text(text: str, marker: str) -> bool:
    if marker.lower() in text.lower():
        return True
    compact_text = "".join(text.lower().split())
    return "".join(marker.lower().split()) in compact_text


def run_case(reference: Path, case: str, timeout: float) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix=f"hades-hermes-provider-error-{case}-"))
    home = root / "home"
    home.mkdir()
    server = ErrorServer(case)
    pid = fd = -1
    buffer = b""
    try:
        server.start()
        pid, fd, buffer = start_ready(reference, home, server.base_url, case, timeout)
        write_bytes(fd, b"probe-text-058")
        buffer = wait_for(pid, fd, buffer, case, "prompt", lambda current: contains_marker(current, "probe-text-058"), timeout)
        pre_submit_text = normalized(buffer)
        write_bytes(fd, b"\r")
        if not server.request_seen.wait(timeout):
            raise ProbeFailure(case, "request", "timed out waiting for provider request", {"screen_tail": safe_tail(buffer)})
        buffer = wait_for_quiet(pid, fd, buffer, server, min(timeout, 5.0))
        buffer = drain(pid, fd, buffer, 0.5)
        requests_before_cleanup = server.snapshot()
        post_submit_text = normalized(buffer)
        post_submit_text = post_submit_text[len(pre_submit_text) :]
        visible_markers = {marker: marker_in_text(post_submit_text, marker) for marker in ERROR_MARKERS}
        screen_tail_before_cleanup = safe_tail(buffer)
        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)
        requests_after_cleanup = server.snapshot()
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "<sanitized prompt>"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Ctrl+C", "meaning": "bounded cleanup"},
            ],
            "requests": requests_before_cleanup,
            "request_count_before_cleanup": len(requests_before_cleanup),
            "request_count_after_cleanup": len(requests_after_cleanup),
            "visible_markers": visible_markers,
            "post_submit_markers": {
                "ready_surface": marker_in_text(post_submit_text, "ready"),
                "interrupt_surface": marker_in_text(post_submit_text, "interrupted"),
            },
            "screen_tail_before_cleanup": screen_tail_before_cleanup,
            "clean_exit": exited,
            "normalization": "The bounded quiet window records observed follow-up requests without classifying their purpose as retry, summary, or tool behavior.",
        }
    finally:
        if pid != -1:
            stop(pid, fd)
        server.close()
        shutil.rmtree(root, ignore_errors=True)


def safe_failure(error: BaseException) -> Any:
    if isinstance(error, ProbeFailure):
        details = dict(error.details)
        if "screen_tail" in details:
            details["screen_tail"] = SENSITIVE.sub("<redacted>", str(details["screen_tail"]))
        return {"case": error.case, "step": error.step, "message": error.message, **details}
    return str(error)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0054",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY with deterministic loopback HTTP/SSE failure fixtures"},
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, prompt text, credentials, authorization values, session identifiers, timestamps, process identifiers, and animated redraw bytes are omitted or replaced by stable markers.",
            "The provider is a deterministic 127.0.0.1 fixture owned by this probe; no external network, OAuth flow, or user credential is used.",
            "Request records are reduced to method/path, content type, authorization presence, body keys, model, stream flag, message roles, and tool presence. Follow-up requests in the bounded quiet window are retained without an inferred purpose.",
            "Visible output is represented by stable candidate markers and a redacted screen tail; spinner, face, provider inventory, and redraw timing are not treated as contracts.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        for case in ("http-error", "malformed-sse", "incomplete-stream"):
            report["cases"].append(run_case(reference, case, args.timeout))
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
