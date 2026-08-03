#!/usr/bin/env python3
"""Capture Hermes terminal styling at the pinned reference commit."""

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
import sys
import tempfile
import termios
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


DEFAULT_REFERENCE = Path("/tmp/hades-hermes-ref-X3bLd0")
COLUMNS = 120
ROWS = 40
SOURCE_COMMIT = "e444d165807f489b5c1ab8e4a612c8d09c2e67a2"
BASE_URL = "http://127.0.0.1:8765/v1"
SENSITIVE_ENV_PARTS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "ACCESS_KEY")
STYLE_SEQUENCE = re.compile(rb"\x1b\[[0-9:;?]*m")
ANSI_SEQUENCE = re.compile(
    rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[()][0-2A-Z])"
)
Predicate = Callable[[bytes], bool]


class ProbeFailure(RuntimeError):
    """Raised when a deterministic reference assertion fails."""

    def __init__(self, case: str, step: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.case = case
        self.step = step
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {"case": self.case, "step": self.step, "message": self.message, **self.details}


@dataclass(frozen=True)
class Style:
    fg: str = "default"
    bg: str = "default"
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False
    strike: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "fg": self.fg,
            "bg": self.bg,
            "bold": self.bold,
            "dim": self.dim,
            "italic": self.italic,
            "underline": self.underline,
            "reverse": self.reverse,
            "strike": self.strike,
        }


DEFAULT_STYLE = Style()


@dataclass
class Cell:
    char: str = " "
    style: Style = DEFAULT_STYLE


def color_name(value: int, foreground: bool) -> str:
    if 30 <= value <= 37:
        return f"ansi({value - 30})"
    if 40 <= value <= 47:
        return f"ansi({value - 40})"
    if 90 <= value <= 97:
        return f"ansi({value - 90 + 8})"
    if 100 <= value <= 107:
        return f"ansi({value - 100 + 8})"
    return "default" if foreground else "default"


def extended_color(values: list[int], index: int) -> tuple[str, int]:
    if index >= len(values):
        return "default", index
    mode = values[index]
    if mode == 5 and index + 1 < len(values):
        return f"indexed({values[index + 1]})", index + 2
    if mode == 2 and index + 3 < len(values):
        red, green, blue = values[index + 1 : index + 4]
        return f"rgb({red},{green},{blue})", index + 4
    return "default", index + 1


def apply_sgr(style: Style, params: list[int]) -> Style:
    if not params:
        params = [0]
    values = list(params)
    current = style
    index = 0
    while index < len(values):
        value = values[index]
        index += 1
        if value == 0:
            current = DEFAULT_STYLE
        elif value == 1:
            current = Style(**{**current.as_dict(), "bold": True})
        elif value == 2:
            current = Style(**{**current.as_dict(), "dim": True})
        elif value == 3:
            current = Style(**{**current.as_dict(), "italic": True})
        elif value == 4:
            current = Style(**{**current.as_dict(), "underline": True})
        elif value == 7:
            current = Style(**{**current.as_dict(), "reverse": True})
        elif value == 9:
            current = Style(**{**current.as_dict(), "strike": True})
        elif value == 22:
            current = Style(**{**current.as_dict(), "bold": False, "dim": False})
        elif value == 23:
            current = Style(**{**current.as_dict(), "italic": False})
        elif value == 24:
            current = Style(**{**current.as_dict(), "underline": False})
        elif value == 27:
            current = Style(**{**current.as_dict(), "reverse": False})
        elif value == 29:
            current = Style(**{**current.as_dict(), "strike": False})
        elif value == 39:
            current = Style(**{**current.as_dict(), "fg": "default"})
        elif value == 49:
            current = Style(**{**current.as_dict(), "bg": "default"})
        elif 30 <= value <= 37 or 90 <= value <= 97:
            current = Style(**{**current.as_dict(), "fg": color_name(value, True)})
        elif 40 <= value <= 47 or 100 <= value <= 107:
            current = Style(**{**current.as_dict(), "bg": color_name(value, False)})
        elif value == 38:
            color, index = extended_color(values, index)
            current = Style(**{**current.as_dict(), "fg": color})
        elif value == 48:
            color, index = extended_color(values, index)
            current = Style(**{**current.as_dict(), "bg": color})
    return current


