#!/usr/bin/env python3
"""Capture the pinned Hermes reference executing tools against a synthetic sandbox.

Four bounded scenarios, each its own fresh synthetic Hermes TUI process with a
deterministic loopback OpenAI-compatible provider at a 120x40 PTY:

- S1 terminal tool: the provider asks Hermes to run a command whose only side
  effect writes into a probe-owned temp dir (`mkdir -p <sandbox>/out && echo
  synthetic > <sandbox>/out/out.txt`). Records the executed command's structural
  markers, the follow-up request's `tool` role message shape, and the next
  assistant turn.
- S2 file tools: `write_file` then `read_file` then `search_files` (list)
  against the probe-owned temp dir. Records result content shapes and the
  follow-up loop across three hops.
- S3 clarify: the observed interactive question surface boundary (OBS-0116) —
  arrow navigation, Enter selection, and the tool-result JSON shape
  (`question`, `choices_offered`, `user_response`).
- S4 multi-hop: the provider answers the first tool result with a second tool
  call, then a plain completion — two hops then termination. Records request
  counts and the termination condition.

Every tool side effect is confined to the probe-owned sandbox directory and a
throwaway synthetic HOME/HERMES_HOME. No credentials, no external network, no
real filesystem outside the sandbox, no installer/browser side effects. Raw
tool arguments, results, and transcripts are never persisted — only normalized
shape (kinds, lengths, digests, structural markers). Any unstable or
unobserved transition (approval UI, retries, failure paths, timing) is
recorded as an explicit unknown, never guessed.
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
from typing import Any, Callable

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
    write_bytes,
)
from probe_hermes_terminal_palette import drain
from probe_hermes_standalone_terminal_platform import rendered_text

LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PORT = 8765
CHAT_PATHS = {"/v1/chat/completions", "/api/chat"}
COMPLETION_TEXT = "Synthetic completion."
AUXILIARY_TEXT = "Synthetic auxiliary response."
OBSERVATION_WINDOW = 3.0
SURFACE_WAIT_TIMEOUT = 15.0
STEP_WINDOW_SECONDS = 0.35
ARROW_DOWN = b"\x1b[B"
ARROW_UP = b"\x1b[A"
ENTER = b"\r"

CLARIFY_QUESTION = "synthetic clarification question"
CLARIFY_CHOICES = ("synthetic choice one", "synthetic choice two")

SYNTHETIC_CALL_IDS = {
    "call_synthetic_terminal",
    "call_synthetic_write_file",
    "call_synthetic_read_file",
    "call_synthetic_search_files",
    "call_synthetic_clarify",
}


def sse_payload(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


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


def normalized_request(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages")
    normalized_messages: list[dict[str, Any]] = []
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                normalized_messages.append({"kind": value_kind(message)})
                continue
            tool_call_id = message.get("tool_call_id")
            normalized_messages.append(
                {
                    "role": message.get("role"),
                    "content_kind": value_kind(message.get("content")),
                    "keys": sorted(message),
                    "tool_calls_present": bool(message.get("tool_calls")),
                    "tool_call_id_marker": (
                        "synthetic-call-id"
                        if tool_call_id in SYNTHETIC_CALL_IDS
                        else "absent"
                        if "tool_call_id" not in message
                        else "other-id"
                    ),
                }
            )
    return {
        "request_kind": (
            "streaming-chat"
            if payload.get("stream") is True
            else "auxiliary-nonstream"
            if "temperature" in payload
            else "other"
        ),
        "body_keys": sorted(payload),
        "model": payload.get("model"),
        "stream": payload.get("stream"),
        "message_count": len(normalized_messages),
        "messages": normalized_messages,
        "tools": {
            "present": isinstance(payload.get("tools"), list) and bool(payload["tools"]),
            "count": len(payload.get("tools", [])) if isinstance(payload.get("tools"), list) else 0,
            "names": [
                tool.get("function", {}).get("name")
                for tool in payload.get("tools", [])
                if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
            ],
        },
    }


def safe_screen_tail(raw: bytes, sensitive: tuple[str, ...]) -> str:
    text = safe_tail(raw)
    for value in sensitive:
        text = text.replace(value, "<synthetic-value>")
    return text


def tool_call_chunks(
    marker: str,
    tool_name: str,
    call_id: str,
    arguments: str,
) -> list[dict[str, Any]]:
    return [
        {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "content": marker,
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": call_id,
                                "type": "function",
                                "function": {"name": tool_name, "arguments": arguments},
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ]
        },
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]


def completion_chunks(text: str = COMPLETION_TEXT) -> list[dict[str, Any]]:
    return [
        {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]


def tool_arguments_shape(arguments: str, markers: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    parsed: Any = None
    try:
        parsed = json.loads(arguments)
    except (json.JSONDecodeError, UnicodeDecodeError):
        parsed = None
    shape: dict[str, Any] = {
        "length": len(arguments),
        "sha256": hashlib.sha256(arguments.encode()).hexdigest(),
        "valid_json": parsed is not None,
    }
    if isinstance(parsed, dict):
        shape["top_level_keys"] = sorted(parsed)
        shape["value_kinds"] = {key: value_kind(value) for key, value in parsed.items()}
        shape["markers"] = markers(parsed)
    return shape


def sandbox_command_markers(*basenames: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def markers(parsed: dict[str, Any]) -> dict[str, Any]:
        command = parsed.get("command")
        if not isinstance(command, str):
            return {"command_present": False}
        lowered = command.lower()
        return {
            "command_present": True,
            "contains_mkdir": "mkdir" in lowered,
            "contains_echo": "echo" in lowered,
            "contains_redirection": ">" in command,
            "contains_chain": "&&" in command,
            "contains_expected_basename": any(name in command for name in basenames),
        }

    return markers


def file_path_markers(parsed: dict[str, Any]) -> dict[str, Any]:
    path = parsed.get("path")
    return {
        "path_kind": value_kind(path),
        "path_ends_with_expected_basename": (
            isinstance(path, str) and path.endswith("out.txt")
            or isinstance(path, str) and path.endswith("sample.txt")
            or isinstance(path, str) and path.endswith("hop.txt")
        ),
    }


def search_files_markers(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "pattern": parsed.get("pattern"),
        "target": parsed.get("target"),
        "path_kind": value_kind(parsed.get("path")),
    }


def clarify_markers(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "question_present": parsed.get("question") == CLARIFY_QUESTION,
        "choices": parsed.get("choices"),
    }


def scenario_s1(sandbox: Path) -> dict[str, Any]:
    out_dir = sandbox / "out"
    command = f"mkdir -p {out_dir} && echo synthetic > {out_dir}/out.txt"
    return {
        "id": "s1-terminal",
        "observation_id": "OBS-0117",
        "prompt": "single Hermes terminal tool execution prompt",
        "assistant_marker": "Synthetic terminal tool call",
        "script": [
            {
                "kind": "tool-call",
                "marker": "Synthetic terminal tool call",
                "tool": "terminal",
                "call_id": "call_synthetic_terminal",
                "arguments": json.dumps({"command": command}, separators=(",", ":")),
                "arguments_markers": sandbox_command_markers("out.txt"),
            },
            {"kind": "completion", "text": COMPLETION_TEXT},
        ],
        "side_effects": {"files": {str(out_dir / "out.txt"): "synthetic"}},
        "anchors": ("synthetic", "out.txt"),
        "screen_markers": ["Synthetic terminal tool call", "terminal", COMPLETION_TEXT],
    }


def scenario_s2(sandbox: Path) -> dict[str, Any]:
    sample = sandbox / "sample.txt"
    return {
        "id": "s2-file-tools",
        "observation_id": "OBS-0118",
        "prompt": "single Hermes file tool execution prompt",
        "assistant_marker": "Synthetic file tool call",
        "script": [
            {
                "kind": "tool-call",
                "marker": "Synthetic write tool call",
                "tool": "write_file",
                "call_id": "call_synthetic_write_file",
                "arguments": json.dumps(
                    {"path": str(sample), "content": "synthetic file content"}, separators=(",", ":")
                ),
                "arguments_markers": file_path_markers,
            },
            {
                "kind": "tool-call",
                "marker": "Synthetic read tool call",
                "tool": "read_file",
                "call_id": "call_synthetic_read_file",
                "arguments": json.dumps({"path": str(sample)}, separators=(",", ":")),
                "arguments_markers": file_path_markers,
            },
            {
                "kind": "tool-call",
                "marker": "Synthetic list tool call",
                "tool": "search_files",
                "call_id": "call_synthetic_search_files",
                "arguments": json.dumps(
                    {"pattern": "*", "target": "files", "path": str(sandbox)}, separators=(",", ":")
                ),
                "arguments_markers": search_files_markers,
            },
            {"kind": "completion", "text": COMPLETION_TEXT},
        ],
        "side_effects": {"files": {str(sample): "synthetic file content"}},
        "anchors": ("synthetic file content", "sample.txt"),
        "screen_markers": ["write_file", "read_file", "search_files", COMPLETION_TEXT],
    }


def scenario_s3(sandbox: Path) -> dict[str, Any]:
    return {
        "id": "s3-clarify",
        "observation_id": "OBS-0119",
        "prompt": "single Hermes clarify execution prompt",
        "assistant_marker": "Synthetic clarify tool call",
        "script": [
            {
                "kind": "tool-call",
                "marker": "Synthetic clarify tool call",
                "tool": "clarify",
                "call_id": "call_synthetic_clarify",
                "arguments": json.dumps(
                    {"question": CLARIFY_QUESTION, "choices": list(CLARIFY_CHOICES)},
                    separators=(",", ":"),
                ),
                "arguments_markers": clarify_markers,
            },
            {"kind": "completion", "text": COMPLETION_TEXT},
        ],
        "side_effects": {"empty_sandbox": True},
        "anchors": CLARIFY_CHOICES,
        "screen_markers": ["clarification", CLARIFY_CHOICES[0], CLARIFY_CHOICES[1], COMPLETION_TEXT],
    }


def scenario_s4(sandbox: Path) -> dict[str, Any]:
    hop = sandbox / "hopdir" / "hop.txt"
    command = f"mkdir -p {sandbox / 'hopdir'} && echo hop-one > {hop}"
    return {
        "id": "s4-multi-hop",
        "observation_id": "OBS-0120",
        "prompt": "single Hermes multi-hop tool execution prompt",
        "assistant_marker": "Synthetic multi-hop tool call",
        "script": [
            {
                "kind": "tool-call",
                "marker": "Synthetic multi-hop terminal call",
                "tool": "terminal",
                "call_id": "call_synthetic_terminal",
                "arguments": json.dumps({"command": command}, separators=(",", ":")),
                "arguments_markers": sandbox_command_markers("hop.txt"),
            },
            {
                "kind": "tool-call",
                "marker": "Synthetic multi-hop read call",
                "tool": "read_file",
                "call_id": "call_synthetic_read_file",
                "arguments": json.dumps({"path": str(hop)}, separators=(",", ":")),
                "arguments_markers": file_path_markers,
            },
            {"kind": "completion", "text": COMPLETION_TEXT},
        ],
        "side_effects": {"files": {str(hop): "hop-one"}},
        "anchors": ("hop-one", "hop.txt"),
        "screen_markers": ["terminal", "read_file", COMPLETION_TEXT],
    }


SCENARIOS = {
    "s1-terminal": scenario_s1,
    "s2-file-tools": scenario_s2,
    "s3-clarify": scenario_s3,
    "s4-multi-hop": scenario_s4,
}

OBSERVATION_IDS = {
    "s1-terminal": "OBS-0117",
    "s2-file-tools": "OBS-0118",
    "s3-clarify": "OBS-0119",
    "s4-multi-hop": "OBS-0120",
}


def tool_result_shape(content: str, anchors: tuple[str, ...]) -> dict[str, Any]:
    stripped = content.lstrip()
    parsed_json: Any = None
    try:
        parsed_json = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        parsed_json = None
    return {
        "recorded": True,
        "content_kind": "string",
        "length": len(content),
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
        "empty": content == "",
        "starts_with_brace": stripped.startswith("{"),
        "json_parseable": parsed_json is not None,
        "json_top_level_keys": sorted(parsed_json) if isinstance(parsed_json, dict) else [],
        "contains_anchors": [anchor for anchor in anchors if anchor in content],
    }


class ToolExecutionServer(ThreadingHTTPServer):
    """Loopback recorder answering each streaming chat request from a scenario script."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, script: list[dict[str, Any]]) -> None:
        self.script = script
        self.lock = threading.Lock()
        self.http_requests: list[dict[str, Any]] = []
        self.chat_requests: list[dict[str, Any]] = []
        self.raw_bodies: list[dict[str, Any]] = []
        self.stream_events: list[dict[str, Any]] = []
        self.streaming_requests = 0
        self.responses_served = 0
        self.completion_served = threading.Event()
        self.first_stream_served = threading.Event()
        self.response: dict[str, Any] = {"tool_calls_served": 0, "auxiliary_responses": 0}
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

            def write_stream(self, chunks: list[dict[str, Any]]) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                for chunk in chunks:
                    with owner.lock:
                        owner.stream_events.append(
                            {"length": len(sse_payload(chunk)), "sha256": digest(chunk)}
                        )
                    self.wfile.write(sse_payload(chunk))
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

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
                with owner.lock:
                    owner.http_requests.append(
                        {
                            "method": "POST",
                            "path": self.path,
                            "authorization_present": self.headers.get("Authorization") is not None,
                        }
                    )
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
                    # Keep the raw parsed body only in memory so the real Hermes
                    # tool-result content can be reduced to shape (length, digest,
                    # structural anchors) without ever persisting the content.
                    owner.raw_bodies.append(payload)

                if payload.get("stream") is not True:
                    self.write_json(
                        {
                            "model": "palette-model",
                            "choices": [
                                {
                                    "index": 0,
                                    "message": {"role": "assistant", "content": AUXILIARY_TEXT},
                                    "finish_reason": "stop",
                                }
                            ],
                        }
                    )
                    with owner.lock:
                        owner.response["auxiliary_responses"] += 1
                    return

                with owner.lock:
                    owner.streaming_requests += 1
                    step_index = owner.streaming_requests - 1
                    step = owner.script[step_index] if step_index < len(owner.script) else None
                if step is None:
                    self.write_json({"error": {"message": "synthetic script exhausted"}}, 500)
                    return

                if step["kind"] == "tool-call":
                    chunks = tool_call_chunks(
                        step["marker"], step["tool"], step["call_id"], step["arguments"]
                    )
                else:
                    chunks = completion_chunks(step["text"])
                try:
                    self.write_stream(chunks)
                except OSError:
                    with owner.lock:
                        owner.response.setdefault("connection_error", "provider stream closed")
                    return
                with owner.lock:
                    owner.responses_served += 1
                    if step["kind"] == "tool-call":
                        owner.response["tool_calls_served"] += 1
                    else:
                        owner.response["completion_served_text"] = step["text"]
                        owner.completion_served.set()
                    if owner.responses_served == 1:
                        owner.first_stream_served.set()

        return Handler

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "http_requests": list(self.http_requests),
                "chat_requests": list(self.chat_requests),
                "raw_bodies": list(self.raw_bodies),
                "stream_events": list(self.stream_events),
                "streaming_requests": self.streaming_requests,
                "responses_served": self.responses_served,
                "response": dict(self.response),
            }


