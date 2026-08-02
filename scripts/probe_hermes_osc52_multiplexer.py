#!/usr/bin/env python3
"""Probe Hermes OSC52 query wrapping under synthetic TMUX and STY markers."""

from __future__ import annotations

import argparse
import base64
import fcntl
import json
import os
import pty
import select
import shutil
import struct
import sys
import tempfile
import termios
import time
from pathlib import Path
from typing import Any, Callable

from probe_hermes_osc52_clipboard import (
    COLUMNS,
    DA1_RESPONSE,
    DA1_SENTINEL,
    DEFAULT_REFERENCE,
    ProbeFailure,
    child_status,
    contains,
    drain,
    make_fake_xclip,
    normalize,
    read_available,
    stop,
    wait_for,
    write_bytes,
)


ROWS = 40
OSC52_QUERY = b"\x1b]52;c;?\x07"
OSC52_RESPONSE = b"\x1b]52;c;" + base64.b64encode(b"mux-remote  \nline-two\n\n") + b"\x07"
NATIVE_ARGUMENTS = "-selection clipboard -out"
BASE_URL = "http://127.0.0.1:8765/v1"
SYNTHETIC_KEY = "synthetic-probe-key"
SENSITIVE_ENV_PARTS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "ACCESS_KEY")
WRAPPED_QUERIES = {
    "TMUX": b"\x1bPtmux;\x1b\x1b]52;c;?\x07\x1b\\",
    "STY": b"\x1bP\x1b]52;c;?\x07\x1b\\",
}
MAX_CASE_ATTEMPTS = 3


CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "tmux-direct-response",
        "marker": "TMUX",
        "response": OSC52_RESPONSE,
        "description": "TMUX-wrapped OSC52 query followed by a directly supplied raw OSC52 response",
        "osc52_marker": "mux-remote",
        "expected_outcome": "osc52-response",
    },
    {
        "id": "tmux-da1-fallback",
        "marker": "TMUX",
        "response": None,
        "description": "TMUX-wrapped OSC52 query with no OSC52 response and DA1 fallback",
        "osc52_marker": None,
        "expected_outcome": "native-fallback",
    },
    {
        "id": "sty-direct-response",
        "marker": "STY",
        "response": OSC52_RESPONSE,
        "description": "GNU Screen-wrapped OSC52 query followed by a directly supplied raw OSC52 response",
        "osc52_marker": "mux-remote",
        "expected_outcome": "osc52-response",
    },
    {
        "id": "sty-da1-fallback",
        "marker": "STY",
        "response": None,
        "description": "GNU Screen-wrapped OSC52 query with no OSC52 response and DA1 fallback",
        "osc52_marker": None,
        "expected_outcome": "native-fallback",
    },
)


def spawn_with_marker(
    reference: Path,
    home: Path,
    fake_bin: Path,
    native_payload: str,
    native_log: Path,
    marker: str,
) -> tuple[int, int]:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        "model:\n"
        "  provider: custom\n"
        "  default: multiplexer-model\n"
        f"  base_url: {BASE_URL}\n"
        f"  api_key: {SYNTHETIC_KEY}\n"
        "custom_providers:\n"
        "  - name: multiplexer-loopback\n"
        f"    base_url: {BASE_URL}\n"
        f"    api_key: {SYNTHETIC_KEY}\n"
        "    model: multiplexer-model\n",
        encoding="utf-8",
    )
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
                "HERMES_HOME": str(home),
                "HOME": str(home),
                "PATH": f"{fake_bin}{os.pathsep}{environment.get('PATH', '')}",
                "HERMES_NATIVE_PAYLOAD": native_payload,
                "HERMES_NATIVE_LOG": str(native_log),
                "SSH_TTY": "/dev/pts/999",
                "UV_NO_CONFIG": "1",
            }
        )
        environment.pop("WAYLAND_DISPLAY", None)
        environment.pop("WSL_INTEROP", None)
        environment.pop("WSL_DISTRO_NAME", None)
        if marker == "TMUX":
            environment["TMUX"] = "/tmp/tmux-999/default,123,0"
            environment.pop("STY", None)
        else:
            environment["STY"] = "1234.pts-0.host"
            environment.pop("TMUX", None)
        os.chdir(reference)
        os.execvpe("uv", ["uv", "run", "hermes", "--tui"], environment)

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLUMNS, 0, 0))
    os.set_blocking(fd, False)
    return pid, fd


