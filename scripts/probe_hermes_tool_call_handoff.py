#!/usr/bin/env python3
"""Capture Hermes' bounded tool-call stream handoff without executing a tool."""

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
    child_status,
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
PROMPT = "single Hermes tool handoff prompt"
ASSISTANT_MARKER = "Synthetic handoff"
TOOL_NAME = "clarify"
TOOL_CALL_ID = "call_synthetic_clarify"
ARGUMENT_FRAGMENTS = (
    '{"question":"synthetic clarification prompt",',
    '"choices":["synthetic choice one","synthetic choice two"]}',
)


def sse_payload(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


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


def semantic_content(value: Any) -> str:
    if value == PROMPT:
        return "synthetic-user"
    if value == ASSISTANT_MARKER:
        return "synthetic-assistant-marker"
    if value is None:
        return "null"
    if isinstance(value, list):
        return "structured"
    if isinstance(value, str):
        return "other"
    return value_kind(value)


def normalized_tool_inventory(tools: Any) -> dict[str, Any]:
    if not isinstance(tools, list):
        return {"present": False, "count": 0, "names": [], "clarify_present": False}
    names: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.append(function["name"])
    return {
        "present": bool(tools),
        "count": len(tools),
        "names": names,
        "clarify_present": TOOL_NAME in names,
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
    return {
        "request_kind": (
            "streaming-chat" if stream is True
            else "auxiliary-nonstream" if "temperature" in payload
            else "other"
        ),
        "body_keys": sorted(payload),
        "model": payload.get("model"),
        "stream": stream,
        "message_count": len(messages) if isinstance(messages, list) else 0,
        "messages": normalized_messages,
        "tools": normalized_tool_inventory(payload.get("tools")),
    }


def normalized_delta(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return {"choice_shape": value_kind(choices)}
    choice = choices[0]
    delta = choice.get("delta")
    result: dict[str, Any] = {
        "choice_index": choice.get("index"),
        "delta_keys": sorted(delta) if isinstance(delta, dict) else [],
        "finish_reason": choice.get("finish_reason"),
    }
    if not isinstance(delta, dict):
        return result
    tool_calls = delta.get("tool_calls")
    if not isinstance(tool_calls, list):
        return result
    normalized_calls: list[dict[str, Any]] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            normalized_calls.append({"kind": value_kind(call)})
            continue
        function = call.get("function")
        function_summary: dict[str, Any] = {
            "keys": sorted(function) if isinstance(function, dict) else [],
        }
        if isinstance(function, dict):
            name = function.get("name")
            arguments = function.get("arguments")
            if isinstance(name, str):
                function_summary["name"] = name
            if isinstance(arguments, str):
                function_summary["arguments"] = {
                    "fragment_length": len(arguments),
                    "fragment_sha256": digest(arguments),
                }
            else:
                function_summary["arguments"] = {"kind": value_kind(arguments)}
        normalized_calls.append(
            {
                "index": call.get("index"),
                "id_marker": (
                    "synthetic-call-id"
                    if call.get("id") == TOOL_CALL_ID
                    else "absent" if "id" not in call else "other-id"
                ),
                "type": call.get("type"),
                "function": function_summary,
            }
        )
    result["tool_calls"] = normalized_calls
    return result


def safe_failure_tail(raw: bytes) -> str:
    text = safe_tail(raw)
    for value in (PROMPT, ASSISTANT_MARKER, *ARGUMENT_FRAGMENTS):
        text = text.replace(value, "<synthetic-value>")
    return text


class HandoffServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.http_requests: list[dict[str, Any]] = []
        self.chat_requests: list[dict[str, Any]] = []
        self.stream_events: list[dict[str, Any]] = []
        self.response: dict[str, Any] = {}
        self.finish_sent = threading.Event()
        self.release_stream = threading.Event()
        super().__init__((LOOPBACK_HOST, LOOPBACK_PORT), self._handler())

    def record_http(self, method: str, path: str, authorization_present: bool) -> None:
        with self.lock:
            self.http_requests.append(
                {
                    "method": method,
                    "path": path,
                    "authorization_present": authorization_present,
                }
            )

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
                owner.record_http("GET", self.path, self.headers.get("Authorization") is not None)
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
                owner.record_http("POST", self.path, self.headers.get("Authorization") is not None)
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

                request = normalized_request(payload)
                record = {
                    "path": self.path,
                    "content_type": self.headers.get("Content-Type", ""),
                    "authorization_present": self.headers.get("Authorization") is not None,
                    "request": request,
                }
                with owner.lock:
                    owner.chat_requests.append(record)

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

                tools = request["tools"]
                if not tools["clarify_present"]:
                    self.write_json({"error": {"message": "clarify was not registered"}}, 400)
                    return

                chunks = [
                    {
                        "id": "chatcmpl-synthetic",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": "palette-model",
                        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
                    },
                    {
                        "id": "chatcmpl-synthetic",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": "palette-model",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "content": ASSISTANT_MARKER,
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": TOOL_CALL_ID,
                                            "type": "function",
                                            "function": {
                                                "name": TOOL_NAME,
                                                "arguments": ARGUMENT_FRAGMENTS[0],
                                            },
                                        }
                                    ],
                                },
                                "finish_reason": None,
                            }
                        ],
                    },
                    {
                        "id": "chatcmpl-synthetic",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": "palette-model",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "function": {"arguments": ARGUMENT_FRAGMENTS[1]},
                                        }
                                    ]
                                },
                                "finish_reason": None,
                            }
                        ],
                    },
                    {
                        "id": "chatcmpl-synthetic",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": "palette-model",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                    },
                ]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                try:
                    for chunk in chunks:
                        with owner.lock:
                            owner.stream_events.append(normalized_delta(chunk))
                        self.wfile.write(sse_payload(chunk))
                        self.wfile.flush()
                    with owner.lock:
                        owner.response = {
                            "content_type": "text/event-stream",
                            "chunk_count": len(chunks),
                            "done_marker_sent": False,
                            "finish_reason_sent": "tool_calls",
                            "tool_response_sent": False,
                            "stream_stop": "after finish_reason before [DONE]",
                        }
                    owner.finish_sent.set()
                    owner.release_stream.wait(10.0)
                except OSError:
                    with owner.lock:
                        owner.response.setdefault("connection_error", "provider stream closed by bounded stop")

        return Handler

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "http_requests": list(self.http_requests),
                "chat_requests": list(self.chat_requests),
                "stream_events": list(self.stream_events),
                "response": dict(self.response),
            }


