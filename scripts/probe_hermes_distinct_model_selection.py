#!/usr/bin/env python3
"""Capture Hermes distinct-model selection effectiveness and persistence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from probe_hermes_model_picker import (
    COLUMNS,
    DEFAULT_REFERENCE,
    ROWS,
    SOURCE_COMMIT,
    screen_contains,
    type_text,
)
from probe_hermes_model_picker_selection import (
    advance_to_model_stage,
    artifact_roots,
    clean_exit,
    drain,
    enter_provider_stage,
    file_digest,
    screen_landmarks,
    screen_text,
    start_existing,
    stop,
)
from probe_hermes_slash_commands import (
    BASE_URL,
    ProbeFailure,
    SYNTHETIC_KEY,
    safe_tail,
    wait_for,
    write_bytes,
)


CASE = "distinct-model-selection"
DEFAULT_MODEL = "palette-model"
ALTERNATE_MODEL = "alternate-model"
PROMPT = "distinct-model prompt"
MODEL_STAGE_MARKERS = [
    "Select model (step 2/2)",
    "palette-loopback",
    DEFAULT_MODEL,
    "persist: session",
    "Enter switch",
]


def normalized_landmarks(raw: bytes) -> list[str]:
    """Keep screen landmarks stable without leaking temporary checkout paths."""

    return [
        re.sub(r"/tmp/hades-hermes-ref-[A-Za-z0-9_-]+", "<reference-checkout>", line)
        for line in screen_landmarks(raw)
    ]


def normalized_requests(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retain request metadata and model markers, never request payloads."""

    return [
        {
            "method": record["method"],
            "path": record["path"],
            "content_type": record["content_type"],
            "body_bytes": record["body_bytes"],
            "authorization_present": record["authorization_present"],
            **{
                key: record[key]
                for key in ("model", "stream", "message_roles", "prompt_marker")
                if key in record
            },
        }
        for record in records
    ]


class DistinctModelServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        super().__init__(("127.0.0.1", 8765), self._handler())

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(record) for record in self.records]

    def _record(self, method: str, path: str, content_type: str, body: bytes, authorization: bool) -> None:
        record: dict[str, Any] = {
            "method": method,
            "path": path,
            "content_type": content_type,
            "body_bytes": len(body),
            "authorization_present": authorization,
        }
        if method == "POST" and path == "/v1/chat/completions":
            try:
                payload = json.loads(body.decode("utf-8"))
                record["model"] = payload.get("model")
                record["stream"] = payload.get("stream") is True
                messages = payload.get("messages")
                if isinstance(messages, list):
                    record["message_roles"] = [
                        message.get("role")
                        for message in messages
                        if isinstance(message, dict)
                    ]
                    record["prompt_marker"] = (
                        PROMPT
                        if PROMPT in json.dumps(messages, ensure_ascii=False)
                        else "other"
                    )
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                record["model"] = None
                record["stream"] = False
                record["prompt_marker"] = "unparseable"
        with self.lock:
            self.records.append(record)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                return

            def _read_body(self) -> bytes:
                length = int(self.headers.get("Content-Length", "0"))
                return self.rfile.read(length)

            def _record(self, body: bytes = b"") -> None:
                owner._record(
                    self.command,
                    self.path,
                    self.headers.get("Content-Type", ""),
                    body,
                    self.headers.get("Authorization") is not None,
                )

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
                self._record()
                if self.path.endswith("/models"):
                    body = json.dumps(
                        {
                            "object": "list",
                            "data": [
                                {"id": DEFAULT_MODEL, "object": "model"},
                                {"id": ALTERNATE_MODEL, "object": "model"},
                            ],
                        }
                    ).encode()
                elif self.path.endswith(f"/models/{DEFAULT_MODEL}"):
                    body = json.dumps({"id": DEFAULT_MODEL, "object": "model"}).encode()
                elif self.path.endswith(f"/models/{ALTERNATE_MODEL}"):
                    body = json.dumps({"id": ALTERNATE_MODEL, "object": "model"}).encode()
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
                body = self._read_body()
                self._record(body)
                if self.path == "/api/show":
                    response = json.dumps(
                        {
                            "details": {"family": "synthetic", "parameter_size": "small"},
                            "model_info": {"general.architecture": "synthetic"},
                        }
                    ).encode()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(response)))
                    self.end_headers()
                    self.wfile.write(response)
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                chunks = [
                    {
                        "id": "distinct-model-chat",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": ALTERNATE_MODEL,
                        "choices": [{
                            "index": 0,
                            "delta": {"role": "assistant"},
                            "finish_reason": None,
                        }],
                    },
                    {
                        "id": "distinct-model-chat",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": ALTERNATE_MODEL,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": "Distinct model answer."},
                            "finish_reason": None,
                        }],
                    },
                    {
                        "id": "distinct-model-chat",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": ALTERNATE_MODEL,
                        "choices": [{
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        }],
                    },
                ]
                response = b"".join(
                    f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n".encode()
                    for chunk in chunks
                ) + b"data: [DONE]\n\n"
                try:
                    self.wfile.write(response)
                    self.wfile.flush()
                except OSError:
                    return

        return Handler