class Screen:
    """Small terminal model for the ANSI screen state used by the probe."""

    def __init__(self, columns: int = COLUMNS, rows: int = ROWS):
        self.columns = columns
        self.rows = rows
        self.cells = [[Cell() for _ in range(columns)] for _ in range(rows)]
        self.x = 0
        self.y = 0
        self.style = DEFAULT_STYLE
        self.saved_cursor = (0, 0, DEFAULT_STYLE)

    def clear(self) -> None:
        self.cells = [[Cell() for _ in range(self.columns)] for _ in range(self.rows)]

    def erase_line(self, mode: int) -> None:
        if mode == 1:
            start, end = 0, min(self.columns, self.x + 1)
        elif mode == 2:
            start, end = 0, self.columns
        else:
            start, end = min(self.columns, self.x), self.columns
        for column in range(start, end):
            self.cells[self.y][column] = Cell()

    def erase_display(self, mode: int) -> None:
        if mode == 2 or mode == 3:
            self.clear()
        elif mode == 1:
            for row in range(0, self.y):
                self.cells[row] = [Cell() for _ in range(self.columns)]
            self.erase_line(1)
        else:
            for row in range(self.y + 1, self.rows):
                self.cells[row] = [Cell() for _ in range(self.columns)]
            self.erase_line(0)

    def put(self, char: str) -> None:
        if self.x >= self.columns:
            self.x = 0
            self.y = min(self.rows - 1, self.y + 1)
        if self.y < self.rows:
            self.cells[self.y][self.x] = Cell(char, self.style)
        width = 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        self.x = min(self.columns, self.x + width)

    def csi(self, body: str, final: str) -> None:
        private = body.startswith(("?", ">", "!"))
        raw = body[1:] if private else body
        params = []
        for value in raw.split(";") if raw else []:
            try:
                params.append(int(value or "0"))
            except ValueError:
                params.append(0)
        first = params[0] if params else 1
        if final == "m":
            self.style = apply_sgr(self.style, params)
        elif final in {"H", "f"}:
            self.y = max(0, min(self.rows - 1, (params[0] if params else 1) - 1))
            self.x = max(0, min(self.columns - 1, (params[1] if len(params) > 1 else 1) - 1))
        elif final == "A":
            self.y = max(0, self.y - first)
        elif final == "B":
            self.y = min(self.rows - 1, self.y + first)
        elif final == "C":
            self.x = min(self.columns, self.x + first)
        elif final == "D":
            self.x = max(0, self.x - first)
        elif final == "E":
            self.y = min(self.rows - 1, self.y + first)
            self.x = 0
        elif final == "F":
            self.y = max(0, self.y - first)
            self.x = 0
        elif final == "G":
            self.x = max(0, min(self.columns - 1, first - 1))
        elif final == "d":
            self.y = max(0, min(self.rows - 1, first - 1))
        elif final == "J":
            self.erase_display(first)
        elif final == "K":
            self.erase_line(first)
        elif final == "X":
            for column in range(self.x, min(self.columns, self.x + first)):
                self.cells[self.y][column] = Cell()
        elif final == "P":
            count = min(self.columns - self.x, first)
            row = self.cells[self.y]
            row[self.x : self.columns - count] = row[self.x + count :]
            row[self.columns - count :] = [Cell() for _ in range(count)]
        elif final == "@":
            count = min(self.columns - self.x, first)
            row = self.cells[self.y]
            row[self.x + count :] = row[self.x : self.columns - count]
            row[self.x : self.x + count] = [Cell() for _ in range(count)]
        elif final == "s":
            self.saved_cursor = (self.x, self.y, self.style)
        elif final == "u":
            self.x, self.y, self.style = self.saved_cursor

    def feed(self, raw: bytes) -> None:
        text = raw.decode("utf-8", errors="replace")
        index = 0
        while index < len(text):
            char = text[index]
            if char == "\x1b":
                if index + 1 >= len(text):
                    break
                next_char = text[index + 1]
                if next_char == "[":
                    end = index + 2
                    while end < len(text) and not ("@" <= text[end] <= "~"):
                        end += 1
                    if end >= len(text):
                        break
                    self.csi(text[index + 2 : end], text[end])
                    index = end + 1
                    continue
                if next_char == "]":
                    end = index + 2
                    while end < len(text) and text[end] not in {"\x07", "\x1b"}:
                        end += 1
                    if end < len(text) and text[end] == "\x1b" and end + 1 < len(text):
                        end += 1
                    index = min(len(text), end + 1)
                    continue
                index += 2
                continue
            if char in {"\r", "\n"}:
                if char == "\r":
                    self.x = 0
                else:
                    self.y = min(self.rows - 1, self.y + 1)
                index += 1
                continue
            if char == "\b":
                self.x = max(0, self.x - 1)
                index += 1
                continue
            if char == "\t":
                self.x = min(self.columns, ((self.x // 8) + 1) * 8)
                index += 1
                continue
            if ord(char) >= 0x20:
                self.put(char)
            index += 1

    def lines(self) -> list[str]:
        return ["".join(cell.char for cell in row) for row in self.cells]

    def marker_style(self, marker: str) -> dict[str, Any] | None:
        marker_lower = marker.lower()
        for row, line in enumerate(self.lines()):
            column = line.lower().find(marker_lower)
            if column >= 0:
                return {
                    "row": row + 1,
                    "column": column + 1,
                    "style": self.cells[row][column].style.as_dict(),
                }
        return None

    def inventory(self) -> list[dict[str, Any]]:
        counts: dict[Style, int] = {}
        for row in self.cells:
            for cell in row:
                if cell.char != " ":
                    counts[cell.style] = counts.get(cell.style, 0) + 1
        return [
            {"style": style.as_dict(), "visible_cell_count": count}
            for style, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].as_dict()["fg"]))
        ]