def wait_for_optional(
    pid: int,
    fd: int,
    buffer: bytes,
    case: str,
    step: str,
    predicate: Callable[[bytes], bool],
    timeout: float,
) -> tuple[bytes, bool]:
    try:
        return wait_for(pid, fd, buffer, case, step, predicate, timeout), True
    except ProbeFailure as error:
        if not error.message.startswith("timed out after"):
            raise
        return buffer, False


def finish_process(pid: int, fd: int, buffer: bytes, timeout: float) -> tuple[bytes, bool]:
    for _ in range(2):
        if child_status(pid)[0]:
            break
        try:
            write_bytes(fd, b"\x03")
            buffer = drain(pid, fd, buffer, 0.2)
        except OSError:
            break

    deadline = time.monotonic() + timeout
    while not child_status(pid)[0] and time.monotonic() < deadline:
        buffer = drain(pid, fd, buffer, 0.05)
    return buffer, child_status(pid)[0]


def wait_for_outcome_answering_da1(
    pid: int,
    fd: int,
    buffer: bytes,
    case: str,
    response_at: int,
    predicate: Callable[[bytes], bool],
    timeout: float,
) -> tuple[bytes, int, bool]:
    """Answer every DA1 barrier emitted after the clipboard query.

    Hermes can still be completing an earlier startup query batch when the
    clipboard query is sent. A single observed DA1 can therefore belong to
    that earlier batch; answer barriers incrementally so the clipboard flush
    cannot remain pending behind a startup race.
    """
    deadline = time.monotonic() + timeout
    barriers_answered = 0
    while time.monotonic() < deadline:
        barriers_observed = buffer[response_at:].count(DA1_SENTINEL)
        if barriers_observed > barriers_answered:
            write_bytes(fd, DA1_RESPONSE * (barriers_observed - barriers_answered))
            barriers_answered = barriers_observed
        if predicate(buffer):
            return buffer, barriers_answered, True
        exited, status = child_status(pid)
        if exited:
            buffer += read_available(fd)
            if predicate(buffer):
                return buffer, barriers_answered, True
            raise ProbeFailure(
                case,
                "response-outcome",
                "Hermes exited before the PTY assertion",
                {"exit_status": status, "da1_barriers_answered": barriers_answered},
            )
        readable, _, _ = select.select([fd], [], [], 0.05)
        if readable:
            buffer += read_available(fd)
    raise ProbeFailure(
        case,
        "response-outcome",
        f"timed out after {timeout:.1f}s",
        {"da1_barriers_answered": barriers_answered, "screen_tail": normalize(buffer)[-2000:]},
    )