def write_distinct_config(home: Path) -> None:
    (home / "config.yaml").write_text(
        "model:\n"
        "  provider: custom\n"
        f"  default: {DEFAULT_MODEL}\n"
        f"  base_url: {BASE_URL}\n"
        f"  api_key: {SYNTHETIC_KEY}\n"
        "custom_providers:\n"
        "  - name: palette-loopback\n"
        f"    base_url: {BASE_URL}\n"
        f"    api_key: {SYNTHETIC_KEY}\n"
        f"    model: {DEFAULT_MODEL}\n",
        encoding="utf-8",
    )


def snapshot_tree(home: Path) -> list[str]:
    return sorted(str(path.relative_to(home)) for path in home.rglob("*") if path.is_file())


def wait_for_alternate_filter(pid: int, fd: int, buffer: bytes, timeout: float) -> bytes:
    buffer = type_text(pid, fd, buffer, "alternate")
    return wait_for(
        pid,
        fd,
        buffer,
        CASE,
        "alternate-filter",
        lambda current: screen_contains(current, "filter: alternate")
        and screen_contains(current, ALTERNATE_MODEL),
        timeout,
    )


def wait_for_request(
    pid: int,
    fd: int,
    buffer: bytes,
    server: DistinctModelServer,
    timeout: float,
) -> bytes:
    try:
        return wait_for(
            pid,
            fd,
            buffer,
            CASE,
            "distinct-model-request",
            lambda current: any(
                record["method"] == "POST"
                and record["path"] == "/v1/chat/completions"
                and record.get("model") == ALTERNATE_MODEL
                and record.get("prompt_marker") == PROMPT
                and record.get("stream") is True
                for record in server.snapshot()
            )
            and screen_contains(current, "Distinct model answer."),
            timeout,
        )
    except ProbeFailure as error:
        # Keep request diagnostics bounded and sanitized when the reference
        # fails to submit.  This distinguishes a picker/composer boundary from
        # a provider response without claiming behavior from the timeout.
        error.details["request_records"] = server.snapshot()
        raise