def set_window_size(fd: int, columns: int = COLUMNS, rows: int = ROWS) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))


def read_available(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        try:
            chunk = os.read(fd, 65_536)
        except OSError as error:
            if error.errno in {errno.EIO, errno.EAGAIN}:
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
    return waited_pid != 0, status if waited_pid else None


def normalized(raw: bytes) -> str:
    return ANSI_SEQUENCE.sub(b"", raw).decode("utf-8", errors="replace").replace("\r", "")


def contains_marker(raw: bytes, marker: str) -> bool:
    text = normalized(raw)
    compact_text = "".join(text.split()).lower()
    compact_marker = "".join(marker.split()).lower()
    return marker.lower() in text.lower() or compact_marker in compact_text


def contains_busy_interrupt(raw: bytes) -> bool:
    compact_text = "".join(normalized(raw).lower().split())
    # Hermes redraws the footer while the provider retries. A direct PTY can
    # capture that redraw with the ``in`` bytes omitted, so accept both the
    # complete and observed split form without accepting a generic busy label.
    return re.search(r"ctrl\+cto(?:interrupt|interupt|terrupt)", compact_text) is not None


def wait_for(pid: int, fd: int, buffer: bytes, case: str, step: str, predicate: Predicate, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(buffer):
            return buffer
        exited, status = child_status(pid)
        if exited:
            buffer += read_available(fd)
            if predicate(buffer):
                return buffer
            raise ProbeFailure(case, step, "Hermes exited before the PTY assertion", {
                "exit_status": status,
                "screen_tail": normalized(buffer)[-2000:],
            })
        readable, _, _ = select.select([fd], [], [], min(0.05, max(0.0, deadline - time.monotonic())))
        if readable:
            buffer += read_available(fd)
            if predicate(buffer):
                return buffer
    if predicate(buffer):
        return buffer
    raise ProbeFailure(case, step, f"timed out after {timeout:.1f}s", {"screen_tail": normalized(buffer)[-2000:]})


def drain(pid: int, fd: int, buffer: bytes, duration: float = 0.15) -> bytes:
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        if child_status(pid)[0]:
            return buffer + read_available(fd)
        readable, _, _ = select.select([fd], [], [], min(0.02, max(0.0, deadline - time.monotonic())))
        if readable:
            buffer += read_available(fd)
    return buffer


def write_bytes(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        offset += os.write(fd, payload[offset:])


def stop(pid: int, fd: int) -> None:
    if not child_status(pid)[0]:
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


def write_ready_config(home: Path) -> None:
    (home / "config.yaml").write_text(
        "model:\n"
        "  provider: custom\n"
        "  default: palette-model\n"
        f"  base_url: {BASE_URL}\n"
        "  api_key: palette-test-key\n"
        "custom_providers:\n"
        "  - name: palette-loopback\n"
        f"    base_url: {BASE_URL}\n"
        "    api_key: palette-test-key\n"
        "    model: palette-model\n",
        encoding="utf-8",
    )


def spawn(reference: Path, home: Path, configured: bool) -> tuple[int, int]:
    if configured:
        write_ready_config(home)
    pid, fd = pty.fork()
    if pid == 0:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not any(part in key.upper() for part in SENSITIVE_ENV_PARTS)
        }
        environment.update(
            {
                "TERM": "xterm-256color",
                "COLUMNS": str(COLUMNS),
                "LINES": str(ROWS),
                "HERMES_HOME": str(home),
                "HOME": str(home),
                "HERMES_TUI_DIR": str(reference / "ui-tui"),
                "HERMES_TUI_THEME": "dark",
                "HERMES_TUI_STARTUP_TIMEOUT_MS": "8000",
                "UV_NO_CONFIG": "1",
            }
        )
        for key in ("TMUX", "STY", "WAYLAND_DISPLAY", "WSL_INTEROP", "WSL_DISTRO_NAME"):
            environment.pop(key, None)
        os.chdir(reference)
        os.execvpe("uv", ["uv", "run", "hermes", "--tui"], environment)
    set_window_size(fd)
    os.set_blocking(fd, False)
    return pid, fd


def sgr_summary(raw: bytes) -> dict[str, Any]:
    matches = STYLE_SEQUENCE.findall(raw)
    counts: dict[bytes, int] = {}
    order: list[bytes] = []
    for match in matches:
        if match not in counts:
            order.append(match)
            counts[match] = 0
        counts[match] += 1
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_length": len(raw),
        "sgr_sequences": [
            {"bytes_hex": match.hex(" "), "count": counts[match]}
            for match in order
        ],
    }


def surface_record(raw: bytes, full_buffer: bytes, markers: list[str]) -> dict[str, Any]:
    screen = Screen()
    screen.feed(full_buffer)
    return {
        "raw_delta": sgr_summary(raw),
        "marker_styles": {marker: screen.marker_style(marker) for marker in markers},
        "style_inventory": screen.inventory(),
    }


def require_markers(buffer: bytes, markers: tuple[str, ...], case: str, step: str) -> None:
    text = normalized(buffer).lower()
    missing = [marker for marker in markers if marker.lower() not in text]
    if missing:
        raise ProbeFailure(case, step, "required text markers were not observed", {"missing": missing})


def run_ready_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "ready-and-interrupt"
    home = Path(tempfile.mkdtemp(prefix="had034-ready-"))
    pid, fd = spawn(reference, home, True)
    buffer = b""
    try:
        buffer = wait_for(pid, fd, buffer, case, "startup", lambda current: all(
            marker.lower() in normalized(current).lower()
            for marker in ("Hermes Agent", "Nous Research", "Available Tools", "Available Skills", "ready")
        ), timeout)
        startup_end = len(buffer)
        buffer = drain(pid, fd, buffer)
        startup = surface_record(buffer[:startup_end], buffer, [
            "Hermes Agent", "Nous Research", "Available Tools", "Available Skills", "ready"
        ])

        ready_start = len(buffer)
        write_bytes(fd, b"palette-ready")
        buffer = wait_for(pid, fd, buffer, case, "ready-composer", lambda current: "palette-ready" in normalized(current), timeout)
        buffer = drain(pid, fd, buffer)
        ready = surface_record(buffer[ready_start:], buffer, ["palette-ready", "ready", "mock-model"])

        busy_start = len(buffer)
        write_bytes(fd, b"\r")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "busy",
            contains_busy_interrupt,
            timeout,
        )
        buffer = drain(pid, fd, buffer, 0.05)
        busy = surface_record(buffer[busy_start:], buffer, ["musing", "mulling", "Ctrl+C to interrupt"])

        complete_start = len(buffer)
        write_bytes(fd, b"\x03")
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case,
            "interrupted",
            lambda current: contains_marker(current, "interrupted"),
            timeout,
        )
        buffer = drain(pid, fd, buffer)
        completed = surface_record(buffer[complete_start:], buffer, ["interrupted", "✓", "ready", "palette-ready"])

        write_bytes(fd, b"\x03")
        if not wait_for(pid, fd, buffer, case, "cleanup", lambda current: child_status(pid)[0], timeout):
            raise ProbeFailure(case, "cleanup", "Hermes did not exit")
        return {
            "id": case,
            "status": "passed",
            "configured_provider": "custom loopback at <loopback-url>",
            "surfaces": {"startup": startup, "ready": ready, "busy": busy, "interrupted": completed},
            "cleanup": "Ctrl+C interrupted the busy turn; a second Ctrl+C exited cleanly",
        }
    finally:
        stop(pid, fd)
        shutil.rmtree(home, ignore_errors=True)


