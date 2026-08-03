#!/usr/bin/env python3
"""Capture the exact Hermes 31-tool inventory including description text.

A fresh synthetic Hermes TUI process submits one ordinary prompt to a
deterministic loopback provider. The probe records the complete `tools`
array from the streaming chat request: names, description text, parameter
property names/types, required fields, enums, and nested structure. Tool
definitions are public API schemas from the pinned open-source commit — not
credentials or private state.

The normalized marker digest is anchored to OBS-0109
(90bc20dad34193bb183edab4038f4ca4cf220c63de3ebcec63b90fd9d14470bf) so this
fixture is provably the same inventory, now with description text included.
No tool is executed, approved, or forwarded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import threading
import time
from http import HTTPStatus
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
    safe_tail,
    start_ready,
    stop,
    wait_for,
    write_bytes,
)
from probe_hermes_terminal_palette import drain
from probe_hermes_tool_schema_semantics import (
    digest,
    normalized_tool_schema,
)


LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PORT = 8765
CHAT_PATHS = {"/v1/chat/completions", "/api/chat"}
PROMPT = "single Hermes tool inventory prompt"
ANSWER = "Hermes tool inventory answer."
EXPECTED_TOOL_COUNT = 31
ANCHOR_DIGEST = "90bc20dad34193bb183edab4038f4ca4cf220c63de3ebcec63b90fd9d14470bf"


def sse_payload(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


class InventoryServer(ThreadingHTTPServer):
    """Loopback OpenAI-compatible recorder; returns an ordinary streamed answer."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.http_requests: list[dict[str, Any]] = []
        self.chat_requests: list[dict[str, Any]] = []
        self.answers: list[str] = []
        super().__init__((LOOPBACK_HOST, LOOPBACK_PORT), self._handler())

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                return

            def write_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
                encoded = json.dumps(payload, separators=(",", ":")).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
                with owner.lock:
                    owner.http_requests.append(
                        {"method": "GET", "path": self.path, "authorization_present": False}
                    )
                if self.path in {"/api/v1/models", "/v1/models"}:
                    self.write_json(
                        {"object": "list", "data": [{"id": "palette-model", "object": "model"}]}
                    )
                    return
                if self.path == "/v1/models/palette-model":
                    self.write_json({"id": "palette-model", "object": "model"})
                    return
                if self.path == "/api/tags":
                    self.write_json({"models": [{"name": "palette-model"}]})
                    return
                if self.path in {"/api/version", "/v1/props", "/props"}:
                    self.write_json({})
                    return
                self.write_json({"error": {"message": "synthetic endpoint not found"}}, 404)

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                try:
                    payload = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}

                if self.path == "/api/show":
                    self.write_json({"modelfile": "FROM palette-model", "details": {}})
                    return
                if self.path not in CHAT_PATHS:
                    self.write_json({"error": {"message": "synthetic endpoint not found"}}, 404)
                    return

                request = {
                    "path": self.path,
                    "content_type": self.headers.get("Content-Type", ""),
                    "authorization_present": self.headers.get("Authorization") is not None,
                    "request_kind": (
                        "streaming-chat"
                        if payload.get("stream") is True
                        else "auxiliary-nonstream"
                        if "temperature" in payload
                        else "other"
                    ),
                    "model": payload.get("model"),
                    "message_roles": [
                        item.get("role") for item in payload.get("messages", []) if isinstance(item, dict)
                    ],
                    "tools": payload.get("tools"),
                }
                with owner.lock:
                    owner.chat_requests.append(request)

                if payload.get("stream") is not True:
                    self.write_json(
                        {
                            "model": "palette-model",
                            "choices": [
                                {
                                    "index": 0,
                                    "message": {"role": "assistant", "content": "Synthetic auxiliary response."},
                                    "finish_reason": "stop",
                                }
                            ],
                        }
                    )
                    return

                chunks = [
                    {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {"content": ANSWER}, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                ]
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
                    with owner.lock:
                        owner.answers.append("streamed")
                except OSError:
                    pass

        return Handler


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "tool-inventory"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-toolinv-"))
    home = root / "home"
    home.mkdir()
    server = InventoryServer()
    pid = fd = -1
    buffer = b""
    try:
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        pid, fd, buffer = start_ready(reference, home, case, timeout)
        write_bytes(fd, PROMPT.encode())
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "prompt",
            lambda current: contains_marker(current, PROMPT),
            timeout,
        )
        write_bytes(fd, b"\r")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not server.answers:
            buffer = drain(pid, fd, buffer, 0.05)
        if not server.answers:
            raise ProbeFailure(
                case,
                "response",
                f"timed out after {timeout:.1f}s waiting for the synthetic answer",
                {"screen_tail": safe_tail(buffer)},
            )
        buffer = drain(pid, fd, buffer, 0.4)
        if not contains_marker(buffer, ANSWER):
            raise ProbeFailure(
                case,
                "visible",
                "synthetic answer was not visible in the terminal",
                {"screen_tail": safe_tail(buffer)},
            )

        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)
        streaming = [
            request
            for request in server.chat_requests
            if request["request_kind"] == "streaming-chat" and isinstance(request["tools"], list)
        ]
        if len(streaming) != 1:
            raise ProbeFailure(
                case,
                "requests",
                f"expected one streaming chat request with tools, got {len(streaming)}",
                {"request_count": len(server.chat_requests), "screen_tail": safe_tail(buffer)},
            )
        tools = streaming[0]["tools"]
        if len(tools) != EXPECTED_TOOL_COUNT:
            raise ProbeFailure(
                case,
                "tool-count",
                f"expected {EXPECTED_TOOL_COUNT} tools, got {len(tools)}",
                {"count": len(tools), "screen_tail": safe_tail(buffer)},
            )
        normalized = normalized_tool_schema(tools)
        if normalized["inventory_sha256"] != ANCHOR_DIGEST:
            raise ProbeFailure(
                case,
                "anchor",
                "normalized inventory digest does not match the OBS-0109 anchor",
                {
                    "observed": normalized["inventory_sha256"],
                    "expected": ANCHOR_DIGEST,
                },
            )
        raw_digest = digest(tools)
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "<synthetic prompt>"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
            ],
            "provider_request": {
                "path": streaming[0]["path"],
                "authorization_present": streaming[0]["authorization_present"],
                "model": streaming[0]["model"],
                "message_roles": streaming[0]["message_roles"],
            },
            "tool_inventory": {
                "present": True,
                "count": len(tools),
                "names": [tool.get("function", {}).get("name") for tool in tools],
                "inventory_sha256": raw_digest,
                "normalized_inventory_sha256": normalized["inventory_sha256"],
                "anchor_digest": ANCHOR_DIGEST,
                "anchor_observation": "OBS-0109",
                "tools": tools,
            },
            "visible_answer": "streamed and rendered",
            "clean_exit": exited,
        }
    finally:
        stop(pid, fd)
        server.shutdown()
        server.server_close()
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
        "observation_id": "OBS-0112",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with deterministic loopback HTTP/SSE inventory recorder",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, prompt text, answer text, credentials, authorization values, session identifiers, timestamps, and redraw bytes are omitted or represented by stable markers.",
            "Tool definitions are public API schemas from the pinned open-source commit and are recorded in full (names, descriptions, parameter names/types, required fields, enums, nested structure).",
            "The normalized structural marker digest is anchored to OBS-0109 to prove this is the same 31-tool inventory.",
            "No tool is executed, approved, or forwarded; the live process is interrupted and cleaned up after the bounded streamed answer.",
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
        if isinstance(error, ProbeFailure):
            report["failure"] = error.as_dict()
        else:
            report["failure"] = str(error)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