def wait_for_count(server: ToolExecutionServer, case: str, step: str, count: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.snapshot()["streaming_requests"] >= count:
            return
        time.sleep(0.05)
    raise ProbeFailure(
        case,
        step,
        f"timed out after {timeout:.1f}s waiting for streaming request {count}",
        {"streaming_requests": server.snapshot()["streaming_requests"]},
    )


def verify_follow_up_shape(server: ToolExecutionServer, case: str, request_index: int) -> dict[str, Any]:
    snapshot = server.snapshot()
    if request_index >= len(snapshot["chat_requests"]):
        raise ProbeFailure(
            case,
            "follow-up",
            f"chat request {request_index + 1} was not recorded",
            {"chat_requests": snapshot["chat_requests"]},
        )
    request = snapshot["chat_requests"][request_index]["request"]
    if request["request_kind"] != "streaming-chat":
        raise ProbeFailure(
            case,
            "follow-up",
            f"chat request {request_index + 1} was not streaming",
            {"request": request},
        )
    roles = [message["role"] for message in request["messages"]]
    if "tool" not in roles:
        raise ProbeFailure(
            case,
            "follow-up",
            f"chat request {request_index + 1} carried no tool-role message",
            {"request": request},
        )
    tool_messages = [
        message for message in request["messages"]
        if message["role"] == "tool" and message["content_kind"] == "string"
    ]
    if not tool_messages:
        raise ProbeFailure(
            case,
            "follow-up",
            f"chat request {request_index + 1} carried no string tool-result message",
            {"request": request},
        )
    return {
        "sequence": request_index + 1,
        "request_kind": request["request_kind"],
        "model": request["model"],
        "message_count": request["message_count"],
        "message_roles": roles,
        "message_content_kinds": [message["content_kind"] for message in request["messages"]],
        "tool_calls_in_history": [message["tool_calls_present"] for message in request["messages"]],
        "tool_call_id_markers": [message["tool_call_id_marker"] for message in request["messages"]],
        "tool_result_messages": len(tool_messages),
    }


def verify_side_effects(case: str, scenario: dict[str, Any], sandbox: Path) -> dict[str, Any]:
    expected_files = scenario["side_effects"].get("files", {})
    observed: dict[str, Any] = {"files": [], "match": True}
    for path, expected_content in expected_files.items():
        target = Path(path)
        exists = target.is_file()
        content = ""
        if exists:
            content = target.read_text(encoding="utf-8", errors="replace")
        content_matches = exists and (
            content == expected_content or content == expected_content + "\n"
        )
        observed["files"].append(
            {
                "basename": target.name,
                "exists": exists,
                "content_matches_expected": content_matches,
                "content_length": len(content) if exists else 0,
                "content_sha256": hashlib.sha256(content.encode()).hexdigest() if exists else None,
            }
        )
        if not (exists and content_matches):
            observed["match"] = False
    if scenario["side_effects"].get("empty_sandbox"):
        entries = [entry.name for entry in sandbox.iterdir()]
        observed["empty_sandbox"] = {"empty": not entries, "entries": entries}
        if entries:
            observed["match"] = False
    if not observed["match"]:
        raise ProbeFailure(
            case,
            "sandbox-side-effect",
            "the reference did not produce the expected probe-owned sandbox side effect",
            {"observed": observed},
        )
    return observed


def tool_result_shapes(server: ToolExecutionServer, anchors: tuple[str, ...]) -> list[dict[str, Any]]:
    shapes: list[dict[str, Any]] = []
    for body in server.snapshot()["raw_bodies"]:
        # Later follow-up bodies carry the full message history, so the
        # NEWEST tool result is the last tool-role message in each body.
        newest: str | None = None
        for message in body.get("messages", []):
            if message.get("role") == "tool" and isinstance(message.get("content"), str):
                newest = message["content"]
        if newest is not None:
            shapes.append(tool_result_shape(newest, anchors))
    return shapes


def run_case(reference: Path, timeout: float, observation_window: float, scenario_id: str) -> dict[str, Any]:
    case = scenario_id
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-toolexec-"))
    home = root / "home"
    home.mkdir()
    sandbox = root / "sandbox"
    sandbox.mkdir()
    pid = fd = -1
    buffer = b""
    server: ToolExecutionServer | None = None
    try:
        scenario = SCENARIOS[case](sandbox)
        metadata = scenario_metadata(case)
        scenario["unknowns"] = metadata["unknowns"]
        scenario["side_effect_boundary"] = metadata["side_effect_boundary"]
        server = ToolExecutionServer(scenario["script"])
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        prompt = scenario["prompt"]
        sensitive = (
            prompt,
            scenario["assistant_marker"],
            *[step.get("arguments", "") for step in scenario["script"] if step["kind"] == "tool-call"],
        )
        pid, fd, buffer = start_ready(reference, home, case, timeout)
        write_bytes(fd, prompt.encode())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            buffer = drain(pid, fd, buffer, 0.1)
            if contains_marker(buffer, prompt):
                break
        else:
            raise ProbeFailure(
                case,
                "prompt",
                f"timed out after {timeout:.1f}s waiting for the composer prompt",
                {"screen_tail": safe_screen_tail(buffer, sensitive)},
            )
        write_bytes(fd, b"\r")
        if not server.first_stream_served.wait(timeout):
            raise ProbeFailure(
                case,
                "tool-call-stream",
                f"timed out after {timeout:.1f}s waiting for the first tool-call stream",
                {
                    "chat_requests": server.snapshot()["chat_requests"],
                    "screen_tail": safe_screen_tail(buffer, sensitive),
                },
            )

        interaction_steps: list[dict[str, Any]] = []
        if case == "s3-clarify":
            surface_deadline = time.monotonic() + SURFACE_WAIT_TIMEOUT
            while time.monotonic() < surface_deadline:
                buffer = drain(pid, fd, buffer, 0.1)
                frame = rendered_text(buffer)
                if "clarification" in frame and CLARIFY_CHOICES[0] in frame:
                    break
            else:
                raise ProbeFailure(
                    case,
                    "question-surface",
                    f"timed out after {SURFACE_WAIT_TIMEOUT:.1f}s waiting for the clarify question surface",
                    {"screen_tail": safe_screen_tail(buffer, sensitive)},
                )
            for label, input_bytes in (
                ("down", ARROW_DOWN),
                ("up", ARROW_UP),
                ("enter-choice-one", ENTER),
            ):
                write_bytes(fd, input_bytes)
                time.sleep(0.05)
                buffer = drain(pid, fd, buffer, STEP_WINDOW_SECONDS)
                frame = rendered_text(buffer)
                interaction_steps.append(
                    {
                        "input": label,
                        "bytes_hex": input_bytes.hex(" "),
                        "observation_window_ms": round(STEP_WINDOW_SECONDS * 1000),
                        "markers": {
                            "question_marker": "clarification" in frame,
                            "choice_one_marker": CLARIFY_CHOICES[0] in frame,
                            "choice_two_marker": CLARIFY_CHOICES[1] in frame,
                            "answer_marker": COMPLETION_TEXT in frame,
                        },
                        "screen_frame_tail": "<omitted-successfully>",
                    }
                )

        follow_up_shapes: list[dict[str, Any]] = []
        script_length = len(scenario["script"])
        for index in range(1, script_length):
            wait_for_count(server, case, f"follow-up-{index}", index + 1, timeout)
            follow_up_shapes.append(verify_follow_up_shape(server, case, index))
        if not server.completion_served.wait(timeout):
            raise ProbeFailure(
                case,
                "completion",
                f"timed out after {timeout:.1f}s waiting for the plain completion response",
                {
                    "chat_requests": server.snapshot()["chat_requests"],
                    "screen_tail": safe_screen_tail(buffer, sensitive),
                },
            )

        buffer = drain(pid, fd, buffer, observation_window)
        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)
        after_cleanup = server.snapshot()

        chat_requests = after_cleanup["chat_requests"]
        if not chat_requests:
            raise ProbeFailure(case, "request", "no streaming chat request was recorded")
        first = chat_requests[0]
        if first["request"]["request_kind"] != "streaming-chat":
            raise ProbeFailure(case, "request-kind", "the first captured chat request was not streaming")
        tool_names = first["request"]["tools"]["names"]
        if not first["request"]["tools"]["present"] or first["request"]["tools"]["count"] != 31:
            raise ProbeFailure(
                case,
                "tool-registration",
                "the anchored 31-tool inventory was not advertised in the first request",
                {"tools": first["request"]["tools"]},
            )
        scripted_tools = [step["tool"] for step in scenario["script"] if step["kind"] == "tool-call"]
        for tool in scripted_tools:
            if tool not in tool_names:
                raise ProbeFailure(
                    case,
                    "tool-registration",
                    f"{tool} was not advertised in the first request",
                    {"tools": first["request"]["tools"]},
                )
        if after_cleanup["streaming_requests"] != script_length:
            raise ProbeFailure(
                case,
                "request-count",
                f"expected {script_length} streaming chat requests, observed {after_cleanup['streaming_requests']}",
                {"streaming_requests": after_cleanup["streaming_requests"]},
            )
        if after_cleanup["responses_served"] != script_length:
            raise ProbeFailure(
                case,
                "response-count",
                f"expected {script_length} streamed responses, observed {after_cleanup['responses_served']}",
                {"responses_served": after_cleanup["responses_served"]},
            )
        if after_cleanup["response"].get("completion_served_text") != COMPLETION_TEXT:
            raise ProbeFailure(case, "completion", "the final streamed response was not the plain completion")

        side_effects = verify_side_effects(case, scenario, sandbox)
        anchors = scenario["anchors"]
        tool_results = tool_result_shapes(server, anchors)

        tool_calls: list[dict[str, Any]] = []
        for step in scenario["script"]:
            if step["kind"] != "tool-call":
                continue
            tool_calls.append(
                {
                    "name": step["tool"],
                    "call_id_marker": (
                        "synthetic-call-id" if step["call_id"] in SYNTHETIC_CALL_IDS else "other-id"
                    ),
                    "arguments": tool_arguments_shape(step["arguments"], step["arguments_markers"]),
                }
            )

        visible_markers = {
            marker: contains_marker(buffer, marker) for marker in scenario["screen_markers"]
        }
        visible_markers["processing_marker"] = contains_marker(buffer, "Processing")
        visible_markers["ready_marker"] = contains_marker(buffer, "ready")

        follow_up_requests = [
            {
                "sequence": index + 2,
                "request_kind": request["request"]["request_kind"],
                "model": request["request"]["model"],
                "message_count": request["request"]["message_count"],
                "message_roles": [message["role"] for message in request["request"]["messages"]],
                "message_content_kinds": [
                    message["content_kind"] for message in request["request"]["messages"]
                ],
                "tool_calls_in_history": [
                    message["tool_calls_present"] for message in request["request"]["messages"]
                ],
            }
            for index, request in enumerate(chat_requests[1:])
        ]

        return {
            "id": case,
            "status": "passed",
            "observation_id": scenario["observation_id"],
            "input": [
                {"kind": "text", "value": "<synthetic prompt>"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {"kind": "wait", "value": "scripted tool-call stream served"},
                *(
                    [{"kind": "wait", "value": "clarify question surface rendered"}]
                    + [
                        {"kind": "key", "value": "ArrowDown", "bytes_hex": ARROW_DOWN.hex(" ")},
                        {"kind": "wait", "value": "bounded navigation window"},
                        {"kind": "key", "value": "ArrowUp", "bytes_hex": ARROW_UP.hex(" ")},
                        {"kind": "wait", "value": "bounded navigation window"},
                        {"kind": "key", "value": "Enter (select first choice)", "bytes_hex": "0d"},
                    ]
                    if case == "s3-clarify"
                    else []
                ),
                *[
                    {"kind": "wait", "value": f"tool result {index} followed up"}
                    for index in range(1, script_length)
                ],
                {"kind": "wait", "value": "plain completion rendered"},
            ],
            "provider_request": {
                "path": first["path"],
                "authorization_present": first["authorization_present"],
                "request": first["request"],
            },
            "tool_calls": tool_calls,
            "follow_up_requests": follow_up_requests,
            "follow_up_shapes": follow_up_shapes,
            "tool_results": tool_results,
            "interaction_steps": interaction_steps,
            "sandbox_side_effects": side_effects,
            "visible_markers": visible_markers,
            "visible_screen_tail": "<omitted-successfully>",
            "request_counts": {
                "chat_requests": len(chat_requests),
                "streaming_requests": after_cleanup["streaming_requests"],
                "subsequent_chat_requests": max(0, len(chat_requests) - 1),
                "tool_result_requests": len(tool_results),
                "loopback_http_requests": len(after_cleanup["http_requests"]),
                "auxiliary_responses": after_cleanup["response"].get("auxiliary_responses", 0),
            },
            "termination": {
                "completion_text": COMPLETION_TEXT,
                "completion_served": True,
                "clean_exit": exited,
                "observation_window_seconds": observation_window,
            },
            "side_effect_boundary": {
                "provider_endpoint": "127.0.0.1 loopback owned by probe",
                "external_network": "none observed; all recorded HTTP traffic stayed on the synthetic loopback",
                "credentials": "none; only a synthetic key was placed in the throwaway config and auth values were reduced to presence booleans",
                "oauth": "not entered",
                "browser": "not started",
                "filesystem": "tool side effects were confined to the probe-owned sandbox directory under a throwaway temp root; the sandbox was removed after the probe",
                "tool_action": scenario["side_effect_boundary"],
            },
            "unknowns": scenario["unknowns"],
        }
    finally:
        if pid != -1:
            stop(pid, fd)
        if server is not None:
            server.shutdown()
            server.server_close()
        shutil.rmtree(root, ignore_errors=True)


def scenario_metadata(scenario_id: str) -> dict[str, Any]:
    shared = {
        "s1-terminal": {
            "surface": "hermes-tui-terminal-tool-execution",
            "capture": "fresh synthetic-home Hermes TUI process with one ordinary prompt; the loopback provider requests one terminal tool call writing into a probe-owned temp dir; the follow-up tool result is answered with a plain completion; bounded post-completion observation window",
            "normalization_extra": [
                "The executed command is a synthetic probe-owned command whose only side effect writes into the probe sandbox; the command's structure is recorded as markers (contains mkdir/echo/redirection/chaining) and the arguments as length/digest, never the raw command text or sandbox path.",
                "The real Hermes terminal tool-result content is recorded only as normalized shape (content kind, length, digest, JSON top-level keys, boolean anchors); the content itself is never persisted.",
            ],
            "unknowns": [
                "Approval UI, retry, failure-path, and timing semantics for the terminal tool remain unknown beyond this single fresh observation; the observed command matched no dangerous pattern and executed without an approval prompt.",
                "Whether the terminal tool result content (output text, exit code, cwd, duration fields) is stable across reference restarts remains bounded by this single observation.",
                "The purpose of the auxiliary non-stream system/user request seen in OBS-0108/0109/0114/0116/0119 remains unclassified and is not a Hades requirement.",
            ],
            "side_effect_boundary": "one terminal command whose only side effect writes the probe-owned sandbox file (mkdir -p <sandbox>/out && echo synthetic > <sandbox>/out/out.txt)",
        },
        "s2-file-tools": {
            "surface": "hermes-tui-file-tool-execution",
            "capture": "fresh synthetic-home Hermes TUI process with one ordinary prompt; the loopback provider requests write_file, then read_file, then search_files (list) against the probe-owned temp dir, then a plain completion; bounded post-completion observation window",
            "normalization_extra": [
                "All file tool paths are probe-owned sandbox paths; arguments are recorded as length/digest/structural markers (top-level keys, value kinds, basename anchors), never the raw paths or content.",
                "The real Hermes file tool-result contents are recorded only as normalized shape (content kind, length, digest, JSON top-level keys, boolean anchors); the contents themselves are never persisted.",
            ],
            "unknowns": [
                "Approval UI, retry, failure-path, and timing semantics for the file tools remain unknown beyond this single fresh observation.",
                "Whether file tool result content (line-numbered reads, match listings, error text) is stable across reference restarts remains bounded by this single observation.",
                "The purpose of the auxiliary non-stream system/user request seen in OBS-0108/0109/0114/0116/0119 remains unclassified and is not a Hades requirement.",
            ],
            "side_effect_boundary": "three file tool hops (write_file, read_file, search_files) confined to the probe-owned sandbox directory",
        },
        "s3-clarify": {
            "surface": "hermes-tui-clarify-tool-execution",
            "capture": "fresh synthetic-home Hermes TUI process with one ordinary prompt; the loopback provider requests one clarify tool call; arrow navigation and one Enter selection on the rendered question surface (OBS-0116 boundary); the follow-up tool result is answered with a plain completion; bounded post-completion observation window",
            "normalization_extra": [
                "clarify is interactive-only; exercising its TUI question surface with arrow navigation and one Enter selection involves no external side effect.",
                "The real Hermes clarify tool-result content is recorded only as normalized shape (content kind, length, digest, JSON top-level keys, boolean anchors); the content itself is never persisted.",
            ],
            "unknowns": [
                "Whether the observed question-surface cursor semantics and the 158-byte tool-result shape are stable across reference restarts remains bounded by this single fresh observation; the exact completion/approval/failure semantics remain unknown.",
                "Provider-specific retries, malformed or truncated argument handling, multiple calls per turn, approval policy, and post-handoff failure behavior remain unknown.",
                "The purpose of the auxiliary non-stream system/user request seen in OBS-0108/0109/0114/0116/0119 remains unclassified and is not a Hades requirement.",
            ],
            "side_effect_boundary": "clarify is interactive-only; only arrow navigation and one Enter selection on the TUI question surface were exercised, with no external side effect",
        },
        "s4-multi-hop": {
            "surface": "hermes-tui-multi-hop-tool-execution",
            "capture": "fresh synthetic-home Hermes TUI process with one ordinary prompt; the loopback provider requests a terminal tool call, answers the resulting tool message with a read_file tool call, then a plain completion — two hops then termination; bounded post-completion observation window",
            "normalization_extra": [
                "The executed commands are synthetic probe-owned commands whose only side effects write into the probe sandbox; command structure is recorded as markers and arguments as length/digest, never the raw command text or sandbox path.",
                "The real Hermes tool-result contents (terminal output, read content) are recorded only as normalized shape (content kind, length, digest, JSON top-level keys, boolean anchors); the contents themselves are never persisted.",
            ],
            "unknowns": [
                "Approval UI, retry, failure-path, and termination semantics beyond the observed plain-completion termination remain unknown; the loop terminated when the follow-up stream carried no tool calls.",
                "Whether the multi-hop request sequence and tool-result contents are stable across reference restarts remains bounded by this single observation.",
                "The purpose of the auxiliary non-stream system/user request seen in OBS-0108/0109/0114/0116/0119 remains unclassified and is not a Hades requirement.",
            ],
            "side_effect_boundary": "two tool hops (terminal, then read_file) confined to the probe-owned sandbox directory",
        },
    }
    return shared[scenario_id]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--observation-window", type=float, default=OBSERVATION_WINDOW)
    args = parser.parse_args()
    reference = args.reference.resolve()
    metadata = scenario_metadata(args.scenario)
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": OBSERVATION_IDS[args.scenario],
        "scenario": args.scenario,
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": metadata["capture"],
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, prompt text, assistant text, tool arguments, credentials, authorization values, session identifiers, timestamps, and redraw bytes are omitted or represented by stable markers or digests.",
            "The provider endpoint is a deterministic 127.0.0.1 fixture owned by this probe; no external network, OAuth flow, browser, tool response beyond the scripted loopback, or user credential is used.",
            "The response records OpenAI-compatible tool-call delta shape and argument length/digest without copying argument payloads; the [DONE] marker completes each stream so tool execution proceeds.",
            "Tool side effects are confined to the probe-owned sandbox directory under a throwaway temp root; the sandbox and HOME/HERMES_HOME are removed after the probe.",
            *metadata["normalization_extra"],
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        if args.observation_window < 0 or args.observation_window > 15:
            raise ProbeFailure("reference", "arguments", "observation window must be between 0 and 15 seconds")
        report["cases"].append(run_case(reference, args.timeout, args.observation_window, args.scenario))
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
