#!/usr/bin/env python3
"""Replay the Hades multi-hop tool loop through a real PTY (spec 011, OBS-0120).

The loopback provider asks Hades to execute a terminal tool call whose only
side effect writes into the probe-owned sandbox (`mkdir -p <sandbox>/hopdir &&
echo hop-one > <sandbox>/hopdir/hop.txt`), then a read_file tool call on the
written file, then a plain completion — two hops then termination. Hades must
execute both tools against the explicit `HADES_SANDBOX` root, feed the
executed results back through the follow-up requests in the observed
`system,user,assistant,tool` shape, and terminate when the follow-up stream
carries no tool calls. Ctrl+C exits cleanly.

The report carries only path-free normalized facts (structural markers,
lengths, digests), so the Python and Rust replays compare identically and no
probe-owned sandbox path leaks into evidence.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import tempfile
import termios
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from probe_tui_lifecycle import retain_slave_descriptor, slave_path_for_pid


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BINARY = ROOT / "target/debug/hades"
COLUMNS = 120
ROWS = 40
ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
Predicate = Callable[[str], bool]

PROMPT = "synthetic multi-hop prompt"
TERMINAL_MARKER = "Synthetic multi-hop terminal call"
READ_MARKER = "Synthetic multi-hop read call"
COMPLETION_TEXT = "Synthetic completion."
EXPECTED_TOOL_COUNT = 31
# Canonical sort-keys SHA-256 of the OBS-0112 31-tool inventory.
EXPECTED_INVENTORY_DIGEST = "b2cbd3f2bf77de3a91cf9a4844b324f6130aab8c72b2924a159cce533f38a220"
# OBS-0117/0120 byte-exact tool-result digests (path-free, stable across runs).
TERMINAL_RESULT_DIGEST = "708054e20f8345e96aa29aa3d3ae50e6245e6723619f1f57c1486f2c2ef9c451"
READ_RESULT_DIGEST = "fb3accfce3bc199b09eebb2e2e03ea41ff7467e0f76fc5e75ce6849fa6ff856f"
# OBS-0120 sandbox side effect: `echo hop-one > .../hop.txt` (trailing newline).
HOP_CONTENT = "hop-one\n"
HOP_DIGEST = "8dafa0ec68b138aeb867e95010596f555ee72018ca35ae8ee8d4fdca3c55b030"


def canonical_digest(value: Any) -> str:
    """Sort object keys recursively and hash the compact serialization,
    matching the probe/validator canonical digest convention."""

    def sort(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: sort(item) for key, item in sorted(node.items())}
        if isinstance(node, list):
            return [sort(item) for item in node]
        return node

    encoded = json.dumps(sort(value), ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class ReplayFailure(RuntimeError):
    """Raised when a bounded multi-hop replay assertion fails."""

    def __init__(self, case: str, step: str, message: str, output: bytes = b""):
        super().__init__(message)
        self.case = case
        self.step = step
        self.message = message
        self.output = output

    def as_dict(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "step": self.step,
            "message": self.message,
            "screen_tail": clean_output(self.output)[-2000:],
        }


def tool_call_chunks(marker: str, tool: str, call_id: str, arguments: str) -> list[bytes]:
    return [
        b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
        (
            b'data: {"choices":[{"delta":{"content":"'
            + marker.encode()
            + b'","tool_calls":[{"index":0,"id":"'
            + call_id.encode()
            + b'","type":"function","function":{"name":"'
            + tool.encode()
            + b'","arguments":'
            + json.dumps(arguments, separators=(",", ":")).encode()
            + b"}}]}}]}\n\n"
        ),
        b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n',
        b"data: [DONE]\n\n",
    ]


def completion_chunks(text: str = COMPLETION_TEXT) -> list[bytes]:
    return [
        b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"' + text.encode() + b'"}}]}\n\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
        b"data: [DONE]\n\n",
    ]


class ToolExecutionServer(ThreadingHTTPServer):
    """Deterministic loopback provider serving the S4 multi-hop script."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, script: list[tuple[str, str, str, str, str]]) -> None:
        # script entries: (kind, marker, tool, call_id, arguments) with kind
        # in {"tool-call", "completion"}.
        self.script = script
        self.records: list[dict[str, Any]] = []
        self.streaming_requests = 0
        self.completion_served = threading.Event()
        super().__init__(("127.0.0.1", 0), self._handler())

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
                owner.records.append({"method": "GET", "path": self.path})
                if self.path in {"/api/v1/models", "/v1/models"}:
                    self._json({"object": "list", "data": [{"id": "palette-model", "object": "model"}]})
                    return
                if self.path == "/v1/models/palette-model":
                    self._json({"id": "palette-model", "object": "model"})
                    return
                if self.path == "/api/tags":
                    self._json({"models": [{"name": "palette-model"}]})
                    return
                self._json({"error": {"message": "synthetic endpoint not found"}}, 404)

            def _json(self, payload: dict[str, Any], status: int = 200) -> None:
                encoded = json.dumps(payload, separators=(",", ":")).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                payload = json.loads(body.decode("utf-8"))
                owner.records.append(
                    {
                        "method": "POST",
                        "path": self.path,
                        "authorization_present": self.headers.get("Authorization") is not None,
                        "body": payload,
                    }
                )
                if payload.get("stream") is not True:
                    self._json(
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

                owner.streaming_requests += 1
                step_index = owner.streaming_requests - 1
                if step_index >= len(owner.script):
                    self._json({"error": {"message": "synthetic script exhausted"}}, 500)
                    return
                kind, marker, tool, call_id, arguments = owner.script[step_index]
                if kind == "tool-call":
                    chunks = tool_call_chunks(marker, tool, call_id, arguments)
                else:
                    chunks = completion_chunks(marker)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                for chunk in chunks:
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except OSError:
                        return
                    time.sleep(0.02)
                if kind == "completion":
                    owner.completion_served.set()

        return Handler


def clean_output(output: bytes) -> str:
    return ANSI_ESCAPE.sub("", output.decode("utf-8", errors="replace")).replace("\r", "")


def marker_present(text: str, marker: str) -> bool:
    if marker in text:
        return True
    compact_text = "".join(text.split())
    compact_marker = "".join(marker.split())
    return compact_marker in compact_text


def set_window_size(fd: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLUMNS, 0, 0))


