#!/usr/bin/env python3
"""Capture the bounded Hermes model-picker selection side-effect boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
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
from probe_hermes_slash_commands import (
    ProbeFailure,
    clean_exit,
    contains_marker,
    drain,
    safe_tail,
    spawn,
    stop,
    wait_for,
    write_bytes,
    write_ready_config,
)
from probe_hermes_terminal_palette import Screen


CASE = "model-picker-selection-boundary"
MODEL_STAGE_MARKERS = [
    "Select model (step 2/2)",
    "palette-loopback",
    "palette-model",
    "persist: session",
    "Enter switch",
]


class SelectionServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        super().__init__(("127.0.0.1", 8765), self._handler())

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(record) for record in self.records]

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                return

            def _record(self, body: bytes = b"") -> None:
                with owner.lock:
                    owner.records.append(
                        {
                            "method": self.command,
                            "path": self.path,
                            "content_type": self.headers.get("Content-Type", ""),
                            "authorization_present": self.headers.get("Authorization") is not None,
                            "body_bytes": len(body),
                        }
                    )

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
                self._record()
                if self.path.endswith("/models") or self.path.endswith("/models/palette-model"):
                    body = json.dumps(
                        {
                            "object": "list",
                            "data": [{"id": "palette-model", "object": "model"}],
                            "id": "palette-model",
                        }
                    ).encode()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_error(404)

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
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
                try:
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except OSError:
                    return

        return Handler


def screen_text(raw: bytes) -> str:
    screen = Screen()
    screen.feed(raw)
    return "\n".join(screen.lines())


def screen_landmarks(raw: bytes) -> list[str]:
    keywords = ("model", "provider", "switch", "select", "ready", "error", "current")
    lines = []
    for line in screen_text(raw).splitlines():
        compact = " ".join(line.split())
        if compact and any(keyword in compact.lower() for keyword in keywords):
            lines.append(compact[:240])
    return lines[-30:]


def snapshot_tree(home: Path) -> list[str]:
    if not home.exists():
        return []
    return sorted(str(path.relative_to(home)) for path in home.rglob("*") if path.is_file())


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_roots(files: list[str]) -> list[str]:
    return sorted({file.split("/", 1)[0] for file in files})


def start_existing(reference: Path, home: Path, timeout: float) -> tuple[int, int, bytes]:
    pid, fd = spawn(reference, home, configured=False)
    try:
        buffer = wait_for(
            pid,
            fd,
            b"",
            CASE,
            "startup",
            lambda current: contains_marker(current, "Hermes Agent") and contains_marker(current, "ready"),
            timeout,
        )
        return pid, fd, buffer
    except BaseException:
        stop(pid, fd)
        raise


def enter_provider_stage(pid: int, fd: int, buffer: bytes, timeout: float) -> bytes:
    write_bytes(fd, b"/model\r")
    buffer = drain(pid, fd, buffer, 0.5)
    write_bytes(fd, b"\r")
    provider_markers = [
        "Select provider (step 1/2)",
        "Current: palette-model",
        "type to filter",
        "persist: session",
        "Esc clear/back",
        "q close",
    ]
    buffer = wait_for(
        pid,
        fd,
        buffer,
        CASE,
        "provider-picker",
        lambda current: all(contains_marker(current, marker) for marker in provider_markers),
        timeout,
    )
    return buffer


def advance_to_model_stage(pid: int, fd: int, buffer: bytes, timeout: float) -> bytes:
    buffer = type_text(pid, fd, buffer, "palette")
    buffer = wait_for(
        pid,
        fd,
        buffer,
        CASE,
        "provider-filter",
        lambda current: screen_contains(current, "filter: palette")
        and screen_contains(current, "palette-loopback"),
        timeout,
    )
    write_bytes(fd, b"\r")
    return wait_for(
        pid,
        fd,
        buffer,
        CASE,
        "model-stage",
        lambda current: all(screen_contains(current, marker) for marker in MODEL_STAGE_MARKERS),
        timeout,
    )


def enter_model_stage(pid: int, fd: int, buffer: bytes, timeout: float) -> bytes:
    return advance_to_model_stage(pid, fd, enter_provider_stage(pid, fd, buffer, timeout), timeout)


def run_case(reference: Path, home: Path, server: SelectionServer, timeout: float) -> dict[str, Any]:
    write_ready_config(home)
    config_path = home / "config.yaml"
    initial_config = config_path.read_bytes()
    initial_digest = file_digest(config_path)
    initial_files = snapshot_tree(home)
    pid = fd = -1
    buffer = b""
    try:
        # Control: open the model stage and leave without selecting a row. This
        # separates Hermes' normal startup/cache/config initialization from the
        # side effects attributable to the bounded Enter selection input.
        pid, fd, buffer = start_existing(reference, home, timeout)
        buffer = enter_model_stage(pid, fd, buffer, timeout)
        baseline_model_stage = {
            marker: screen_contains(buffer, marker) for marker in MODEL_STAGE_MARKERS
        }
        write_bytes(fd, b"\x1b\x1b")
        buffer = drain(pid, fd, buffer, 0.35)
        buffer, _ = clean_exit(pid, fd, buffer, CASE, timeout)
        pid = fd = -1
        baseline_config = config_path.read_bytes() if config_path.exists() else b""
        baseline_digest = file_digest(config_path) if config_path.exists() else None
        baseline_files = snapshot_tree(home)
        baseline_requests = server.snapshot()

        # Selection case: the only additional model-stage action is Enter on
        # the visible palette-model row.
        selection_request_start = len(baseline_requests)
        pid, fd, buffer = start_existing(reference, home, timeout)
        buffer = enter_model_stage(pid, fd, buffer, timeout)
        write_bytes(fd, b"\r")
        buffer = drain(pid, fd, buffer, 1.0)
        selection_markers = {
            marker: screen_contains(buffer, marker)
            for marker in (
                "Select provider (step 1/2)",
                "Select model (step 2/2)",
                "ready",
                "Provider error",
                "Current: palette-model",
            )
        }
        selection_screen_landmarks = screen_landmarks(buffer)
        buffer, _ = clean_exit(pid, fd, buffer, CASE, timeout)
        pid = fd = -1
        selection_config = config_path.read_bytes() if config_path.exists() else b""
        selection_files = snapshot_tree(home)
        selection_requests = server.snapshot()[selection_request_start:]

        # Fresh-process readback: inspect the provider-stage current marker
        # before advancing to the model stage, then capture the model-stage
        # landmarks before cleanup mutates the final screen.
        pid, fd, buffer = start_existing(reference, home, timeout)
        provider_buffer = enter_provider_stage(pid, fd, buffer, timeout)
        current_marker = screen_contains(provider_buffer, "Current: palette-model")
        buffer = advance_to_model_stage(pid, fd, provider_buffer, timeout)
        fresh_stage_markers = {
            marker: screen_contains(buffer, marker) for marker in MODEL_STAGE_MARKERS
        }
        fresh_model_stage = screen_text(buffer)
        write_bytes(fd, b"\x1b\x1b")
        buffer = drain(pid, fd, buffer, 0.35)
        buffer, _ = clean_exit(pid, fd, buffer, CASE, timeout)
        pid = fd = -1

        return {
            "id": CASE,
            "status": "passed",
            "input_sequence": [
                {"kind": "text", "value": "/model"},
                {"kind": "key", "value": "Enter"},
                {"kind": "text", "value": "palette"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Enter on palette-model"},
            ],
            "baseline_control": {
                "selection_submitted": False,
                "model_stage_markers": baseline_model_stage,
                "config_changed_from_initial": initial_config != baseline_config,
                "config_sha256_initial": initial_digest,
                "config_sha256_after_control": file_digest(config_path) if config_path.exists() else None,
                "config_byte_length_initial": len(initial_config),
                "config_byte_length_after_control": len(baseline_config),
                "artifact_roots_initial": artifact_roots(initial_files),
                "artifact_roots_after_control": artifact_roots(baseline_files),
                "artifact_file_count_initial": len(initial_files),
                "artifact_file_count_after_control": len(baseline_files),
                "request_count": len(baseline_requests),
            },
            "selection_process": {
                "selection_input": "Enter on the visible palette-model row",
                "final_surface_markers": selection_markers,
                "screen_landmarks": selection_screen_landmarks,
                "config_changed_from_control": baseline_config != selection_config,
                "config_sha256_before_selection": baseline_digest,
                "config_sha256_after_selection": hashlib.sha256(selection_config).hexdigest(),
                "config_byte_length_before_selection": len(baseline_config),
                "config_byte_length_after_selection": len(selection_config),
                "artifact_roots_before_selection": artifact_roots(baseline_files),
                "artifact_roots_after_selection": artifact_roots(selection_files),
                "artifact_file_count_before_selection": len(baseline_files),
                "artifact_file_count_after_selection": len(selection_files),
                "requests": selection_requests,
                "cleanup": "bounded Ctrl+C cleanup exited cleanly",
            },
            "fresh_process_readback": {
                "model_stage_reached": all(fresh_stage_markers.values()),
                "current_palette_model_visible": current_marker,
                "model_stage_markers": fresh_stage_markers,
                "cleanup": "Escape plus bounded Ctrl+C cleanup exited cleanly",
            },
            "normalized_screen": {
                "selection_surface": selection_markers,
                "fresh_model_stage": {
                    "stage": "Select model (step 2/2)" if "Select model (step 2/2)" in fresh_model_stage else "unknown",
                    "current_palette_model_visible": current_marker,
                },
            },
            "selection_claim": "No model selection or persistence claim is promoted from this bounded Enter result; the control, selection delta, fresh-process current marker, and sanitized request/config traces are recorded explicitly.",
        }
    except ProbeFailure:
        raise
    finally:
        if pid != -1:
            stop(pid, fd)


def emit_report(report: dict[str, Any], path: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0093",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY rendered screen markers"},
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, loopback URL, credentials, session IDs, timestamps, and raw redraw bytes are omitted or replaced by placeholders.",
            "The local HTTP server is deterministic and loopback-only; request records contain method/path, content type, body size, and authorization presence without payload or credential values.",
            "Config bytes are compared only as changed/unchanged and file trees are reduced to relative artifact names; no config contents, API keys, or private paths are emitted.",
            "A model selection is not claimed from Enter, a transient redraw, or an unchanged current marker; only fresh-process/config/request evidence can promote that boundary.",
        ],
        "cases": [],
        "passed": False,
    }
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-model-selection-"))
    home = root / "home"
    home.mkdir()
    server: SelectionServer | None = None
    thread: threading.Thread | None = None
    try:
        if not reference.is_dir():
            raise ProbeFailure(CASE, "reference", f"reference checkout does not exist: {reference}")
        server = SelectionServer()
        thread = threading.Thread(target=server.serve_forever, name="hermes-model-selection", daemon=True)
        thread.start()
        report["cases"].append(run_case(reference, home, server, args.timeout))
        report["boundaries"] = {
            "provider": "loopback-only deterministic HTTP server",
            "credentials": "synthetic config input omitted from report",
            "external_network": False,
            "selection_persistence": "unknown unless fresh-process/config evidence proves it",
        }
        report["unknowns"] = [
            "Provider and model inventories, dynamic discovery timing, warnings, and model-selection behavior outside the visible palette-model row remain unknown.",
            "A config or request change not observed in this bounded path must not be inferred from the model-picker redraw.",
            "Persistence toggles, empty model lists, unreachable providers, authentication failures, and selection across sessions remain outside the observation.",
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
    emit_report(report, args.report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
