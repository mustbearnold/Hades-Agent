#!/usr/bin/env python3
"""Capture Hermes' first local-provider request and bounded response stream."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from probe_hermes_slash_commands import (
    COLUMNS,
    DEFAULT_REFERENCE,
    ROWS,
    SOURCE_COMMIT,
    ProbeFailure,
    clean_exit,
    contains_marker,
    normalized,
    safe_tail,
    start_ready,
    stop,
    wait_for,
    write_bytes,
)
from probe_hermes_terminal_palette import drain


LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PORT = 8765
REQUEST_PATH = "/v1/chat/completions"
CHAT_PATHS = {REQUEST_PATH, "/api/chat"}
RESPONSE_TEXT = "Synthetic loopback response."
VISIBLE_MARKER_CANDIDATES = (
    RESPONSE_TEXT,
    "ready",
    "musing…",
    "Ctrl+C to interrupt",
    "Connection error",
    "API call failed",
)


def sse_payload(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


class LoopbackRecorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []

    def record_request(self, method: str, path: str, headers: dict[str, str], body: bytes) -> None:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        messages = payload.get("messages", [])
        roles = [message.get("role") for message in messages if isinstance(message, dict)]
        record = {
            "method": method,
            "path": path,
            "content_type": headers.get("content-type", ""),
            "authorization_present": "authorization" in headers,
            "body_keys": sorted(payload) if isinstance(payload, dict) else [],
            "model": payload.get("model") if isinstance(payload, dict) else None,
            "stream": payload.get("stream") if isinstance(payload, dict) else None,
            "message_count": len(messages) if isinstance(messages, list) else 0,
            "message_roles": roles,
            "tools_present": bool(payload.get("tools")) if isinstance(payload, dict) else False,
        }
        with self._lock:
            self.requests.append(record)

    def record_response(self, path: str, chunk_count: int, done: bool, content_type: str) -> None:
        with self._lock:
            self.responses.append(
                {
                    "path": path,
                    "content_type": content_type,
                    "chunk_count": chunk_count,
                    "done_marker_sent": done,
                    "response_text": RESPONSE_TEXT,
                }
            )

    def snapshot(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with self._lock:
            return list(self.requests), list(self.responses)


class LoopbackHandler(BaseHTTPRequestHandler):
    server: "LoopbackServer"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _write_ndjson(self, payloads: list[dict[str, Any]]) -> None:
        encoded = b"".join(
            f"{json.dumps(payload, separators=(',', ':'))}\n".encode() for payload in payloads
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        self.server.recorder.record_request("GET", self.path, {}, b"")
        if self.path in {"/v1/models", "/api/v1/models"}:
            self._write_json(
                200,
                {
                    "object": "list",
                    "data": [{"id": "palette-model", "object": "model", "owned_by": "synthetic"}],
                },
            )
            return
        if self.path == "/api/tags":
            self._write_json(200, {"models": [{"name": "palette-model", "model": "palette-model"}]})
            return
        if self.path == "/api/version":
            self._write_json(200, {"version": "synthetic"})
            return
        if self.path in {"/v1/props", "/props"}:
            self._write_json(200, {})
            return
        if self.path == "/v1/models/palette-model":
            self._write_json(200, {"id": "palette-model", "object": "model"})
            return
        self._write_json(404, {"error": {"message": "synthetic endpoint not found"}})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        headers = {key.lower(): value for key, value in self.headers.items()}
        self.server.recorder.record_request("POST", self.path, headers, body)

        if self.path == "/api/show":
            self._write_json(
                200,
                {
                    "modelfile": "FROM palette-model",
                    "parameters": "",
                    "template": "",
                    "details": {"family": "synthetic", "families": ["synthetic"]},
                },
            )
            return

        if self.path == "/api/chat":
            payloads = [
                {
                    "model": "palette-model",
                    "message": {"role": "assistant", "content": RESPONSE_TEXT},
                    "done": False,
                },
                {
                    "model": "palette-model",
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "stop",
                },
            ]
            self.server.recorder.record_response(self.path, len(payloads), True, "application/x-ndjson")
            self._write_ndjson(payloads)
            return

        chunks = [
            {
                "id": "synthetic-chat",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "palette-model",
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            },
            {
                "id": "synthetic-chat",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "palette-model",
                "choices": [{"index": 0, "delta": {"content": RESPONSE_TEXT}, "finish_reason": None}],
            },
            {
                "id": "synthetic-chat",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "palette-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
        ]
        self.server.recorder.record_response(self.path, len(chunks), True, "text/event-stream")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for chunk in chunks:
                self.wfile.write(sse_payload(chunk))
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except BrokenPipeError:
            # The response boundary is recorded even if Hermes closes after
            # receiving enough bytes to render its first visible state.
            return


class LoopbackServer:
    def __init__(self) -> None:
        self.recorder = LoopbackRecorder()
        self.httpd = ThreadingHTTPServer((LOOPBACK_HOST, LOOPBACK_PORT), LoopbackHandler)
        self.httpd.recorder = self.recorder
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def wait_for_chat_request(self, timeout: float, after: int = 0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            requests, _responses = self.recorder.snapshot()
            if any(
                request["method"] == "POST" and request["path"] in CHAT_PATHS
                for request in requests[after:]
            ):
                return True
            time.sleep(0.05)
        return False

    def wait_for_response(self, timeout: float, after: int = 0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _requests, responses = self.recorder.snapshot()
            if any(response["path"] in CHAT_PATHS for response in responses[after:]):
                return True
            time.sleep(0.05)
        return False

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


def emit_report(report: dict[str, Any], path: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")


def safe_failure(error: BaseException) -> Any:
    if not isinstance(error, ProbeFailure):
        return str(error)
    details = dict(error.details)
    if "screen_tail" in details:
        details["screen_tail"] = safe_tail(str(details["screen_tail"]).encode())
    return {"case": error.case, "step": error.step, "message": error.message, **details}


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "local-provider-stream"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-local-stream-"))
    home = root / "home"
    home.mkdir()
    server = LoopbackServer()
    pid = fd = -1
    buffer = b""
    try:
        server.start()
        pid, fd, buffer = start_ready(reference, home, case, timeout)
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "composer-ready",
            lambda current: re.search(r"(?m)ready\s*│", normalized(current)[-1200:], re.IGNORECASE)
            is not None,
            timeout,
        )
        buffer = drain(pid, fd, buffer, 0.2)
        request_count_before_prompt, response_count_before_prompt = (
            len(server.recorder.snapshot()[0]),
            len(server.recorder.snapshot()[1]),
        )
        write_bytes(fd, b"hello loopback")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "prompt-echo",
            lambda current: contains_marker(current, "hello loopback"),
            timeout,
        )
        buffer = drain(pid, fd, buffer, 0.1)
        write_bytes(fd, b"\r")
        if not server.wait_for_chat_request(timeout, request_count_before_prompt):
            buffer = drain(pid, fd, buffer, 0.2)
            requests, responses = server.recorder.snapshot()
            raise ProbeFailure(
                case,
                "request",
                f"timed out after {timeout:.1f}s waiting for POST",
                {"requests": requests[-6:], "responses": responses[-6:], "screen_tail": safe_tail(buffer)},
            )
        if not server.wait_for_response(timeout, response_count_before_prompt):
            requests, responses = server.recorder.snapshot()
            raise ProbeFailure(
                case,
                "response",
                f"timed out after {timeout:.1f}s waiting for SSE response",
                {"requests": requests, "responses": responses},
            )
        buffer = drain(pid, fd, buffer, 1.5)
        requests, responses = server.recorder.snapshot()
        visible_markers = [marker for marker in VISIBLE_MARKER_CANDIDATES if contains_marker(buffer, marker)]
        chat_requests = [request for request in requests if request["path"] in CHAT_PATHS]
        chat_responses = [response for response in responses if response["path"] in CHAT_PATHS]
        if not chat_requests or not chat_responses:
            raise ProbeFailure(case, "normalize", "chat boundary disappeared before report emission")
        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "<sanitized prompt>"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03"},
            ],
            "request": {
                "discovery": [request for request in requests if request["path"] not in CHAT_PATHS],
                "first_chat": chat_requests[0],
                "subsequent_chat_request_count": len(chat_requests) - 1,
            },
            "response": {
                "first_chat": chat_responses[0],
                "subsequent_chat_response_count": len(chat_responses) - 1,
            },
            "stream_landmarks": {
                "request_path": chat_requests[0]["path"],
                "stream_requested": chat_requests[0]["stream"],
                "response_content_type": chat_responses[0]["content_type"],
                "response_chunk_count": chat_responses[0]["chunk_count"],
                "done_marker_sent": chat_responses[0]["done_marker_sent"],
                "assistant_text_marker": chat_responses[0]["response_text"],
            },
            "visible_state": {
                "markers": visible_markers,
                "returned_to_ready": contains_marker(buffer, "ready"),
                "interrupt_control_visible": contains_marker(buffer, "Ctrl+C to interrupt"),
            },
            "clean_exit": exited,
            "cleanup": "Ctrl+C interrupted or exited the bounded local-provider turn cleanly",
        }
    finally:
        if pid != -1:
            stop(pid, fd)
        server.close()
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0050",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with local loopback HTTP/SSE recorder and normalized screen landmarks",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, prompt text, credentials, authorization values, session identifiers, timestamps, and animated redraw bytes are omitted or replaced by placeholders.",
            "The provider endpoint is a deterministic 127.0.0.1 HTTP/SSE fixture owned by this probe; no external network or user credential is used.",
            "Request bodies are reduced to method/path, content type, authorization presence, top-level keys, model, stream flag, message roles/count, and tool presence; prompt content and headers are not persisted.",
            "The response body is reduced to the normalized SSE content marker, chunk count, and DONE marker; exact IDs, timestamps, and raw bytes are omitted.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"].append(run_case(reference, args.timeout))
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        report["failure"] = safe_failure(error)
    emit_report(report, args.report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
