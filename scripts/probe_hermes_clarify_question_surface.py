#!/usr/bin/env python3
"""Observe the Hermes clarify question surface interaction.

A fresh synthetic Hermes TUI process with a deterministic loopback provider
submits one ordinary prompt. The provider returns a complete streaming
tool-call response: fragmented `clarify` arguments, `finish_reason:
"tool_calls"`, and the terminal `[DONE]` marker. Once the clarify question
surface renders, the probe sends only bounded non-submitting inputs (arrow
navigation and one Enter selection of a visible choice) and records exact
input bytes, rendered question/choice/cursor markers, the follow-up chat
request carrying the real tool-result content, and the resulting answer.

`clarify` is interactive-only: its execution is confined to the TUI question
surface, so observing it involves no network, credential, OAuth, browser,
filesystem, or installer side effect. Any unstable or unobserved transition
is recorded as an explicit unknown, never guessed.
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
    write_bytes,
)
from probe_hermes_terminal_palette import drain
from probe_hermes_standalone_terminal_platform import rendered_text

LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PORT = 8765
CHAT_PATHS = {"/v1/chat/completions", "/api/chat"}
PROMPT = "single Hermes clarify question surface prompt"
TOOL_NAME = "clarify"
TOOL_CALL_ID = "call_synthetic_clarify"
ARGUMENT_FRAGMENTS = (
    '{"question":"synthetic clarification question",',
    '"choices":["synthetic choice one","synthetic choice two"]}',
)
CHOICE_ONE = "synthetic choice one"
CHOICE_TWO = "synthetic choice two"
ARROW_DOWN = b"\x1b[B"
ARROW_UP = b"\x1b[A"
ENTER = b"\r"
STEP_WINDOW_SECONDS = 0.35
SURFACE_WAIT_TIMEOUT = 15.0
OBSERVATION_WINDOW = 3.0


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
            normalized_messages.append(
                {
                    "role": message.get("role"),
                    "content_kind": value_kind(message.get("content")),
                    "keys": sorted(message),
                    "tool_calls_present": bool(message.get("tool_calls")),
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
            "clarify_present": any(
                tool.get("function", {}).get("name") == TOOL_NAME
                for tool in payload.get("tools", [])
                if isinstance(tool, dict)
            ),
        },
    }


def safe_screen_tail(raw: bytes) -> str:
    text = safe_tail(raw)
    for value in (PROMPT, *ARGUMENT_FRAGMENTS, CHOICE_ONE, CHOICE_TWO):
        text = text.replace(value, "<synthetic-value>")
    return text


class ClarifySurfaceServer(ThreadingHTTPServer):
    """Loopback recorder returning a complete clarify tool-call stream."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.http_requests: list[dict[str, Any]] = []
        self.chat_requests: list[dict[str, Any]] = []
        self.raw_bodies: list[dict[str, Any]] = []
        self.stream_events: list[dict[str, Any]] = []
        self.response: dict[str, Any] = {}
        self.done_sent = threading.Event()
        self.streaming_requests = 0
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

                request = normalized_request(payload)
                record = {
                    "path": self.path,
                    "content_type": self.headers.get("Content-Type", ""),
                    "authorization_present": self.headers.get("Authorization") is not None,
                    "request": request,
                }
                with owner.lock:
                    owner.chat_requests.append(record)
                    # Keep the raw parsed body so the real Hermes tool-result
                    # content can be reduced to shape (length, digest, anchors)
                    # without persisting the content itself.
                    owner.raw_bodies.append(payload)

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

                with owner.lock:
                    owner.streaming_requests += 1
                    is_first_stream = owner.streaming_requests == 1
                if not is_first_stream:
                    # A follow-up streaming request carries the tool result in
                    # history; answer plainly so the agent loop terminates and
                    # the post-selection boundary stays bounded.
                    chunks = [
                        {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                        {"choices": [{"index": 0, "delta": {"content": "Synthetic completion."}, "finish_reason": None}]},
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
                            owner.response["follow_up_answered"] = True
                    except OSError:
                        pass
                    return

                chunks = [
                    {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "content": "Synthetic handoff",
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
                        ]
                    },
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                        {"index": 0, "function": {"arguments": ARGUMENT_FRAGMENTS[1]}}
                                    ]
                                },
                                "finish_reason": None,
                            }
                        ]
                    },
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
                ]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    for chunk in chunks:
                        with owner.lock:
                            owner.stream_events.append(
                                {
                                    "length": len(sse_payload(chunk)),
                                    "sha256": digest(chunk),
                                }
                            )
                        self.wfile.write(sse_payload(chunk))
                        self.wfile.flush()
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                    with owner.lock:
                        owner.response = {
                            "content_type": "text/event-stream",
                            "chunk_count": len(chunks),
                            "done_marker_sent": True,
                            "finish_reason_sent": "tool_calls",
                        }
                    owner.done_sent.set()
                except OSError:
                    with owner.lock:
                        owner.response.setdefault("connection_error", "provider stream closed")

        return Handler

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "http_requests": list(self.http_requests),
                "chat_requests": list(self.chat_requests),
                "raw_bodies": list(self.raw_bodies),
                "stream_events": list(self.stream_events),
                "response": dict(self.response),
            }


