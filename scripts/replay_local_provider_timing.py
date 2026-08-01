#!/usr/bin/env python3
"""Replay Hades incremental provider deltas and cancellation through a PTY."""

from __future__ import annotations

import argparse
import json
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from replay_local_provider import (
    COLUMNS,
    DEFAULT_BINARY,
    ROWS,
    ReplayFailure,
    assert_clean_exit,
    clean_output,
    marker_present,
    send,
    spawn,
    stop_process,
    wait_for,
    wait_for_exit,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "tests/fixtures/parity/OBS-0053-hades-stream-timing.json"
FIRST_DELTA = "HADES_DELAY_FIRST"
SECOND_DELTA = "HADES_DELAY_SECOND"


class DelayedProviderServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        self.request_seen = threading.Event()
        self.first_sent = threading.Event()
        self.release_second = threading.Event()
        self.handler_done = threading.Event()
        self.connection_closed = threading.Event()
        self.records: list[dict[str, Any]] = []
        self.writes: list[dict[str, Any]] = []
        super().__init__(("127.0.0.1", 0), self._handler())

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                owner.records.append(
                    {
                        "path": self.path,
                        "content_type": self.headers.get("Content-Type", ""),
                        "authorization_present": self.headers.get("Authorization") is not None,
                        "body": json.loads(body.decode("utf-8")),
                    }
                )
                owner.request_seen.set()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self._write(0, b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n', "role")
                    self._write(1, f'data: {{"choices":[{{"delta":{{"content":"{FIRST_DELTA}"}}}}]}}\n\n'.encode(), FIRST_DELTA)
                    owner.first_sent.set()
                    owner.release_second.wait(timeout=5.0)
                    self._write(2, f'data: {{"choices":[{{"delta":{{"content":"{SECOND_DELTA}"}}}}]}}\n\n'.encode(), SECOND_DELTA)
                    self._write(3, b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n', "finish")
                    self._write(4, b"data: [DONE]\n\n", "DONE")
                except (BrokenPipeError, ConnectionResetError, OSError) as error:
                    owner.connection_closed.set()
                    owner.writes.append({"index": 99, "marker": "connection-closed", "sent": False, "error": type(error).__name__})
                finally:
                    owner.handler_done.set()

            def _write(self, index: int, payload: bytes, marker: str) -> None:
                self.wfile.write(payload)
                self.wfile.flush()
                owner.writes.append({"index": index, "marker": marker, "sent": True})

        return Handler


def start_server() -> tuple[DelayedProviderServer, threading.Thread]:
    server = DelayedProviderServer()
    thread = threading.Thread(target=server.serve_forever, name="hades-delayed-provider", daemon=True)
    thread.start()
    return server, thread


def finish_server(server: DelayedProviderServer, thread: threading.Thread) -> None:
    server.release_second.set()
    server.shutdown()
    server.server_close()
    thread.join(timeout=2.0)


def run_case(binary: Path, interrupt: bool, timeout: float) -> dict[str, Any]:
    case = "interrupt-before-completion" if interrupt else "delayed-delta-order"
    server, server_thread = start_server()
    pid, fd, _slave_path, home = spawn(binary, f"http://127.0.0.1:{server.server_port}/v1")
    output = bytearray()
    reaped = False
    try:
        wait_for(pid, fd, output, case, "startup", lambda text: "Hermes Agent" in text and "ready" in text, timeout)
        send(fd, b"stream timing probe\r")
        wait_for(pid, fd, output, case, "request", lambda _text: server.request_seen.is_set(), timeout)
        wait_for(pid, fd, output, case, "first-write", lambda _text: server.first_sent.is_set(), timeout)
        wait_for(
            pid,
            fd,
            output,
            case,
            "first-delta",
            lambda text: marker_present(text, FIRST_DELTA),
            timeout,
        )

        if interrupt:
            send(fd, b"\x03")
            wait_for(pid, fd, output, case, "interrupt", lambda text: marker_present(text, "interrupted"), timeout)
            time.sleep(0.1)
            server.release_second.set()
            wait_for(pid, fd, output, case, "connection-close", lambda _text: server.handler_done.is_set(), timeout)
            if marker_present(clean_output(bytes(output)), SECOND_DELTA):
                raise ReplayFailure(case, "late-delta", "the second provider delta rendered after Ctrl+C", bytes(output))
            if not server.connection_closed.is_set():
                raise ReplayFailure(case, "connection-close", "provider server did not observe the cancelled socket", bytes(output))
            send(fd, b"\x03")
        else:
            server.release_second.set()
            wait_for(
                pid,
                fd,
                output,
                case,
                "second-delta",
                lambda text: marker_present(text, SECOND_DELTA),
                timeout,
            )
            wait_for(pid, fd, output, case, "ready", lambda text: marker_present(text, "ready"), timeout)
            send(fd, b"\x03")

        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        assert_clean_exit(status, case)
        raw = bytes(output)
        if b"\x1b[?1049l" not in raw:
            raise ReplayFailure(case, "cleanup", "alternate screen was not restored", raw)
        if len(server.records) != 1:
            raise ReplayFailure(case, "request", f"expected one request, got {len(server.records)}", raw)
        record = server.records[0]
        body = record["body"]
        if record["path"] != "/v1/chat/completions" or record["content_type"] != "application/json":
            raise ReplayFailure(case, "request", "request boundary was not preserved", raw)
        if record["authorization_present"]:
            raise ReplayFailure(case, "request", "unexpected authorization crossed the sanitized replay boundary", raw)
        if sorted(body) != ["max_tokens", "messages", "model", "stream", "stream_options", "tools"]:
            raise ReplayFailure(case, "request", f"unexpected body keys: {sorted(body)}", raw)
        if body["model"] != "palette-model" or body["stream"] is not True:
            raise ReplayFailure(case, "request", "model/stream markers were not preserved", raw)
        if [message["role"] for message in body["messages"]] != ["system", "user"]:
            raise ReplayFailure(case, "request", "message role boundary was not preserved", raw)
        return {
            "id": case,
            "status": "passed",
            "input": [
                {"kind": "text", "value": "sanitized prompt"},
                {"kind": "key", "value": "Enter"},
                {"kind": "key", "value": "Ctrl+C", "meaning": "interrupt before delayed second delta" if interrupt else "bounded cleanup after completion"},
                *([{"kind": "key", "value": "Ctrl+C", "meaning": "exit from ready/interrupted state"}] if interrupt else []),
            ],
            "request": {
                "method": "POST",
                "path": record["path"],
                "content_type": record["content_type"],
                "authorization_present": False,
                "body_keys": sorted(body),
                "model": body["model"],
                "stream": body["stream"],
                "message_roles": [message["role"] for message in body["messages"]],
                "tools_present": bool(body["tools"]),
            },
            "writes": server.writes,
            "visible_state": {
                "first_delta_visible": True,
                "second_delta_visible": not interrupt,
                "partial_response_preserved": interrupt,
                "interrupted_surface_observed": interrupt,
                "returned_to_ready": True,
                "provider_connection_closed": server.connection_closed.is_set() if interrupt else False,
                "clean_exit": True,
            },
        }
    finally:
        stop_process(pid, fd, reaped)
        finish_server(server, server_thread)
        shutil.rmtree(home, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    binary = args.binary.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "command": "replay-local-provider-timing",
        "binary": str(binary),
        "contract": str(args.contract.resolve()),
        "dimensions": {"columns": COLUMNS, "rows": ROWS, "emulator": "direct PTY"},
        "cases": [],
        "passed": False,
    }
    try:
        if not binary.is_file():
            raise ReplayFailure("report", "binary", f"binary not found: {binary}")
        report["cases"] = [run_case(binary, interrupt=False, timeout=args.timeout), run_case(binary, interrupt=True, timeout=args.timeout)]
        report["passed"] = True
    except (OSError, ReplayFailure, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        report["failure"] = error.as_dict() if isinstance(error, ReplayFailure) else {"message": str(error)}
        status = 1
    else:
        status = 0
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized, encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