def run_case(reference: Path, case: dict[str, Any], timeout: float) -> dict[str, Any]:
    case_id = str(case["id"])
    marker = str(case["marker"])
    root = Path(tempfile.mkdtemp(prefix=f"had030-{case_id}-"))
    fake_bin = make_fake_xclip(root)
    home = root / "home"
    home.mkdir()
    native_log = root / "xclip.log"
    native_payload = f"native-{case_id}\n"
    pid, fd = spawn_with_marker(reference, home, fake_bin, native_payload, native_log, marker)
    buffer = b""
    wrapped_query = WRAPPED_QUERIES[marker]
    response = case["response"]
    try:
        buffer = wait_for(pid, fd, buffer, case_id, "startup", lambda current: contains(current, "Hermes Agent"), timeout)
        draft = f"mux-boundary-{case_id}"
        write_bytes(fd, draft.encode("utf-8"))
        buffer = wait_for(pid, fd, buffer, case_id, "draft", lambda current: contains(current, draft), timeout)
        start = len(buffer)
        write_bytes(fd, b"\x16")
        buffer = wait_for(pid, fd, buffer, case_id, "wrapped-osc52-query", lambda current: wrapped_query in current[start:], timeout)
        query_at = buffer.find(wrapped_query, start)
        response_at = query_at + len(wrapped_query)
        if response is not None:
            write_bytes(fd, response)

        native_marker = native_payload.rstrip("\n")
        osc52_marker = case["osc52_marker"]
        buffer, barrier_count, outcome_observed = wait_for_outcome_answering_da1(
            pid,
            fd,
            buffer,
            case_id,
            response_at,
            lambda current: (osc52_marker is not None and contains(current, osc52_marker)) or contains(current, native_marker),
            timeout,
        )
        da1_at = buffer.find(DA1_SENTINEL, response_at)
        provider_arguments = native_log.read_text(encoding="utf-8") if native_log.exists() else ""
        osc52_observed = osc52_marker is not None and contains(buffer, osc52_marker)
        native_observed = contains(buffer, native_marker)
        if osc52_observed and provider_arguments:
            outcome = "ambiguous"
        elif osc52_observed:
            outcome = "osc52-response"
        elif native_observed and provider_arguments == NATIVE_ARGUMENTS:
            outcome = "native-fallback"
        elif outcome_observed:
            outcome = "unresolved-output"
        else:
            outcome = "timeout-or-unresolved"
        if outcome != case["expected_outcome"]:
            raise ProbeFailure(
                case_id,
                "response-outcome",
                f"expected {case['expected_outcome']}, observed {outcome}",
                {"native_provider_arguments": provider_arguments},
            )

        process_buffer, exited = finish_process(pid, fd, buffer, timeout)
        normalized_tail = normalize(process_buffer)[-2000:]
        return {
            "id": case_id,
            "description": case["description"],
            "multiplexer_marker": marker,
            "draft": draft,
            "ssh_marker": "SSH_TTY=/dev/pts/999",
            "input_sequence": [
                {"kind": "text", "value": draft, "bytes_hex": draft.encode("utf-8").hex(" ")},
                {"kind": "key", "value": "Ctrl+V", "bytes_hex": "16"},
            ],
            "terminal_response": {
                "osc52_query_bytes_hex": OSC52_QUERY.hex(" "),
                "wrapped_query_bytes_hex": wrapped_query.hex(" "),
                "osc52_response_bytes_hex": response.hex(" ") if response is not None else None,
                "da1_sentinel_bytes_hex": DA1_SENTINEL.hex(" "),
                "da1_response_bytes_hex": DA1_RESPONSE.hex(" "),
                "query_offset": query_at,
                "da1_query_offset": da1_at,
                "da1_barriers_answered": barrier_count,
            },
            "output": {
                "status": "ready" if outcome_observed else "unknown",
                "outcome": outcome,
                "provider_order": (
                    "direct OSC52 response before native provider"
                    if outcome == "osc52-response"
                    else "native provider after wrapped OSC52 query and DA1 barrier"
                    if outcome == "native-fallback"
                    else "unknown"
                ),
                "timing_boundary": (
                    "wrapped query observed before direct response; direct response supplied before DA1 response"
                    if outcome == "osc52-response"
                    else "wrapped query observed; two DA1 barriers answered before native provider"
                    if outcome == "native-fallback"
                    else "unknown"
                ),
                "native_provider": "xclip" if provider_arguments == NATIVE_ARGUMENTS else "not observed",
                "native_provider_arguments": provider_arguments,
                "native_payload": native_payload,
                "screen_markers": [draft, osc52_marker or native_marker],
                "screen_absent_markers": ["Ctrl+C to interrupt"] if "Ctrl+C to interrupt" not in normalized_tail else [],
                "submission": "not submitted" if "musing" not in normalized_tail else "unknown",
                "cleanup": "clean exit after bounded probe" if exited else "process required termination",
            },
            "screen_tail": normalized_tail,
        }
    finally:
        stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def run_case_with_retry(reference: Path, case: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Retry only the fresh-process PTY response race, without weakening assertions."""
    retry_history: list[dict[str, Any]] = []
    for attempt in range(1, MAX_CASE_ATTEMPTS + 1):
        try:
            result = run_case(reference, case, timeout)
            result["oracle_attempts"] = attempt
            if retry_history:
                result["retry_history"] = retry_history
            return result
        except ProbeFailure as error:
            retry_record = {
                "attempt": attempt,
                "step": error.step,
                "message": error.message,
                "da1_barriers_answered": error.details.get("da1_barriers_answered"),
                "native_provider_arguments": error.details.get("native_provider_arguments", ""),
            }
            retry_history.append(retry_record)
            if error.step != "response-outcome" or attempt == MAX_CASE_ATTEMPTS:
                error.details["retry_history"] = retry_history
                raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0030",
        "reference_observation": "OBS-0024",
        "reference": str(reference),
        "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY with raw bytes"},
        "cases": [],
        "passed": False,
    }
    try:
        for case in CASES:
            report["cases"].append(run_case_with_retry(reference, case, args.timeout))
        report["unknowns"] = [
            "The probe models the terminal response as a direct raw OSC52 response after the wrapper query; live tmux or GNU Screen daemons and outer-terminal forwarding were not exercised.",
            "Image/path payloads, gateway behavior, delayed or oversized responses, and concurrent input remain unknown.",
        ]
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        report["failure"] = error.as_dict() if isinstance(error, ProbeFailure) else str(error)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    print(serialized)
    if args.report is not None:
        report_path = args.report if args.report.is_absolute() else Path.cwd() / args.report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(serialized + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