def run_case(reference: Path, home: Path, server: DistinctModelServer, timeout: float) -> dict[str, Any]:
    write_distinct_config(home)
    config_path = home / "config.yaml"
    initial_config = config_path.read_bytes()
    initial_files = snapshot_tree(home)
    pid = fd = -1
    buffer = b""
    try:
        pid, fd, buffer = start_existing(reference, home, timeout)
        buffer = advance_to_model_stage(
            pid,
            fd,
            enter_provider_stage(pid, fd, buffer, timeout),
            timeout,
        )
        if not all(screen_contains(buffer, marker) for marker in MODEL_STAGE_MARKERS):
            raise ProbeFailure(CASE, "model-stage", "distinct catalog did not preserve baseline markers")
        buffer = wait_for_alternate_filter(pid, fd, buffer, timeout)
        selection_request_count = len(server.snapshot())
        write_bytes(fd, b"\r")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            CASE,
            "alternate-selection",
            lambda current: screen_contains(current, f"model → {ALTERNATE_MODEL}"),
            timeout,
        )
        selection_buffer = buffer
        selection_records = server.snapshot()[selection_request_count:]
        if any(record["path"] == "/v1/chat/completions" for record in selection_records):
            raise ProbeFailure(CASE, "alternate-selection", "selection opened a chat request")

        buffer = type_text(pid, fd, buffer, PROMPT)
        buffer = wait_for(
            pid,
            fd,
            buffer,
            CASE,
            "distinct-model-prompt",
            lambda current: screen_contains(current, PROMPT),
            timeout,
        )
        buffer = drain(pid, fd, buffer, 0.1)
        write_bytes(fd, b"\r")
        buffer = wait_for_request(pid, fd, buffer, server, timeout)
        chat_records = [
            record
            for record in server.snapshot()
            if record["method"] == "POST" and record["path"] == "/v1/chat/completions"
        ]
        prompt_records = [
            record for record in chat_records if record.get("prompt_marker") == PROMPT
        ]
        primary_records = [record for record in prompt_records if record.get("stream") is True]
        if not primary_records or primary_records[0].get("model") != ALTERNATE_MODEL:
            raise ProbeFailure(
                CASE,
                "distinct-model-request",
                "chat request did not use alternate-model",
                {"chat_records": normalized_requests(chat_records)},
            )
        buffer, _ = clean_exit(pid, fd, buffer, CASE, timeout)
        pid = fd = -1

        selected_config = config_path.read_bytes()
        selected_files = snapshot_tree(home)
        selected_digest = hashlib.sha256(selected_config).hexdigest()

        pid, fd, buffer = start_existing(reference, home, timeout)
        provider_buffer = enter_provider_stage(pid, fd, buffer, timeout)
        fresh_default_marker = screen_contains(provider_buffer, f"Current: {DEFAULT_MODEL}")
        fresh_alternate_marker = screen_contains(provider_buffer, f"Current: {ALTERNATE_MODEL}")
        buffer = advance_to_model_stage(pid, fd, provider_buffer, timeout)
        fresh_stage = screen_text(buffer)
        fresh_model_markers = {
            marker: screen_contains(buffer, marker)
            for marker in MODEL_STAGE_MARKERS + [ALTERNATE_MODEL]
        }
        write_bytes(fd, b"\x1b\x1b")
        buffer = drain(pid, fd, buffer, 0.35)
        buffer, _ = clean_exit(pid, fd, buffer, CASE, timeout)
        pid = fd = -1

        return {
            "id": CASE,
            "status": "passed",
            "input_sequence": [
                {"kind": "text", "value": "/model"},
                {"kind": "key", "value": "Enter twice"},
                {"kind": "text", "value": "palette"},
                {"kind": "key", "value": "Enter"},
                {"kind": "text", "value": "alternate"},
                {"kind": "key", "value": "Enter on alternate-model"},
                {"kind": "text", "value": PROMPT},
                {"kind": "key", "value": "Enter"},
            ],
            "selection": {
                "target": ALTERNATE_MODEL,
                "status_visible": screen_contains(selection_buffer, f"model → {ALTERNATE_MODEL}"),
                "chat_request_model": primary_records[0].get("model"),
                "chat_request_count": len(chat_records),
                "additional_chat_request_count": max(0, len(chat_records) - 1),
                "metadata_request_count": len(selection_records),
                "selection_chat_request_count": 0,
                "request_trace": normalized_requests(selection_records),
                "config_changed": initial_config != selected_config,
                "config_sha256_after_selection": selected_digest,
                "artifact_roots_after_selection": artifact_roots(selected_files),
            },
            "chat_request_trace": normalized_requests(chat_records),
            "fresh_process_readback": {
                "provider_stage": {
                    "current_default_visible": fresh_default_marker,
                    "current_alternate_visible": fresh_alternate_marker,
                },
                "current_default_visible": fresh_default_marker,
                "current_alternate_visible": fresh_alternate_marker,
                "alternate_model_stage_visible": fresh_model_markers.get(ALTERNATE_MODEL, False),
                "model_stage_markers": fresh_model_markers,
                "stage_text_contains_alternate": ALTERNATE_MODEL in fresh_stage,
                "config_equal_to_after_selection": config_path.read_bytes() == selected_config,
                "persistence_classification": (
                    "persisted"
                    if fresh_alternate_marker
                    else "not_persisted"
                    if fresh_default_marker
                    else "unknown"
                ),
            },
            "initial_state": {
                "config_byte_length": len(initial_config),
                "artifact_roots": artifact_roots(initial_files),
            },
            "boundary": {
                "authorization_present": any(
                    record["authorization_present"] for record in server.snapshot()
                ),
                "external_network": False,
                "cleanup": "streamed answer visible; fresh process exited after Escape and Ctrl+C",
            },
            "screen_landmarks": normalized_landmarks(buffer),
        }
    finally:
        if pid != -1:
            stop(pid, fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0096",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY rendered screen markers with loopback catalog and chat trace",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, loopback URL, credentials, session IDs, timestamps, and raw redraw bytes are omitted or replaced by placeholders.",
            "The loopback server exposes only palette-model and alternate-model, records method/path/body size/model marker/authorization presence, and returns a deterministic synthetic answer.",
            "Config contents are reduced to byte equality, lengths, and hashes; artifacts are reduced to root classes and no credential value is emitted.",
            "A distinct model request or fresh-process marker is promoted only from the isolated request/config/screen traces; repeated metadata or failure behavior is diagnostic evidence only.",
        ],
        "cases": [],
        "passed": False,
    }
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-distinct-model-"))
    home = root / "home"
    home.mkdir()
    server: DistinctModelServer | None = None
    thread: threading.Thread | None = None
    try:
        if not reference.is_dir():
            raise ProbeFailure(CASE, "reference", f"reference checkout does not exist: {reference}")
        server = DistinctModelServer()
        thread = threading.Thread(target=server.serve_forever, name="hermes-distinct-model", daemon=True)
        thread.start()
        report["cases"].append(run_case(reference, home, server, args.timeout))
        report["boundaries"] = {
            "provider": "loopback-only deterministic HTTP server",
            "models": [DEFAULT_MODEL, ALTERNATE_MODEL],
            "credentials": "synthetic config input omitted from report",
            "external_network": False,
            "host_clipboard": False,
        }
        report["unknowns"] = [
            "Selection toggles, additional models, unavailable rows, provider errors, and alternate Hermes setup surfaces remain outside this bounded path.",
            "A fresh-process current marker is classified only when the provider stage renders a distinct default or alternate model; otherwise persistence remains unknown.",
            "Any repeated metadata request or failure boundary is not a Hades behavior requirement.",
        ]
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        if isinstance(error, ProbeFailure):
            details = error.as_dict()
            if "screen_tail" in details:
                details["screen_tail"] = safe_tail(str(details["screen_tail"]).encode())
            report["failure"] = details
        else:
            report["failure"] = str(error)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2.0)
        shutil.rmtree(root, ignore_errors=True)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized, encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