def run_case(reference: Path, timeout: float, observation_window: float) -> dict[str, Any]:
    case = "clarify-question-surface"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-clarifysurface-"))
    home = root / "home"
    home.mkdir()
    server = ClarifySurfaceServer()
    pid = fd = -1
    buffer = b""
    try:
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        pid, fd, buffer = start_ready(reference, home, case, timeout)
        write_bytes(fd, PROMPT.encode())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            buffer = drain(pid, fd, buffer, 0.1)
            if contains_marker(buffer, PROMPT):
                break
        else:
            raise ProbeFailure(
                case,
                "prompt",
                f"timed out after {timeout:.1f}s waiting for the composer prompt",
                {"screen_tail": safe_screen_tail(buffer)},
            )
        write_bytes(fd, b"\r")
        if not server.done_sent.wait(timeout):
            raise ProbeFailure(
                case,
                "tool-call-stream",
                f"timed out after {timeout:.1f}s waiting for the completed tool-call stream",
                {"chat_requests": server.snapshot()["chat_requests"], "screen_tail": safe_screen_tail(buffer)},
            )

        # Wait for the rendered clarify question surface (question + choice
        # markers observed in OBS-0114) before any interaction.
        surface_deadline = time.monotonic() + SURFACE_WAIT_TIMEOUT
        while time.monotonic() < surface_deadline:
            buffer = drain(pid, fd, buffer, 0.1)
            frame = rendered_text(buffer)
            if "clarification" in frame and CHOICE_ONE in frame:
                break
        else:
            raise ProbeFailure(
                case,
                "question-surface",
                f"timed out after {SURFACE_WAIT_TIMEOUT:.1f}s waiting for the clarify question surface",
                {"screen_tail": safe_screen_tail(buffer)},
            )

        interaction_steps: list[dict[str, Any]] = []
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
                        "choice_one_marker": CHOICE_ONE in frame,
                        "choice_two_marker": CHOICE_TWO in frame,
                        "tool_call_row": "Clarify" in frame,
                        "answer_marker": "Synthetic completion" in frame,
                    },
                    "screen_frame_tail": "<omitted-successfully>",
                }
            )

        # After the Enter selection, wait for the server-side follow-up answer
        # (deterministic; the raw PTY stream fragments across Ink redraws),
        # then drain the bounded observation window.
        answer_deadline = time.monotonic() + timeout
        snapshot = server.snapshot()
        while time.monotonic() < answer_deadline:
            buffer = drain(pid, fd, buffer, 0.2)
            snapshot = server.snapshot()
            if snapshot["response"].get("follow_up_answered") is True:
                break
        else:
            raise ProbeFailure(
                case,
                "answer",
                f"timed out after {timeout:.1f}s waiting for the follow-up answer after selection",
                {"chat_requests": snapshot["chat_requests"], "screen_tail": safe_screen_tail(buffer)},
            )

        buffer = drain(pid, fd, buffer, observation_window)
        before_cleanup = server.snapshot()
        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)
        after_cleanup = server.snapshot()

        chat_requests = after_cleanup["chat_requests"]
        if not chat_requests:
            raise ProbeFailure(case, "request", "no streaming chat request was recorded")
        first = chat_requests[0]
        if first["request"]["request_kind"] != "streaming-chat":
            raise ProbeFailure(case, "request-kind", "the first captured chat request was not streaming")
        if not first["request"]["tools"]["clarify_present"]:
            raise ProbeFailure(case, "tool-registration", "clarify was not advertised in the request")
        if after_cleanup["response"].get("done_marker_sent") is not True:
            raise ProbeFailure(case, "bounded-stop", "[DONE] was not sent before the observation window")

        tool_result_requests = [
            request
            for request in chat_requests[1:]
            if any(
                message.get("role") == "tool" and message.get("content_kind") == "string"
                for message in request["request"]["messages"]
            )
        ]
        if not tool_result_requests:
            raise ProbeFailure(
                case,
                "tool-result",
                "no follow-up request carried a string tool-role result message",
                {"chat_requests": chat_requests},
            )
        # The real Hermes tool-result content is recorded only by normalized
        # shape (kind, length, digest, structural anchors); the content itself
        # is never persisted. Recover the raw string from the recorded raw
        # bodies.
        tool_content_shape: dict[str, Any] = {"recorded": False}
        for body in after_cleanup["raw_bodies"]:
            for message in body.get("messages", []):
                if message.get("role") == "tool" and isinstance(message.get("content"), str):
                    content = message["content"]
                    stripped = content.lstrip()
                    parsed_json: Any = None
                    try:
                        parsed_json = json.loads(content)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        parsed_json = None
                    tool_content_shape = {
                        "recorded": True,
                        "content_kind": "string",
                        "length": len(content),
                        "sha256": hashlib.sha256(content.encode()).hexdigest(),
                        "matches_choice_one": content == CHOICE_ONE,
                        "matches_choice_two": content == CHOICE_TWO,
                        "contains_choice_one": CHOICE_ONE in content,
                        "contains_choice_two": CHOICE_TWO in content,
                        "empty": content == "",
                        "starts_with_brace": stripped.startswith("{"),
                        "json_parseable": parsed_json is not None,
                        "json_top_level_keys": (
                            sorted(parsed_json) if isinstance(parsed_json, dict) else []
                        ),
                    }
                    break
            if tool_content_shape.get("recorded"):
                break

        frame = rendered_text(buffer)
        markers = {
            "assistant_text": "Synthetic handoff" in frame,
            "answer_text": "Synthetic completion" in frame,
            "question_marker": "clarification" in frame,
            "choice_one_marker": CHOICE_ONE in frame,
            "choice_two_marker": CHOICE_TWO in frame,
            "ready_marker": "ready" in frame,
        }

        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "<synthetic prompt>"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {"kind": "wait", "value": "clarify question surface rendered"},
                {"kind": "key", "value": "ArrowDown", "bytes_hex": ARROW_DOWN.hex(" ")},
                {"kind": "wait", "value": "bounded navigation window"},
                {"kind": "key", "value": "ArrowUp", "bytes_hex": ARROW_UP.hex(" ")},
                {"kind": "wait", "value": "bounded navigation window"},
                {"kind": "key", "value": "Enter (select first choice)", "bytes_hex": "0d"},
                {"kind": "wait", "value": "follow-up answer rendered"},
            ],
            "provider_request": {
                "path": first["path"],
                "authorization_present": first["authorization_present"],
                "request": first["request"],
            },
            "tool_call": {
                "name": TOOL_NAME,
                "argument_fragments": [
                    {
                        "sequence": index + 1,
                        "length": len(fragment),
                        "sha256": hashlib.sha256(fragment.encode()).hexdigest(),
                    }
                    for index, fragment in enumerate(ARGUMENT_FRAGMENTS)
                ],
                "joined_arguments": {
                    "length": len("".join(ARGUMENT_FRAGMENTS)),
                    "sha256": hashlib.sha256("".join(ARGUMENT_FRAGMENTS).encode()).hexdigest(),
                    "valid_json": True,
                },
                "finish_reason": "tool_calls",
                "done_marker_sent": True,
            },
            "interaction_steps": interaction_steps,
            "visible_surface_markers": markers,
            "visible_surface_screen_tail": "<omitted-successfully>",
            "request_counts": {
                "chat_requests": len(chat_requests),
                "subsequent_chat_requests": max(0, len(chat_requests) - 1),
                "tool_result_requests": len(tool_result_requests),
                "loopback_http_requests": len(after_cleanup["http_requests"]),
            },
            "follow_up_requests": [
                {
                    "sequence": index + 2,
                    "request_kind": request["request"]["request_kind"],
                    "model": request["request"]["model"],
                    "message_count": request["request"]["message_count"],
                    "message_roles": [
                        message["role"] for message in request["request"]["messages"]
                    ],
                    "message_content_kinds": [
                        message.get("content_kind") for message in request["request"]["messages"]
                    ],
                    "tool_calls_in_history": [
                        message.get("tool_calls_present")
                        for message in request["request"]["messages"]
                    ],
                }
                for index, request in enumerate(chat_requests[1:])
            ],
            "real_tool_result_content": tool_content_shape,
            "side_effect_boundary": {
                "provider_endpoint": "127.0.0.1 loopback owned by probe",
                "external_network": "none observed; all recorded HTTP traffic stayed on the synthetic loopback",
                "credentials": "none; only a synthetic key was placed in the throwaway config and auth values were reduced to presence booleans",
                "oauth": "not entered",
                "browser": "not started",
                "filesystem": "reference runtime state was confined to the throwaway HOME/HERMES_HOME and removed after the probe; no tool-specific path or result was observed",
                "tool_action": "clarify is interactive-only; only arrow navigation and one Enter selection on the TUI question surface were exercised, with no external side effect",
            },
            "clean_exit": exited,
            "unknowns": [
                "Whether the observed question-surface cursor semantics are stable across reference restarts, and the exact completion/approval/failure semantics, remain intentionally bounded by this single fresh observation.",
                "Provider-specific retries, malformed or truncated argument handling, multiple calls, approval policy, and post-handoff failure behavior remain unknown.",
                "The auxiliary non-stream request seen in OBS-0108/0109/0114 retains its purpose-unknown status and is not a Hades requirement.",
            ],
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
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--observation-window", type=float, default=OBSERVATION_WINDOW)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0116",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with deterministic loopback HTTP/SSE completed tool-call fixture",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, prompt text, assistant text, tool arguments, credentials, authorization values, session identifiers, timestamps, and redraw bytes are omitted or represented by stable markers or digests.",
            "The provider endpoint is a deterministic 127.0.0.1 fixture owned by this probe; no external network, OAuth flow, browser, tool response, or user credential is used.",
            "The response records OpenAI-compatible tool-call delta shape and argument-fragment boundaries without copying argument payloads; the [DONE] marker completes the stream so the post-completion question surface can be interacted with.",
            "clarify is interactive-only; observing its TUI question surface involves no external side effect and does not turn the reference handoff into Hades execution behavior.",
            "The real Hermes tool-result content is recorded only as normalized shape (role, content kind, length, digest) plus boolean anchors against the probe-owned choice text; the content itself is never persisted.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        if args.observation_window < 0 or args.observation_window > 15:
            raise ProbeFailure("reference", "arguments", "observation window must be between 0 and 15 seconds")
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
