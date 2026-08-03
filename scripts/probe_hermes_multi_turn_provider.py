#!/usr/bin/env python3
"""Capture Hermes' bounded multi-turn provider request boundary."""

from __future__ import annotations

import argparse
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
CHAT_PATHS = {"/v1/chat/completions", "/api/chat"}
FIRST_PROMPT = "first Hermes context prompt"
SECOND_PROMPT = "second Hermes context prompt"
FIRST_ANSWER = "First Hermes context answer."
SECOND_ANSWER = "Second Hermes context answer."
SENSITIVE_ENV_PARTS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "ACCESS_KEY")


def sse_payload(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


def semantic_content(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, list):
        return "structured"
    if not isinstance(value, str):
        return type(value).__name__
    if value == FIRST_PROMPT:
        return "first-user"
    if value == SECOND_PROMPT:
        return "second-user"
    if value == FIRST_ANSWER:
        return "first-assistant"
    if value == SECOND_ANSWER:
        return "second-assistant"
    return "other"


def normalized_tool_schema(tools: Any) -> dict[str, Any]:
    if not isinstance(tools, list):
        return {"present": False, "count": 0, "names": [], "parameter_shapes": []}

    names: list[str] = []
    parameter_shapes: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            parameter_shapes.append({"kind": type(tool).__name__})
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            parameter_shapes.append({"kind": "non-function", "top_level_keys": sorted(tool)})
            continue
        name = function.get("name")
        if isinstance(name, str):
            names.append(name)
        parameters = function.get("parameters")
        if isinstance(parameters, dict):
            properties = parameters.get("properties")
            required = parameters.get("required")
            parameter_shapes.append(
                {
                    "parameter_type": parameters.get("type"),
                    "property_count": len(properties) if isinstance(properties, dict) else 0,
                    "required_count": len(required) if isinstance(required, list) else 0,
                    "top_level_keys": sorted(parameters),
                }
            )
        else:
            parameter_shapes.append({"parameter_type": type(parameters).__name__})

    return {
        "present": bool(tools),
        "count": len(tools),
        "names": names,
        "parameter_shapes": parameter_shapes,
    }


def normalized_request(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages")
    normalized_messages: list[dict[str, Any]] = []
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                normalized_messages.append({"kind": type(message).__name__})
                continue
            normalized_messages.append(
                {
                    "role": message.get("role"),
                    "content": semantic_content(message.get("content")),
                    "keys": sorted(message),
                    "tool_calls_present": bool(message.get("tool_calls")),
                }
            )

    tools = normalized_tool_schema(payload.get("tools"))
    stream = payload.get("stream")
    request_kind = (
        "streaming-chat"
        if stream is True
        else "auxiliary-nonstream"
        if "temperature" in payload
        else "other"
    )
    return {
        "request_kind": request_kind,
        "body_keys": sorted(payload),
        "model": payload.get("model"),
        "stream": stream,
        "stream_options": {
            "keys": sorted(payload["stream_options"])
            if isinstance(payload.get("stream_options"), dict)
            else [],
            "include_usage": (
                payload.get("stream_options", {}).get("include_usage")
                if isinstance(payload.get("stream_options"), dict)
                else None
            ),
        },
        "message_count": len(messages) if isinstance(messages, list) else 0,
        "messages": normalized_messages,
        "tools": tools,
    }


class MultiTurnServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        self.completed_answers: list[str] = []
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
                if self.path in {"/api/v1/models", "/v1/models"}:
                    self.write_json(
                        {
                            "object": "list",
                            "data": [{"id": "palette-model", "object": "model"}],
                        }
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

                prompt = "unknown"
                for message in payload.get("messages", []):
                    if isinstance(message, dict) and message.get("role") == "user":
                        prompt = message.get("content", "unknown")
                answer = FIRST_ANSWER if prompt == FIRST_PROMPT else SECOND_ANSWER
                record = {
                    "method": self.command,
                    "path": self.path,
                    "content_type": self.headers.get("Content-Type", ""),
                    "authorization_present": self.headers.get("Authorization") is not None,
                    "request": normalized_request(payload),
                    "prompt_marker": (
                        "first-user" if prompt == FIRST_PROMPT else
                        "second-user" if prompt == SECOND_PROMPT else "unknown"
                    ),
                }
                with owner.lock:
                    owner.requests.append(record)

                if payload.get("stream") is not True:
                    response_payload = {
                        "model": "palette-model",
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": "Synthetic auxiliary response."},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                    self.write_json(response_payload)
                    content_type = "application/json"
                    chunk_count = 1
                    response_kind = "auxiliary-json"
                elif self.path == "/api/chat":
                    payloads = [
                        {"model": "palette-model", "message": {"role": "assistant", "content": answer}, "done": False},
                        {"model": "palette-model", "message": {"role": "assistant", "content": ""}, "done": True},
                    ]
                    encoded = b"".join(
                        f"{json.dumps(item, separators=(',', ':'))}\n".encode() for item in payloads
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    content_type = "application/x-ndjson"
                    chunk_count = len(payloads)
                    response_kind = "streaming-ndjson"
                else:
                    chunks = [
                        {"choices": [{"delta": {"role": "assistant"}}]},
                        {"choices": [{"delta": {"content": answer}}]},
                        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
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
                    except OSError:
                        return
                    content_type = "text/event-stream"
                    chunk_count = len(chunks)
                    response_kind = "streaming-sse"

                with owner.lock:
                    owner.responses.append(
                        {
                            "path": self.path,
                            "content_type": content_type,
                            "chunk_count": chunk_count,
                            "done_marker_sent": response_kind != "auxiliary-json",
                            "response_kind": response_kind,
                            "answer_marker": (
                                "first-assistant"
                                if answer == FIRST_ANSWER and payload.get("stream") is True
                                else "second-assistant"
                                if answer == SECOND_ANSWER and payload.get("stream") is True
                                else "auxiliary"
                            ),
                        }
                    )
                    if payload.get("stream") is True:
                        owner.completed_answers.append(
                            "first-assistant" if answer == FIRST_ANSWER else "second-assistant"
                        )

        return Handler

    def snapshot(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with self.lock:
            return list(self.requests), list(self.responses)

    def completed(self) -> list[str]:
        with self.lock:
            return list(self.completed_answers)

    def wait_for_requests(self, count: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if len(self.requests) >= count:
                    return True
            time.sleep(0.02)
        return False

    def wait_for_answer(self, marker: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if marker in self.completed():
                return True
            time.sleep(0.02)
        return False


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "multi-turn-provider-request"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-multiturn-"))
    home = root / "home"
    home.mkdir()
    server = MultiTurnServer()
    pid = fd = -1
    buffer = b""
    try:
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        pid, fd, buffer = start_ready(reference, home, case, timeout)
        for prompt, answer, marker in (
            (FIRST_PROMPT, FIRST_ANSWER, "first-assistant"),
            (SECOND_PROMPT, SECOND_ANSWER, "second-assistant"),
        ):
            write_bytes(fd, prompt.encode())
            buffer = wait_for(
                pid,
                fd,
                buffer,
                case,
                f"{marker}-prompt",
                lambda current, value=prompt: contains_marker(current, value),
                timeout,
            )
            write_bytes(fd, b"\r")
            if not server.wait_for_requests(1 if marker == "first-assistant" else 2, timeout):
                raise ProbeFailure(
                    case,
                    f"{marker}-request",
                    f"timed out after {timeout:.1f}s waiting for the chat request",
                    {"request_count": len(server.snapshot()[0]), "screen_tail": safe_tail(buffer)},
                )
            if not server.wait_for_answer(marker, timeout):
                raise ProbeFailure(
                    case,
                    f"{marker}-response",
                    f"timed out after {timeout:.1f}s waiting for the synthetic response",
                    {"responses": server.snapshot()[1], "screen_tail": safe_tail(buffer)},
                )
            buffer = drain(pid, fd, buffer, 0.4)
            if not contains_marker(buffer, answer):
                raise ProbeFailure(
                    case,
                    f"{marker}-visible",
                    "synthetic response was not visible in the terminal",
                    {"screen_tail": safe_tail(buffer)},
                )

        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)
        requests, responses = server.snapshot()
        if len(requests) < 2:
            raise ProbeFailure(case, "normalize", "fewer than two chat requests were recorded")
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "<first synthetic prompt>"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {"kind": "text", "value": "<second synthetic prompt>"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03"},
            ],
            "chat_requests": requests,
            "chat_responses": responses,
            "request_counts": {
                "chat_requests": len(requests),
                "completed_responses": len(responses),
                "extra_requests_beyond_two": max(0, len(requests) - 2),
                "streaming_chat_requests": sum(
                    request["request"].get("request_kind") == "streaming-chat"
                    for request in requests
                ),
                "auxiliary_nonstream_requests": sum(
                    request["request"].get("request_kind") == "auxiliary-nonstream"
                    for request in requests
                ),
            },
            "visible_answers": ["first-assistant", "second-assistant"],
            "clean_exit": exited,
            "unknowns": [
                "Tool-call execution, retries, discovery details, token accounting, persistence, and behavior outside two ordinary completed turns remain unobserved.",
            ],
        }
    finally:
        if pid != -1:
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
        "observation_id": "OBS-0108",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with deterministic loopback HTTP/SSE fixture and normalized two-turn request recorder",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, prompts, response text, credentials, authorization values, session identifiers, timestamps, and redraw bytes are omitted or represented by stable markers.",
            "The provider endpoint is a deterministic 127.0.0.1 fixture owned by this probe; no external network, OAuth flow, tool action, or user credential is used.",
            "Each chat body is reduced to top-level wire keys, model/stream metadata, message role/semantic markers/keys, and a structural tool-schema summary without parameter values.",
            "Only two ordinary prompts are submitted; extra chat requests are recorded as a normalized count and are not implemented or reproduced by Hades in this research task.",
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