def run_setup_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "setup-required"
    home = Path(tempfile.mkdtemp(prefix="had034-setup-"))
    pid, fd = spawn(reference, home, False)
    buffer = b""
    try:
        buffer = wait_for(pid, fd, buffer, case, "startup", lambda current: "Hermes Agent" in normalized(current), timeout)
        setup_start = len(buffer)
        write_bytes(fd, b"/help\r")
        buffer = wait_for(pid, fd, buffer, case, "setup-overlay", lambda current: "Setup Required" in normalized(current), timeout)
        buffer = drain(pid, fd, buffer)
        setup = surface_record(buffer[setup_start:], buffer, [
            "Setup Required", "model provider", "/model", "/setup", "Ctrl+C"
        ])
        write_bytes(fd, b"\x03")
        buffer = drain(pid, fd, buffer, 0.15)
        write_bytes(fd, b"\x03")
        if not wait_for(pid, fd, buffer, case, "cleanup", lambda current: child_status(pid)[0], timeout):
            raise ProbeFailure(case, "cleanup", "Hermes did not exit from setup-required")
        return {
            "id": case,
            "status": "passed",
            "configured_provider": "none",
            "surfaces": {"setup-required": setup},
            "cleanup": "two Ctrl+C presses exited cleanly from setup-required",
        }
    finally:
        stop(pid, fd)
        shutil.rmtree(home, ignore_errors=True)


def emit_report(report: dict[str, Any], path: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0034",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY raw bytes"},
        },
        "normalization": [
            "Reference checkout, synthetic HOME, HERMES_HOME, PTY paths, loopback URL, session IDs, timestamps, elapsed durations, and rotating prompt text are represented by placeholders or hashes.",
            "Raw terminal bytes are not copied into the fixture; exact SGR sequences are retained as hex bytes with counts and raw-surface hashes.",
            "Style inventories contain only terminal-cell attributes and counts for visible cells; transcript payloads and credentials are excluded.",
        ],
        "runtime": {"node": "22.22.2", "npm": "10.9.7", "python": "3.11.14", "uv": "0.12.1"},
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"].append(run_ready_case(reference, args.timeout))
        report["cases"].append(run_setup_case(reference, args.timeout))
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        report["failure"] = error.as_dict() if isinstance(error, ProbeFailure) else str(error)
    emit_report(report, args.report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
