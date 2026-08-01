#!/usr/bin/env python3
"""Probe Hermes OSC52 empty and malformed-response boundaries in a direct PTY."""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

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
    query_position,
    spawn,
    stop,
    wait_for,
    write_bytes,
)


ROWS = 40
OSC52_QUERY = b"\x1b]52;c;?\x07"
NATIVE_ARGUMENTS = "-selection clipboard -out"


CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "empty-payload",
        "response": b"\x1b]52;c;\x07",
        "response_description": "BEL-terminated OSC52 response with an empty payload",
    },
    {
        "id": "query-marker-payload",
        "response": b"\x1b]52;c;?\x07",
        "response_description": "BEL-terminated OSC52 query marker returned as data",
    },
    {
        "id": "invalid-base64",
        "response": b"\x1b]52;c;%%%not-base64%%%\x07",
        "response_description": "BEL-terminated OSC52 response with invalid base64",
    },
    {
        "id": "invalid-target",
        "response": b"\x1b]52;x;" + base64.b64encode(b"wrong-selection") + b"\x07",
        "response_description": "BEL-terminated OSC52 response with an unsupported selection",
    },
    {
        "id": "unterminated-response",
        "response": b"\x1b]52;c;" + base64.b64encode(b"unterminated") ,
        "response_description": "OSC52 response without BEL or ST termination",
    },
)


def wait_for_optional(
    pid: int,
    fd: int,
    buffer: bytes,
    case: str,
    step: str,
    predicate: Any,
    timeout: float,
) -> tuple[bytes, bool]:
    try:
        return wait_for(pid, fd, buffer, case, step, predicate, timeout), True
    except ProbeFailure as error:
        if not error.message.startswith("timed out after"):
            raise
        return buffer, False


def finish_process(pid: int, fd: int, buffer: bytes, timeout: float) -> tuple[bytes, bool]:
    if not child_status(pid)[0]:
        try:
            write_bytes(fd, b"\x03")
            buffer = drain(pid, fd, buffer, 0.2)
        except OSError:
            pass
    if not child_status(pid)[0]:
        try:
            write_bytes(fd, b"\x03")
            buffer = drain(pid, fd, buffer, 0.2)
        except OSError:
            pass
    deadline = time.monotonic() + timeout
    while not child_status(pid)[0] and time.monotonic() < deadline:
        buffer = drain(pid, fd, buffer, 0.05)
    return buffer, child_status(pid)[0]


def run_case(reference: Path, case: dict[str, Any], timeout: float) -> dict[str, Any]:
    case_id = str(case["id"])
    root = Path(tempfile.mkdtemp(prefix=f"had026-{case_id}-"))
    fake_bin = make_fake_xclip(root)
    home = root / "home"
    home.mkdir()
    native_log = root / "xclip.log"
    native_payload = f"native-{case_id}\n"
    pid, fd = spawn(reference, home, fake_bin, native_payload, native_log)
    buffer = b""
    response = bytes(case["response"])
    try:
        buffer = wait_for(pid, fd, buffer, case_id, "startup", lambda current: contains(current, "Hermes Agent"), timeout)
        draft = f"boundary-{case_id}"
        write_bytes(fd, draft.encode("utf-8"))
        buffer = wait_for(pid, fd, buffer, case_id, "draft", lambda current: contains(current, draft), timeout)
        start = len(buffer)
        write_bytes(fd, b"\x16")
        buffer = wait_for(pid, fd, buffer, case_id, "osc52-query", lambda current: OSC52_QUERY in current[start:], timeout)
        query_at = query_position(buffer, start)
        response_at = query_at + len(OSC52_QUERY)
        write_bytes(fd, response)
        buffer, barrier_observed = wait_for_optional(
            pid,
            fd,
            buffer,
            case_id,
            "osc52-flush",
            lambda current: DA1_SENTINEL in current[response_at:],
            timeout,
        )
        barrier_count = max(1, buffer.count(DA1_SENTINEL)) if barrier_observed else 0
        if barrier_observed:
            write_bytes(fd, DA1_RESPONSE * barrier_count)

        native_marker = native_payload.rstrip("\n")
        buffer, fallback_observed = wait_for_optional(
            pid,
            fd,
            buffer,
            case_id,
            "native-fallback",
            lambda current: contains(current, native_marker),
            timeout,
        )
        provider_log = native_log.read_text(encoding="utf-8") if native_log.exists() else ""
        process_buffer, exited = finish_process(pid, fd, buffer, timeout)
        normalized_tail = normalize(process_buffer)[-2000:]
        outcome = "native-fallback" if fallback_observed and provider_log == NATIVE_ARGUMENTS else "unknown"
        return {
            "id": case_id,
            "description": case["response_description"],
            "draft": draft,
            "input_sequence": [
                {"kind": "text", "value": draft, "bytes_hex": draft.encode("utf-8").hex(" ")},
                {"kind": "key", "value": "Ctrl+V", "bytes_hex": "16"},
            ],
            "terminal_response": {
                "osc52_query_bytes_hex": OSC52_QUERY.hex(" "),
                "osc52_response_bytes_hex": response.hex(" "),
                "da1_sentinel_bytes_hex": DA1_SENTINEL.hex(" "),
                "da1_response_bytes_hex": DA1_RESPONSE.hex(" "),
                "query_offset": query_at,
                "da1_barriers_answered": barrier_count,
            },
            "output": {
                "status": "ready" if outcome == "native-fallback" else "unknown",
                "outcome": outcome,
                "submission": "not submitted" if "musing" not in normalized_tail else "unknown",
                "provider_order": "native provider after OSC52 response boundary" if outcome == "native-fallback" else "unknown",
                "native_provider": "xclip" if provider_log == NATIVE_ARGUMENTS else "not observed",
                "native_provider_arguments": provider_log,
                "native_payload": native_payload,
                "screen_markers": [draft, native_marker] if fallback_observed else [draft],
                "screen_absent_markers": ["Ctrl+C to interrupt"],
                "cleanup": "clean exit after bounded probe" if exited else "process required termination",
            },
            "screen_tail": normalized_tail,
        }
    finally:
        stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0026",
        "reference_observation": "OBS-0024",
        "reference": str(reference),
        "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY with raw bytes"},
        "cases": [],
        "passed": False,
    }
    try:
        for case in CASES:
            report["cases"].append(run_case(reference, case, args.timeout))
        report["unknowns"] = [
            case["id"]
            for case in report["cases"]
            if case["output"]["outcome"] == "unknown"
        ]
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        report["failure"] = error.as_dict() if isinstance(error, ProbeFailure) else str(error)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