def read_available(fd: int, output: bytearray) -> None:
    while True:
        try:
            chunk = os.read(fd, 65_536)
        except OSError as error:
            if error.errno in {errno.EAGAIN, errno.EIO}:
                return
            raise
        if not chunk:
            return
        output.extend(chunk)


def child_done(pid: int) -> tuple[bool, int | None]:
    waited, status = os.waitpid(pid, os.WNOHANG)
    return waited != 0, status if waited else None


def wait_for(
    pid: int,
    fd: int,
    output: bytearray,
    case: str,
    step: str,
    predicate: Predicate,
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        read_available(fd, output)
        if predicate(clean_output(bytes(output))):
            return
        done, _ = child_done(pid)
        if done:
            read_available(fd, output)
            raise ReplayFailure(case, step, "Hades exited before the PTY assertion", bytes(output))
        remaining = deadline - time.monotonic()
        select.select([fd], [], [], min(0.05, max(0.0, remaining)))
    read_available(fd, output)
    raise ReplayFailure(case, step, f"timed out after {timeout:.1f}s", bytes(output))


def wait_for_rendered(
    pid: int,
    fd: int,
    output: bytearray,
    case: str,
    step: str,
    predicate: Predicate,
    timeout: float,
) -> None:
    """Like wait_for, but the predicate sees the RENDERED screen text."""
    from probe_hermes_terminal_palette import Screen  # lazy: avoids cycles

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        read_available(fd, output)
        screen = Screen()
        screen.feed(bytes(output))
        if predicate("\n".join(screen.lines())):
            return
        done, _ = child_done(pid)
        if done:
            read_available(fd, output)
            raise ReplayFailure(case, step, "Hades exited before the PTY assertion", bytes(output))
        remaining = deadline - time.monotonic()
        select.select([fd], [], [], min(0.05, max(0.0, remaining)))
    read_available(fd, output)
    raise ReplayFailure(case, step, f"timed out after {timeout:.1f}s", bytes(output))


def wait_for_exit(pid: int, fd: int, output: bytearray, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        read_available(fd, output)
        done, status = child_done(pid)
        if done and status is not None:
            return status
        remaining = deadline - time.monotonic()
        select.select([fd], [], [], min(0.05, max(0.0, remaining)))
    raise ReplayFailure("cleanup", "exit", f"process did not exit within {timeout:.1f}s", bytes(output))


def send(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def terminal_flags(slave_path: str) -> dict[str, bool]:
    local_flags = termios.tcgetattr(retain_slave_descriptor(slave_path))[3]
    return {
        "canonical": bool(local_flags & termios.ICANON),
        "echo": bool(local_flags & termios.ECHO),
    }


def spawn(binary: Path, base_url: str, sandbox: Path) -> tuple[int, int, str, Path]:
    home = Path(tempfile.mkdtemp(prefix="hades-tool-execution-"))
    pid, master = pty.fork()
    if pid == 0:
        environment = os.environ.copy()
        environment.update(
            {
                "TERM": "xterm-256color",
                "COLUMNS": str(COLUMNS),
                "LINES": str(ROWS),
                "HOME": str(home),
                "HERMES_HOME": str(home),
                "HADES_SANDBOX": str(sandbox),
            }
        )
        environment.pop("HADES_PROVIDER_API_KEY", None)
        environment["HADES_PROVIDER_BASE_URL"] = base_url
        environment["HADES_MODEL"] = "palette-model"
        os.execve(str(binary), [str(binary)], environment)
    set_window_size(master)
    os.set_blocking(master, False)
    slave_path = slave_path_for_pid(pid)
    retain_slave_descriptor(slave_path)
    return pid, master, slave_path, home


def stop_process(pid: int, fd: int, reaped: bool) -> None:
    if not reaped:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
    try:
        os.close(fd)
    except OSError:
        pass


def assert_clean_exit(status: int, case: str) -> None:
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        raise ReplayFailure(case, "cleanup", f"unexpected exit status: {status}")


def argument_shape(arguments: str) -> dict[str, Any]:
    parsed: Any = None
    try:
        parsed = json.loads(arguments)
    except (json.JSONDecodeError, UnicodeDecodeError):
        parsed = None
    shape: dict[str, Any] = {"valid_json": parsed is not None}
    if isinstance(parsed, dict):
        shape["top_level_keys"] = sorted(parsed)
        shape["value_kinds"] = {key: type(value).__name__ for key, value in parsed.items()}
        if "command" in parsed:
            command = parsed["command"]
            lowered = command.lower()
            shape["markers"] = {
                "contains_mkdir": "mkdir" in lowered,
                "contains_echo": "echo" in lowered,
                "contains_redirection": ">" in command,
                "contains_chain": "&&" in command,
                "contains_expected_basename": "hop.txt" in command,
            }
        elif "path" in parsed:
            path = parsed["path"]
            shape["markers"] = {"path_ends_with_expected_basename": path.endswith("hop.txt")}
    return shape


def run_multi_hop_case(binary: Path, timeout: float) -> dict[str, Any]:
    case = "tool-execution-multi-hop"
    sandbox = Path(tempfile.mkdtemp(prefix="hades-toolexec-"))
    hop = sandbox / "hopdir" / "hop.txt"
    command = f"mkdir -p {sandbox / 'hopdir'} && echo hop-one > {hop}"
    script = [
        ("tool-call", TERMINAL_MARKER, "terminal", "call_synthetic_terminal", json.dumps({"command": command}, separators=(",", ":"))),
        ("tool-call", READ_MARKER, "read_file", "call_synthetic_read_file", json.dumps({"path": str(hop)}, separators=(",", ":"))),
        ("completion", COMPLETION_TEXT, "", "", ""),
    ]
    server = ToolExecutionServer(script)
    server_thread = threading.Thread(target=server.serve_forever, name="hades-tool-execution", daemon=True)
    server_thread.start()
    pid, fd, slave_path, home = spawn(binary, f"http://127.0.0.1:{server.server_port}/v1", sandbox)
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            fd,
            output,
            case,
            "startup",
            lambda text: "Hades Agent" in text and "ready" in text,
            timeout,
        )
        send(fd, PROMPT.encode() + b"\r")
        wait_for_rendered(
            pid,
            fd,
            output,
            case,
            "terminal-result-follow-up",
            lambda text: marker_present(text, TERMINAL_MARKER) and marker_present(text, "ready"),
            timeout,
        )
        wait_for_rendered(
            pid,
            fd,
            output,
            case,
            "read-result-follow-up",
            lambda text: marker_present(text, READ_MARKER) and marker_present(text, "ready"),
            timeout,
        )
        wait_for_rendered(
            pid,
            fd,
            output,
            case,
            "completion",
            lambda text: marker_present(text, COMPLETION_TEXT) and marker_present(text, "ready"),
            timeout,
        )
        # Termination proof: the follow-up stream carried no tool calls, so no
        # fourth request may arrive.
        time.sleep(0.4)
        if server.streaming_requests != 3:
            raise ReplayFailure(
                case,
                "request-count",
                f"expected exactly 3 streaming chat requests, got {server.streaming_requests}",
                bytes(output),
            )
        visible = clean_output(bytes(output))
        if marker_present(visible, "Busy"):
            raise ReplayFailure(case, "response", "Hades stayed busy after the completion", bytes(output))
        done, _ = child_done(pid)
        if done:
            raise ReplayFailure(case, "response", "Hades exited before Ctrl+C", bytes(output))

        send(fd, b"\x03")
        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        assert_clean_exit(status, case)
        raw = bytes(output)
        if b"\x1b[?1049l" not in raw:
            raise ReplayFailure(case, "cleanup", "alternate screen was not restored", raw)
        flags = terminal_flags(slave_path)
        if not flags["canonical"] or not flags["echo"]:
            raise ReplayFailure(case, "cleanup", f"terminal flags were not restored: {flags}", raw)

        chat_requests = [r for r in server.records if r["method"] == "POST"]
        if len(chat_requests) != 3:
            raise ReplayFailure(
                case,
                "request-count",
                f"expected 3 chat requests (initial + two follow-ups), got {len(chat_requests)}",
                raw,
            )
        request, follow_up_1, follow_up_2 = chat_requests

        request_tools = request["body"].get("tools")
        if not isinstance(request_tools, list) or len(request_tools) != EXPECTED_TOOL_COUNT:
            raise ReplayFailure(
                case,
                "inventory",
                f"expected {EXPECTED_TOOL_COUNT} advertised tools, got {len(request_tools) if isinstance(request_tools, list) else request_tools}",
                raw,
            )
        inventory_digest = canonical_digest(request_tools)
        if inventory_digest != EXPECTED_INVENTORY_DIGEST:
            raise ReplayFailure(
                case,
                "inventory",
                "advertised tool inventory does not match the OBS-0112 wire digest",
                raw,
            )

        def verify_follow_up(follow_up: dict[str, Any], expected_roles: list[str], call_name: str, result_digest: str) -> dict[str, Any]:
            body = follow_up["body"]
            messages = body.get("messages", [])
            roles = [m["role"] for m in messages]
            if roles != expected_roles:
                raise ReplayFailure(
                    case,
                    "follow-up",
                    f"follow-up roles {roles} do not match the observed {expected_roles} shape",
                    raw,
                )
            assistant_message = messages[len(messages) - 2]
            if not assistant_message.get("tool_calls"):
                raise ReplayFailure(case, "follow-up", "follow-up assistant message lacks tool_calls", raw)
            if assistant_message["tool_calls"][0].get("function", {}).get("name") != call_name:
                raise ReplayFailure(case, "follow-up", "follow-up tool call name mismatch", raw)
            tool_message = messages[-1]
            if tool_message.get("role") != "tool" or not tool_message.get("tool_call_id"):
                raise ReplayFailure(case, "follow-up", "tool result message missing role/tool_call_id", raw)
            content = str(tool_message.get("content", ""))
            content_digest = hashlib.sha256(content.encode()).hexdigest()
            if content_digest != result_digest:
                raise ReplayFailure(
                    case,
                    "follow-up",
                    f"tool result digest {content_digest} does not match the observed {result_digest}",
                    raw,
                )
            parsed = json.loads(content)
            return {
                "message_roles": roles,
                "message_count": len(messages),
                "tool_result_messages": sum(1 for m in messages if m.get("role") == "tool"),
                "tool_call_id_markers": [
                    "synthetic-call-id"
                    if m.get("tool_call_id") in {"call_synthetic_terminal", "call_synthetic_read_file"}
                    else "absent"
                    if "tool_call_id" not in m
                    else "other-id"
                    for m in messages
                ],
                "assistant_tool_call_name": call_name,
                "tool_result_sha256": content_digest,
                "tool_result_top_level_keys": sorted(parsed) if isinstance(parsed, dict) else [],
            }

        follow_up_1_shape = verify_follow_up(
            follow_up_1, ["system", "user", "assistant", "tool"], "terminal", TERMINAL_RESULT_DIGEST
        )
        follow_up_2_shape = verify_follow_up(
            follow_up_2,
            ["system", "user", "assistant", "tool", "assistant", "tool"],
            "read_file",
            READ_RESULT_DIGEST,
        )

        hop_bytes = hop.read_bytes() if hop.is_file() else b""
        side_effects = {
            "files": [
                {
                    "basename": "hop.txt",
                    "exists": hop.is_file(),
                    "content_matches_expected": hop_bytes in {HOP_CONTENT.encode(), HOP_CONTENT.encode() + b"\n"},
                    "content_length": len(hop_bytes),
                    "content_sha256": hashlib.sha256(hop_bytes).hexdigest(),
                }
            ],
            "match": hop_bytes == HOP_CONTENT.encode(),
        }
        if not side_effects["match"]:
            raise ReplayFailure(
                case,
                "sandbox-side-effect",
                "the executed terminal tool did not produce the expected probe-owned sandbox file",
                raw,
            )

        terminal_arguments = json.dumps({"command": command}, separators=(",", ":"))
        read_arguments = json.dumps({"path": str(hop)}, separators=(",", ":"))
        return {
            "id": case,
            "status": "passed",
            "input_sequence": [
                {"kind": "text", "value": "<synthetic prompt>"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03"},
            ],
            "provider_request": {
                "path": request["path"],
                "authorization_present": request["authorization_present"],
                "body_keys": sorted(request["body"]),
                "model": request["body"]["model"],
                "stream": request["body"]["stream"],
                "message_roles": [m["role"] for m in request["body"]["messages"]],
                "tool_count": len(request_tools),
                "inventory_sha256": inventory_digest,
                "terminal_present": any(
                    tool.get("function", {}).get("name") == "terminal"
                    for tool in request["body"].get("tools", [])
                ),
                "read_file_present": any(
                    tool.get("function", {}).get("name") == "read_file"
                    for tool in request["body"].get("tools", [])
                ),
            },
            "tool_calls": [
                {
                    "name": "terminal",
                    "call_id_marker": "synthetic-call-id",
                    "arguments": argument_shape(terminal_arguments),
                },
                {
                    "name": "read_file",
                    "call_id_marker": "synthetic-call-id",
                    "arguments": argument_shape(read_arguments),
                },
            ],
            "follow_up_requests": [
                {"sequence": 2, **follow_up_1_shape},
                {"sequence": 3, **follow_up_2_shape},
            ],
            "sandbox_side_effects": side_effects,
            "request_counts": {
                "chat_requests": len(chat_requests),
                "streaming_requests": server.streaming_requests,
                "subsequent_chat_requests": len(chat_requests) - 1,
                "tool_result_requests": 2,
                "auxiliary_responses": 0,
            },
            "termination": {
                "completion_text": COMPLETION_TEXT,
                "completion_served": server.completion_served.is_set(),
                "no_fourth_request": True,
                "clean_exit": True,
            },
            "visible_state": {
                "terminal_marker": marker_present(visible, TERMINAL_MARKER),
                "read_file_marker": marker_present(visible, READ_MARKER),
                "completion_rendered": marker_present(visible, COMPLETION_TEXT),
                "returned_to_ready": marker_present(visible, "ready"),
                "no_busy_marker": not marker_present(visible, "Busy"),
                "cleanup": "Ctrl+C exited cleanly with terminal restored",
            },
        }
    finally:
        stop_process(pid, fd, reaped)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2.0)
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(sandbox, ignore_errors=True)


def write_report(report: dict[str, Any], path: Path | None, status: int) -> int:
    text = json.dumps(report, indent=2, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=8.0)
    arguments = parser.parse_args()
    binary = arguments.binary.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "command": "replay-tool-execution",
        "binary": str(binary),
        "dimensions": {"columns": COLUMNS, "rows": ROWS, "emulator": "direct PTY"},
        "cases": [],
        "passed": False,
    }
    try:
        if not binary.is_file():
            raise ReplayFailure("report", "binary", f"binary not found: {binary}")
        report["cases"] = [run_multi_hop_case(binary, arguments.timeout)]
        report["passed"] = True
    except (OSError, ReplayFailure, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        report["failure"] = error.as_dict() if isinstance(error, ReplayFailure) else {"message": str(error)}
        return write_report(report, arguments.report.resolve() if arguments.report else None, 1)
    return write_report(report, arguments.report.resolve() if arguments.report else None, 0)


if __name__ == "__main__":
    raise SystemExit(main())
