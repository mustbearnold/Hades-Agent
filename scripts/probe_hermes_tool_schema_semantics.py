#!/usr/bin/env python3
"""Capture Hermes tool-schema semantics without entering a tool-call path."""

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


LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PORT = 8765
CHAT_PATHS = {"/v1/chat/completions", "/api/chat"}
FIRST_PROMPT = "first Hermes schema prompt"
SECOND_PROMPT = "second Hermes schema prompt"
FIRST_ANSWER = "First Hermes schema answer."
SECOND_ANSWER = "Second Hermes schema answer."


def sse_payload(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


def semantic_content(value: Any) -> str:
    if value == FIRST_PROMPT:
        return "first-user"
    if value == SECOND_PROMPT:
        return "second-user"
    if value == FIRST_ANSWER:
        return "first-assistant"
    if value == SECOND_ANSWER:
        return "second-assistant"
    if value is None:
        return "null"
    if isinstance(value, list):
        return "structured"
    if isinstance(value, str):
        return "other"
    return type(value).__name__


def digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def value_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def description_marker(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        return {"present": False}
    return {
        "present": True,
        "length": len(value),
        "sha256": hashlib.sha256(value.encode()).hexdigest(),
    }


def schema_node(value: Any, depth: int = 0) -> dict[str, Any]:
    """Keep JSON-schema structure while excluding description payloads."""

    if not isinstance(value, dict):
        return {"kind": value_kind(value)}

    summary: dict[str, Any] = {
        "top_level_keys": sorted(value),
        "description": description_marker(value.get("description")),
    }
    for key in ("type", "format", "title", "pattern"):
        if key in value and isinstance(value[key], str):
            summary[key] = value[key]
    if "type" in value and isinstance(value["type"], list):
        summary["type"] = [item for item in value["type"] if isinstance(item, str)]
    if "additionalProperties" in value:
        additional = value["additionalProperties"]
        summary["additional_properties"] = (
            additional if isinstance(additional, bool) else value_kind(additional)
        )
    if isinstance(value.get("required"), list):
        summary["required"] = sorted(item for item in value["required"] if isinstance(item, str))
    if isinstance(value.get("enum"), list):
        summary["enum_count"] = len(value["enum"])
        summary["enum_value_kinds"] = sorted({value_kind(item) for item in value["enum"]})
    if isinstance(value.get("items"), dict):
        summary["items"] = schema_node(value["items"], depth + 1) if depth < 4 else {"kind": "object"}

    properties = value.get("properties")
    if isinstance(properties, dict):
        entries: list[dict[str, Any]] = []
        for name in sorted(properties):
            property_value = properties[name]
            entry: dict[str, Any] = {"name": name}
            if isinstance(property_value, dict):
                entry["schema"] = (
                    schema_node(property_value, depth + 1)
                    if depth < 4
                    else {"top_level_keys": sorted(property_value)}
                )
            else:
                entry["kind"] = value_kind(property_value)
            entries.append(entry)
        summary["properties"] = entries
        summary["property_names"] = [entry["name"] for entry in entries]

    for key in ("oneOf", "anyOf", "allOf"):
        alternatives = value.get(key)
        if isinstance(alternatives, list):
            summary[key] = [
                schema_node(item, depth + 1) if depth < 4 else {"kind": value_kind(item)}
                for item in alternatives
            ]

    return summary


def normalized_tool_schema(tools: Any) -> dict[str, Any]:
    if not isinstance(tools, list):
        return {"present": False, "count": 0, "tools": [], "inventory_sha256": None}

    normalized_tools: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            normalized_tools.append({"kind": value_kind(tool)})
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            normalized_tools.append({"top_level_keys": sorted(tool), "function": {"kind": "missing"}})
            continue
        parameters = function.get("parameters")
        normalized_tools.append(
            {
                "top_level_keys": sorted(tool),
                "type": tool.get("type"),
                "function": {
                    "keys": sorted(function),
                    "name": function.get("name"),
                    "description": description_marker(function.get("description")),
                    "strict": function.get("strict") if isinstance(function.get("strict"), bool) else None,
                    "parameters": schema_node(parameters),
                },
            }
        )

    return {
        "present": bool(tools),
        "count": len(tools),
        "tools": normalized_tools,
        "inventory_sha256": digest(normalized_tools),
    }


def normalized_request(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages")
    normalized_messages: list[dict[str, Any]] = []
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                normalized_messages.append({"kind": value_kind(message)})
                continue
            normalized_messages.append(
                {
                    "role": message.get("role"),
                    "content": semantic_content(message.get("content")),
                    "keys": sorted(message),
                    "tool_calls_present": bool(message.get("tool_calls")),
                }
            )

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
        "message_count": len(messages) if isinstance(messages, list) else 0,
        "message_roles": [message.get("role") for message in normalized_messages],
        "messages": normalized_messages,
        "tools": normalized_tool_schema(payload.get("tools")),
    }


class SchemaServer(ThreadingHTTPServer):
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

                prompt = "unknown"
                for message in payload.get("messages", []):
                    if isinstance(message, dict) and message.get("role") == "user":
                        prompt = message.get("content", "unknown")
                answer = FIRST_ANSWER if prompt == FIRST_PROMPT else SECOND_ANSWER
                request = normalized_request(payload)
                with owner.lock:
                    owner.requests.append(
                        {
                            "path": self.path,
                            "content_type": self.headers.get("Content-Type", ""),
                            "authorization_present": self.headers.get("Authorization") is not None,
                            "prompt_marker": (
                                "first-user" if prompt == FIRST_PROMPT else
                                "second-user" if prompt == SECOND_PROMPT else "unknown"
                            ),
                            "request": request,
                        }
                    )

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
                    encoded = b"".join(f"{json.dumps(item, separators=(',', ':'))}\n".encode() for item in payloads)
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

    def wait_for_answer(self, marker: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if marker in self.completed_answers:
                    return True
            time.sleep(0.02)
        return False


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "tool-schema-semantics"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-toolschema-"))
    home = root / "home"
    home.mkdir()
    server = SchemaServer()
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
            if not server.wait_for_answer(marker, timeout):
                raise ProbeFailure(
                    case,
                    f"{marker}-response",
                    f"timed out after {timeout:.1f}s waiting for the synthetic response",
                    {"screen_tail": safe_tail(buffer)},
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
        schema_requests = [
            item["request"]
            for item in requests
            if item["request"]["request_kind"] == "streaming-chat"
            and item["request"]["tools"]["present"]
        ]
        if len(schema_requests) < 2:
            raise ProbeFailure(
                case,
                "schema-requests",
                "fewer than two streaming requests with tools were recorded",
                {"request_count": len(requests), "screen_tail": safe_tail(buffer)},
            )
        inventories = [request["tools"] for request in schema_requests]
        stable = len({inventory["inventory_sha256"] for inventory in inventories}) == 1
        if not stable:
            raise ProbeFailure(
                case,
                "schema-stability",
                "tool schema inventory changed between bounded ordinary turns",
                {"inventory_sha256": [inventory["inventory_sha256"] for inventory in inventories]},
            )
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
            "request_counts": {
                "chat_requests": len(requests),
                "streaming_chat_requests": sum(
                    item["request"]["request_kind"] == "streaming-chat" for item in requests
                ),
                "schema_bearing_streaming_requests": len(schema_requests),
                "auxiliary_nonstream_requests": sum(
                    item["request"]["request_kind"] == "auxiliary-nonstream" for item in requests
                ),
            },
            "request_order": [
                {
                    "prompt_marker": item["prompt_marker"],
                    "authorization_present": item["authorization_present"],
                    "content_type": item["content_type"],
                    "path": item["path"],
                    "request": item["request"],
                }
                for item in requests
            ],
            "schema_inventory": inventories[0],
            "schema_stable_across_streaming_turns": stable,
            "responses": responses,
            "visible_answers": ["first-assistant", "second-assistant"],
            "clean_exit": exited,
            "terminal_restoration": "bounded Ctrl+C cleanup returned the PTY to the reference clean-exit boundary",
            "unknowns": [
                "Tool-call response handling, execution, approval, retries, discovery details, persistence, token accounting, and behavior outside two ordinary completed turns remain unobserved.",
                "Description text is represented by presence, length, and a digest; private or dynamic description payloads are not copied into the fixture.",
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
        "observation_id": "OBS-0109",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with deterministic loopback HTTP/SSE fixture and normalized tool-schema recorder",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, prompts, response text, credentials, authorization values, session identifiers, timestamps, and redraw bytes are omitted or represented by stable markers.",
            "The provider endpoint is a deterministic 127.0.0.1 fixture owned by this probe; no external network, OAuth flow, tool action, or user credential is used.",
            "Tool descriptions are reduced to presence, byte length, and SHA-256 digest; parameter schemas retain names, types, required names, structural keys, shape markers, and counts without copying descriptions or arbitrary values.",
            "Only ordinary streamed turns are submitted. The probe records any auxiliary non-stream request but never returns a tool-call response or treats an extra request as a Hades requirement.",
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