def run_case(reference: Path, timeout: float, observation_window: float) -> dict[str, Any]:
    case = "tool-call-handoff"
    try:
        parsed_arguments = json.loads("".join(ARGUMENT_FRAGMENTS))
    except json.JSONDecodeError as error:
        raise ProbeFailure(case, "fixture", f"synthetic tool arguments are not valid JSON: {error}") from error
    if not isinstance(parsed_arguments, dict) or not isinstance(parsed_arguments.get("choices"), list):
        raise ProbeFailure(case, "fixture", "synthetic clarify arguments do not match the registered object shape")
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-toolhandoff-"))
    home = root / "home"
    home.mkdir()
    server = HandoffServer()
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
        while time.monotonic() < deadline:
            snapshot = server.snapshot()
            if snapshot["chat_requests"]:
                break
            time.sleep(0.02)
        snapshot = server.snapshot()
        if not snapshot["chat_requests"]:
            raise ProbeFailure(
                case,
                "request",
                f"timed out after {timeout:.1f}s waiting for the streaming chat request",
                {"http_requests": snapshot["http_requests"], "screen_tail": safe_failure_tail(buffer)},
            )
        if not server.finish_sent.wait(timeout):
            raise ProbeFailure(
                case,
                "tool-call-stream",
                f"timed out after {timeout:.1f}s waiting for the bounded tool-call stream",
                {"chat_requests": snapshot["chat_requests"], "screen_tail": safe_failure_tail(buffer)},
            )

        buffer = drain(pid, fd, buffer, observation_window)
        before_stop = server.snapshot()
        process_alive_before_stop = not child_status(pid)[0]
        server.release_stream.set()
        stop(pid, fd)
        after_stop = server.snapshot()
        subsequent_chat_requests = max(0, len(after_stop["chat_requests"]) - 1)
        request = after_stop["chat_requests"][0]["request"]
        if request["request_kind"] != "streaming-chat":
            raise ProbeFailure(
                case,
                "request-kind",
                "the first captured chat request was not streaming",
                {"request": request},
            )
        if not request["tools"]["clarify_present"]:
            raise ProbeFailure(case, "tool-registration", "Hermes did not register clarify in the provider request")
        if after_stop["response"].get("done_marker_sent"):
            raise ProbeFailure(case, "bounded-stop", "the probe unexpectedly sent [DONE] before stopping Hermes")
        if after_stop["response"].get("tool_response_sent"):
            raise ProbeFailure(case, "bounded-stop", "a tool response was sent before the bounded stop")

        normalized_screen = safe_failure_tail(buffer)
        visible_markers = {
            "assistant_stream_marker": contains_marker(buffer, ASSISTANT_MARKER),
            "tool_processing_status": contains_marker(buffer, "Processing 1 tool call"),
            "tool_name": contains_marker(buffer, TOOL_NAME),
        }
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "<synthetic prompt>"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
            ],
            "provider_request": {
                "path": after_stop["chat_requests"][0]["path"],
                "authorization_present": after_stop["chat_requests"][0]["authorization_present"],
                "request": request,
            },
            "tool_call_deltas": after_stop["stream_events"],
            "tool_call": {
                "index": 0,
                "id_marker": "synthetic-call-id",
                "name": TOOL_NAME,
                "argument_fragments": [
                    {
                        "sequence": index + 1,
                        "length": len(fragment),
                        "sha256": digest(fragment),
                    }
                    for index, fragment in enumerate(ARGUMENT_FRAGMENTS)
                ],
                "argument_fragment_count": len(ARGUMENT_FRAGMENTS),
            },
            "finish_reason": "tool_calls",
            "visible_handoff_markers": visible_markers,
            "visible_handoff_screen_tail": "<omitted-successfully>",
            "request_counts": {
                "loopback_http_requests": len(after_stop["http_requests"]),
                "chat_requests": len(after_stop["chat_requests"]),
                "subsequent_chat_requests": subsequent_chat_requests,
                "tool_response_requests": 0,
            },
            "bounded_stop": {
                "process_alive_before_stop": process_alive_before_stop,
                "stop_signal": "SIGTERM",
                "stop_after": "finish_reason",
                "stop_before": "[DONE] and any tool response/action",
                "done_marker_sent": False,
                "tool_response_sent": False,
                "observation_window_seconds": observation_window,
                "screen_tail_observed": bool(normalized_screen),
            },
            "side_effect_boundary": {
                "provider_endpoint": "127.0.0.1 loopback owned by probe",
                "external_network": "none observed; all recorded HTTP traffic stayed on the synthetic loopback",
                "credentials": "none; only a synthetic key was placed in the throwaway config and auth values were reduced to presence booleans",
                "oauth": "not entered",
                "browser": "not started",
                "filesystem": "reference runtime state was confined to the throwaway HOME/HERMES_HOME and removed after the probe; no tool-specific path or result was observed",
                "tool_action": "not entered; the stream was stopped before [DONE]",
            },
            "clean_exit": False,
            "unknowns": [
                "Whether Hermes would display a clarify overlay, persist the assistant tool-call message, emit tool.start, invoke clarify, or issue a follow-up request after a complete [DONE]-terminated stream remains intentionally unobserved.",
                "Provider-specific retries, malformed or truncated argument handling, multiple calls, approval policy, tool results, and post-handoff failure behavior remain unknown.",
            ],
        }
    finally:
        server.release_stream.set()
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
    parser.add_argument("--observation-window", type=float, default=0.2)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0110",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with deterministic loopback HTTP/SSE fixture and bounded stop after a valid tool-call finish reason",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, prompt text, assistant text, tool arguments, credentials, authorization values, session identifiers, timestamps, and redraw bytes are omitted or represented by stable markers or digests.",
            "The provider endpoint is a deterministic 127.0.0.1 fixture owned by this probe; no external network, OAuth flow, browser, tool response, tool action, or user credential is used.",
            "The provider request retains only wire shape, message roles/semantic markers, tool count/names, and the presence of the registered clarify tool.",
            "The response records OpenAI-compatible tool-call delta shape and argument-fragment boundaries without copying argument payloads. The [DONE] marker is intentionally withheld so the process cannot enter tool processing.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        if args.observation_window < 0 or args.observation_window > 5:
            raise ProbeFailure("reference", "arguments", "observation window must be between 0 and 5 seconds")
        report["cases"].append(run_case(reference, args.timeout, args.observation_window))
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
