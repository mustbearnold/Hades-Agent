#!/usr/bin/env python3
"""Replay Hades bare-SSH OSC52-first clipboard behavior in a direct PTY."""

from __future__ import annotations

import argparse
import base64
import errno
import fcntl
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import sys
import tempfile
import termios
import time
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "tests/fixtures/parity/OBS-0025-hades-osc52-clipboard.json"
DEFAULT_BINARY = ROOT / "target/debug/hades"
ANSI_SEQUENCE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[()][0-2A-Z])")
COLUMNS = 120
ROWS = 40
OSC52_QUERY = b"\x1b]52;c;?\x07"
DA1_QUERY = b"\x1b[c"
DA1_RESPONSE = b"\x1b[?62c"


class Osc52ReplayFailure(RuntimeError):
    def __init__(self, case: str, step: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.case = case
        self.step = step
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {"case": self.case, "step": self.step, "message": self.message, **self.details}


def emit_report(report: dict[str, Any], path: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


def normalize(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").replace("\r", "")
    return ANSI_SEQUENCE.sub("", text).replace("\x08", "")


class Screen:
    """Small ANSI screen model for assertions when PTY output is diff-rendered."""

    def __init__(self) -> None:
        self.rows = [[" "] * COLUMNS for _ in range(ROWS)]
        self.row = 0
        self.column = 0
        self.saved = (0, 0)

    def clear(self) -> None:
        self.rows = [[" "] * COLUMNS for _ in range(ROWS)]
        self.row = 0
        self.column = 0

    def write(self, character: str) -> None:
        if not character:
            return
        if character == "\n":
            self.row = min(ROWS - 1, self.row + 1)
            return
        if character == "\r":
            self.column = 0
            return
        if character == "\b":
            self.column = max(0, self.column - 1)
            return
        if character == "\t":
            self.column = min(COLUMNS - 1, ((self.column // 8) + 1) * 8)
            return
        if ord(character) < 0x20 or ord(character) == 0x7F:
            return
        self.rows[self.row][self.column] = character
        if self.column == COLUMNS - 1:
            self.column = 0
            self.row = min(ROWS - 1, self.row + 1)
        else:
            self.column += 1

    def csi(self, body: bytes, final: int) -> None:
        private = body.startswith(b"?")
        values = body[1:] if private else body
        parameters: list[int] = []
        for value in values.split(b";") if values else []:
            try:
                parameters.append(int(value) if value else 0)
            except ValueError:
                parameters.append(0)

        def parameter(index: int, default: int = 1) -> int:
            value = parameters[index] if index < len(parameters) else 0
            return value or default

        if final in (ord("H"), ord("f")):
            self.row = max(0, min(ROWS - 1, parameter(0) - 1))
            self.column = max(0, min(COLUMNS - 1, parameter(1) - 1))
        elif final == ord("J"):
            if parameter(0, 0) in (0, 2):
                self.rows = [[" "] * COLUMNS for _ in range(ROWS)]
        elif final == ord("K"):
            for column in range(self.column, COLUMNS):
                self.rows[self.row][column] = " "
        elif final == ord("A"):
            self.row = max(0, self.row - parameter(0))
        elif final == ord("B"):
            self.row = min(ROWS - 1, self.row + parameter(0))
        elif final == ord("C"):
            self.column = min(COLUMNS - 1, self.column + parameter(0))
        elif final == ord("D"):
            self.column = max(0, self.column - parameter(0))
        elif final == ord("s"):
            self.saved = (self.row, self.column)
        elif final == ord("u"):
            self.row, self.column = self.saved
        elif private and final in (ord("h"), ord("l")) and 1049 in parameters:
            self.clear()

    def feed(self, raw: bytes) -> None:
        index = 0
        while index < len(raw):
            byte = raw[index]
            if byte == 0x1B and index + 1 < len(raw):
                next_byte = raw[index + 1]
                if next_byte == ord("["):
                    end = index + 2
                    while end < len(raw) and not (0x40 <= raw[end] <= 0x7E):
                        end += 1
                    if end >= len(raw):
                        break
                    self.csi(raw[index + 2 : end], raw[end])
                    index = end + 1
                    continue
                if next_byte == ord("]"):
                    end = index + 2
                    while end < len(raw) and raw[end] not in (0x07,):
                        if raw[end] == 0x1B and end + 1 < len(raw) and raw[end + 1] == ord("\\"):
                            end += 1
                            break
                        end += 1
                    index = min(len(raw), end + 1)
                    continue
                if next_byte in (ord("("), ord(")")):
                    index += 3
                    continue
                if next_byte in (ord("7"), ord("8")):
                    if next_byte == ord("7"):
                        self.saved = (self.row, self.column)
                    else:
                        self.row, self.column = self.saved
                    index += 2
                    continue
                index += 2
                continue
            if byte < 0x80:
                self.write(chr(byte))
                index += 1
                continue
            width = 1 if byte < 0xE0 else 2 if byte < 0xF0 else 3 if byte < 0xF8 else 4
            text = raw[index : index + width].decode("utf-8", errors="replace")
            self.write(text[0])
            index += width

    def text(self) -> str:
        return "\n".join("".join(row).rstrip() for row in self.rows)


def modeled_screen_text(raw: bytes) -> str:
    screen = Screen()
    screen.feed(raw)
    return screen.text()


def contains_marker(raw: bytes, marker: str) -> bool:
    text = modeled_screen_text(raw)
    compact_text = "".join(text.split()).lower()
    compact_marker = "".join(marker.split()).lower()
    raw_text = normalize(raw)
    compact_raw = "".join(raw_text.split()).lower()
    return (
        marker in text
        or compact_marker in compact_text
        or marker in raw_text
        or compact_marker in compact_raw
    )


def read_available(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        try:
            chunk = os.read(fd, 65_536)
        except OSError as error:
            if error.errno in (errno.EAGAIN, errno.EIO):
                break
            raise
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def child_status(pid: int) -> tuple[bool, int | None]:
    try:
        waited_pid, status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True, None
    if waited_pid == 0:
        return False, None
    return True, status


def wait_for(
    pid: int,
    fd: int,
    buffer: bytes,
    case: str,
    step: str,
    predicate: Callable[[bytes], bool],
    timeout: float,
) -> bytes:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(buffer):
            return buffer
        exited, status = child_status(pid)
        if exited:
            buffer += read_available(fd)
            if predicate(buffer):
                return buffer
            raise Osc52ReplayFailure(
                case,
                step,
                "process exited before the PTY assertion",
                {"exit_status": status, "screen_tail": normalize(buffer)[-2000:]},
            )
        readable, _, _ = select.select([fd], [], [], min(0.05, max(0.0, deadline - time.monotonic())))
        if readable:
            buffer += read_available(fd)
    raise Osc52ReplayFailure(
        case,
        step,
        f"timed out after {timeout:.1f}s",
        {
            "screen_tail": normalize(buffer)[-2000:],
            "modeled_screen_tail": modeled_screen_text(buffer)[-2000:],
            "raw_tail_hex": buffer[-512:].hex(" "),
        },
    )


def write_bytes(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        offset += os.write(fd, payload[offset:])


def set_window_size(fd: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLUMNS, 0, 0))


def create_xclip(provider_dir: Path, payload_path: Path, log_path: Path) -> None:
    provider_dir.mkdir(parents=True, exist_ok=True)
    xclip = provider_dir / "xclip"
    xclip.write_text(
        "#!{python}\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['HADES_CLIPBOARD_LOG']).write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n"
        "sys.stdout.buffer.write(Path(os.environ['HADES_CLIPBOARD_PAYLOAD']).read_bytes())\n".format(
            python=sys.executable
        ),
        encoding="utf-8",
    )
    xclip.chmod(0o755)
    payload_path.touch()
    log_path.touch()


def spawn(
    binary: Path,
    home: Path,
    provider_dir: Path,
    payload_path: Path,
    log_path: Path,
    multiplexer_marker: str | None = None,
) -> tuple[int, int]:
    pid, fd = pty.fork()
    if pid == 0:
        environment = os.environ.copy()
        environment.update(
            {
                "TERM": "xterm-256color",
                "HERMES_HOME": str(home),
                "HOME": str(home),
                "HADES_PROVIDER_BASE_URL": "http://127.0.0.1:8765/v1",
                "PATH": f"{provider_dir}{os.pathsep}{environment.get('PATH', '')}",
                "HADES_CLIPBOARD_PAYLOAD": str(payload_path),
                "HADES_CLIPBOARD_LOG": str(log_path),
                "SSH_TTY": "/dev/pts/999",
            }
        )
        for key in (
            "SSH_CONNECTION",
            "SSH_CLIENT",
            "TMUX",
            "STY",
            "WAYLAND_DISPLAY",
            "WSL_INTEROP",
            "WSL_DISTRO_NAME",
        ):
            environment.pop(key, None)
        if multiplexer_marker == "TMUX":
            environment["TMUX"] = "/tmp/tmux-999/default,123,0"
        elif multiplexer_marker == "STY":
            environment["STY"] = "1234.pts-0.host"
        os.execve(str(binary), [str(binary)], environment)

    set_window_size(fd)
    os.set_blocking(fd, False)
    return pid, fd


def stop_child(pid: int, fd: int) -> None:
    exited, _ = child_status(pid)
    if not exited:
        try:
            os.kill(pid, signal.SIGTERM)
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


def load_contract(path: Path) -> dict[str, Any]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Osc52ReplayFailure("contract", "load", str(error)) from error
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise Osc52ReplayFailure("contract", "load", "unsupported OSC52 contract")
    steps = contract.get("steps")
    if not isinstance(steps, list) or not steps:
        raise Osc52ReplayFailure("contract", "load", "steps must be a non-empty array")
    ids = {step.get("id") for step in steps if isinstance(step, dict)}
    legacy_ids = {"osc52-response", "osc52-native-timeout-control"}
    boundary_ids = {
        "osc52-empty-payload",
        "osc52-query-marker-payload",
        "osc52-invalid-base64",
        "osc52-invalid-target",
        "osc52-unterminated-response",
    }
    st_ids = {
        "osc52-valid-st-response",
        "osc52-empty-st-response",
        "osc52-invalid-base64-st-response",
    }
    multiplexer_ids = {
        "osc52-tmux-direct-response",
        "osc52-tmux-da1-fallback",
        "osc52-sty-direct-response",
        "osc52-sty-da1-fallback",
    }
    if ids == legacy_ids:
        return contract
    if ids == boundary_ids and all(
        isinstance(step, dict) and isinstance(step.get("osc52_response_bytes_hex"), str)
        for step in steps
    ):
        return contract
    if ids == st_ids and all(
        isinstance(step, dict)
        and isinstance(step.get("osc52_response_bytes_hex"), str)
        and step.get("expected_outcome") in {"osc52-response", "native-fallback"}
        for step in steps
    ):
        return contract
    if ids == multiplexer_ids and all(
        isinstance(step, dict)
        and step.get("multiplexer_marker") in {"TMUX", "STY"}
        and isinstance(step.get("wrapped_query_bytes_hex"), str)
        and step.get("expected_outcome") in {"osc52-response", "native-fallback"}
        for step in steps
    ):
        return contract
    raise Osc52ReplayFailure(
        "contract",
        "load",
        f"step ids must be {sorted(legacy_ids)}, {sorted(boundary_ids)}, {sorted(st_ids)}, or {sorted(multiplexer_ids)}",
    )


def run_case(binary: Path, case: dict[str, Any], timeout: float, ordinal: int) -> dict[str, Any]:
    case_id = case["id"]
    home = Path(tempfile.mkdtemp(prefix=f"had025-{case_id}-{ordinal}-"))
    provider_dir = home / "bin"
    payload_path = home / "clipboard.payload"
    log_path = home / "clipboard.args"
    payload_path.write_bytes(case["native_payload"].encode("utf-8"))
    create_xclip(provider_dir, payload_path, log_path)
    pid: int | None = None
    fd: int | None = None
    buffer = b""
    try:
        multiplexer_marker = case.get("multiplexer_marker")
        wrapped_query = (
            bytes.fromhex(case["wrapped_query_bytes_hex"])
            if "wrapped_query_bytes_hex" in case
            else OSC52_QUERY
        )
        pid, fd = spawn(binary, home, provider_dir, payload_path, log_path, multiplexer_marker)
        startup_markers = ("Hades Agent", "Underworld", "Available Tools", "Available Skills")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case_id,
            "startup",
            lambda current: all(contains_marker(current, marker) for marker in startup_markers),
            timeout,
        )
        draft = case["draft"]
        write_bytes(fd, draft.encode("utf-8"))
        buffer = wait_for(pid, fd, buffer, case_id, "draft", lambda current: contains_marker(current, draft), timeout)
        start = len(buffer)
        write_bytes(fd, b"\x16")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case_id,
            "osc52-query",
            lambda current: wrapped_query in current[start:],
            timeout,
        )
        query_at = buffer.find(wrapped_query, start)
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case_id,
            "da1-query",
            lambda current: DA1_QUERY in current[query_at + len(wrapped_query) :],
            timeout,
        )
        da1_at = buffer.find(DA1_QUERY, query_at + len(wrapped_query))

        if case_id == "osc52-response":
            response_payload = case["osc52_payload"]
            response = b"\x1b]52;c;" + base64.b64encode(response_payload.encode("utf-8")) + b"\x07"
            write_bytes(fd, response)
            write_bytes(fd, DA1_RESPONSE)
            buffer = wait_for(
                pid,
                fd,
                buffer,
                case_id,
                "remote-text",
                lambda current: all(contains_marker(current, marker) for marker in case["screen_markers"]),
                timeout,
            )
            if log_path.read_text(encoding="utf-8"):
                raise Osc52ReplayFailure(case_id, "provider-order", "native xclip ran after usable OSC52 text")
            outcome = {
                "status": "passed",
                "path": "OSC52 response won before native provider",
                "osc52_query_bytes_hex": OSC52_QUERY.hex(" "),
                "wrapped_query_bytes_hex": wrapped_query.hex(" "),
                "osc52_response_bytes_hex": response.hex(" "),
                "da1_query_bytes_hex": DA1_QUERY.hex(" "),
                "da1_response_bytes_hex": DA1_RESPONSE.hex(" "),
                "native_provider": "not invoked",
            }
        elif "osc52_response_bytes_hex" in case:
            response = bytes.fromhex(case["osc52_response_bytes_hex"])
            write_bytes(fd, response)
            write_bytes(fd, DA1_RESPONSE)
            expected_outcome = case.get("expected_outcome", "native-fallback")
            buffer = wait_for(
                pid,
                fd,
                buffer,
                case_id,
                "response-outcome",
                lambda current: all(contains_marker(current, marker) for marker in case["screen_markers"]),
                timeout,
            )
            provider_arguments = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            if expected_outcome == "osc52-response":
                if provider_arguments:
                    raise Osc52ReplayFailure(case_id, "provider-order", "native xclip ran after usable ST OSC52 text")
                outcome = {
                    "status": "passed",
                    "path": (
                        f"{multiplexer_marker} passthrough OSC52 response won before native provider"
                        if multiplexer_marker
                        else "ST-terminated OSC52 response won before native provider"
                    ),
                    "osc52_query_bytes_hex": OSC52_QUERY.hex(" "),
                    "wrapped_query_bytes_hex": wrapped_query.hex(" "),
                    "osc52_response_bytes_hex": response.hex(" "),
                    "da1_query_bytes_hex": DA1_QUERY.hex(" "),
                    "da1_response_bytes_hex": DA1_RESPONSE.hex(" "),
                    "native_provider": "not invoked",
                }
            else:
                if provider_arguments != "-selection clipboard -out":
                    raise Osc52ReplayFailure(case_id, "provider-order", f"unexpected native provider log: {provider_arguments!r}")
                outcome = {
                    "status": "passed",
                    "path": (
                        f"{multiplexer_marker} passthrough OSC52 response fell back to native provider"
                        if multiplexer_marker
                        else "Malformed or empty OSC52 response fell back to native provider"
                    ),
                    "osc52_query_bytes_hex": OSC52_QUERY.hex(" "),
                    "wrapped_query_bytes_hex": wrapped_query.hex(" "),
                    "osc52_response_bytes_hex": response.hex(" "),
                    "da1_query_bytes_hex": DA1_QUERY.hex(" "),
                    "da1_response_bytes_hex": DA1_RESPONSE.hex(" "),
                    "native_provider": "xclip",
                    "native_provider_arguments": provider_arguments,
                }
        else:
            write_bytes(fd, DA1_RESPONSE)
            buffer = wait_for(
                pid,
                fd,
                buffer,
                case_id,
                "native-fallback",
                lambda current: all(contains_marker(current, marker) for marker in case["screen_markers"]),
                timeout,
            )
            provider_arguments = log_path.read_text(encoding="utf-8")
            if provider_arguments != "-selection clipboard -out":
                raise Osc52ReplayFailure(case_id, "provider-order", f"unexpected native provider log: {provider_arguments!r}")
            outcome = {
                "status": "passed",
                "path": (
                    f"{multiplexer_marker} passthrough DA1 barrier acknowledged, then native provider fallback ran"
                    if multiplexer_marker
                    else "DA1 barrier acknowledged, then native provider fallback ran"
                ),
                "osc52_query_bytes_hex": OSC52_QUERY.hex(" "),
                "wrapped_query_bytes_hex": wrapped_query.hex(" "),
                "osc52_response": "not sent",
                "da1_query_bytes_hex": DA1_QUERY.hex(" "),
                "da1_response_bytes_hex": DA1_RESPONSE.hex(" "),
                "native_provider": "xclip",
                "native_provider_arguments": provider_arguments,
            }

        for marker in case.get("screen_absent_markers", []):
            if contains_marker(buffer, marker):
                raise Osc52ReplayFailure(case_id, "screen", f"unexpected marker: {marker}")

        if child_status(pid)[0]:
            raise Osc52ReplayFailure(case_id, "ready-state", "process exited before cleanup")
        write_bytes(fd, b"\x03")
        buffer = wait_for(pid, fd, buffer, case_id, "exit", lambda _current: child_status(pid)[0], timeout)
        return {
            "id": case_id,
            "status": "passed",
            "draft": draft,
            "ssh_marker": "SSH_TTY=/dev/pts/999",
            "multiplexer_marker": multiplexer_marker,
            "input_bytes_hex": [draft.encode("utf-8").hex(" "), "16"],
            "query_offset": query_at,
            "da1_query_offset": da1_at,
            "outcome": outcome,
            "screen_markers": case["screen_markers"],
            "screen_absent_markers": case.get("screen_absent_markers", []),
            "capture": "direct PTY with TIOCSWINSZ 120x40",
        }
    finally:
        if pid is not None and fd is not None:
            stop_child(pid, fd)
        shutil.rmtree(home, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=5.0)
    arguments = parser.parse_args()
    binary = arguments.binary.resolve()
    contract_path = arguments.contract.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "command": "replay-osc52-clipboard",
        "passed": False,
        "binary": str(binary),
        "contract": str(contract_path),
        "checks": [],
    }

    try:
        if not binary.is_file():
            raise Osc52ReplayFailure("input", "binary", f"binary not found: {binary}")
        contract = load_contract(contract_path)
        report["contract_observation"] = contract["observation_id"]
        report["reference_observation"] = contract.get("reference_observation")
        report["dimensions"] = contract["reference"]["terminal"]
        for ordinal, case in enumerate(contract["steps"], start=1):
            report["checks"].append(run_case(binary, case, arguments.timeout, ordinal))
        report["passed"] = True
    except Osc52ReplayFailure as error:
        report["failure"] = error.as_dict()
    except (OSError, TypeError, ValueError, KeyError) as error:
        report["failure"] = {"case": "report", "step": "runtime", "message": str(error)}

    try:
        emit_report(report, arguments.report.resolve() if arguments.report else None)
    except OSError as error:
        print(json.dumps({"passed": False, "error": f"could not write report: {error}"}))
        return 2
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
