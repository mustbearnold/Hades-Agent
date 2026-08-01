#!/usr/bin/env python3
"""Probe Hermes OSC52 response handling when responses use ST termination."""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
import tempfile
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
    query_position,
    spawn,
    stop,
    wait_for,
    write_bytes,
)


ROWS = 40
OSC52_QUERY = b"\x1b]52;c;?\x07"
ST = b"\x1b\\"
NATIVE_ARGUMENTS = "-selection clipboard -out"


CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "valid-st-response",
        "response": b"\x1b]52;c;"
        + base64.b64encode(b"st-remote  \nline-two\n\n")
        + ST,
        "response_description": "ST-terminated OSC52 response with usable multiline text",
        "osc52_marker": "st-remote",
        "osc52_text": "st-remote  \nline-two",
        "screen_markers": ["st-remote", "line-two"],
        "expected_outcome": "osc52-response",
    },
    {
        "id": "empty-st-response",
        "response": b"\x1b]52;c;" + ST,
        "response_description": "ST-terminated OSC52 response with an empty payload",
        "osc52_marker": None,
        "osc52_text": None,
        "screen_markers": [],
        "expected_outcome": "native-fallback",
    },
    {
        "id": "invalid-base64-st-response",
        "response": b"\x1b]52;c;%%%not-base64%%%" + ST,
        "response_description": "ST-terminated OSC52 response with invalid base64",
        "osc52_marker": None,
        "osc52_text": None,
        "screen_markers": [],
        "expected_outcome": "native-fallback",
    },
)


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


def run_case(reference: Path, case: dict[str, Any], timeout: float) -> dict[str, Any]:
    case_id = str(case["id"])
    root = Path(tempfile.mkdtemp(prefix=f"had028-{case_id}-"))
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
        draft = f"st-boundary-{case_id}"
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
        osc52_marker = case["osc52_marker"]
        buffer, output_observed = wait_for_optional(
            pid,
            fd,
            buffer,
            case_id,
            "response-outcome",
            lambda current: (osc52_marker is not None and contains(current, osc52_marker)) or contains(current, native_marker),
            timeout,
        )
        provider_arguments = native_log.read_text(encoding="utf-8") if native_log.exists() else ""
        osc52_observed = osc52_marker is not None and contains(buffer, osc52_marker)
        native_observed = contains(buffer, native_marker)
        if osc52_observed and provider_arguments:
            outcome = "ambiguous"
        elif osc52_observed:
            outcome = "osc52-response"
        elif native_observed and provider_arguments == NATIVE_ARGUMENTS:
            outcome = "native-fallback"
        elif output_observed:
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
            "description": case["response_description"],
            "draft": draft,
            "ssh_marker": "SSH_TTY=/dev/pts/999",
            "input_sequence": [
                {"kind": "text", "value": draft, "bytes_hex": draft.encode("utf-8").hex(" ")},
                {"kind": "key", "value": "Ctrl+V", "bytes_hex": "16"},
            ],
            "terminal_response": {
                "osc52_query_bytes_hex": OSC52_QUERY.hex(" "),
                "osc52_response_bytes_hex": response.hex(" "),
                "da1_sentinel_bytes_hex": DA1_SENTINEL.hex(" "),
                "da1_response_bytes_hex": DA1_RESPONSE.hex(" "),
                "da1_barriers_answered": barrier_count,
            },
            "output": {
                "status": "ready" if output_observed else "unknown",
                "outcome": outcome,
                "osc52_text": case["osc52_text"] if outcome == "osc52-response" else None,
                "submission": "not submitted" if "musing" not in normalized_tail else "unknown",
                "provider_order": (
                    "OSC52 response before native provider"
                    if outcome == "osc52-response"
                    else "native provider after OSC52 response boundary"
                    if outcome == "native-fallback"
                    else "unknown"
                ),
                "native_provider": "xclip" if provider_arguments == NATIVE_ARGUMENTS else "not observed",
                "native_provider_arguments": provider_arguments,
                "native_payload": native_payload,
                "screen_markers": [draft, *(case["screen_markers"] or [native_marker])],
                "screen_absent_markers": ["Ctrl+C to interrupt"] if "Ctrl+C to interrupt" not in normalized_tail else [],
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
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0028",
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
            "Delayed responses after the 500 ms read race and oversized payloads were not exercised.",
            "BEL-terminated malformed and unterminated controls are covered by OBS-0026; this probe covers only ST-terminated valid, empty, and invalid-base64 responses.",
            "TMUX/STY passthrough wrapping, image/path clipboard behavior, gateway behavior, concurrent input, and Hades implementation parity remain separate unknowns.",
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
