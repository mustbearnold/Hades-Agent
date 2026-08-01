#!/usr/bin/env python3
"""Probe bounded Hermes OSC52 timing and decoded-payload controls."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import select
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
    OSC52_QUERY,
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
TIMEOUT_MS = 500
LARGE_DECODED_BYTES = 256 * 1024
OVERSIZED_DECODED_BYTES = 512 * 1024
NATIVE_ARGUMENTS = "-selection clipboard -out"
SOURCE_COMMIT = "e444d165807f489b5c1ab8e4a612c8d09c2e67a2"


def build_payload(label: str, size: int) -> bytes:
    prefix = f"{label}-start\n".encode("ascii")
    suffix = f"\n{label}-end\n\n".encode("ascii")
    if size <= len(prefix) + len(suffix):
        raise ValueError(f"payload size is too small for {label}: {size}")
    fill = bytes((ord(label[0]),)) * (size - len(prefix) - len(suffix))
    return prefix + fill + suffix


def write_nonblocking(fd: int, payload: bytes, deadline: float) -> float:
    """Write a bounded response through the non-blocking PTY master."""

    started = time.monotonic()
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(fd, payload[offset : offset + 65_536])
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeFailure(
                    "payload-write",
                    "osc52-response-write",
                    "bounded response did not reach the PTY before its deadline",
                    {"payload_bytes": len(payload), "written_bytes": offset},
                )
            select.select([], [fd], [], min(0.05, remaining))
            continue
        if written <= 0:
            raise ProbeFailure("payload-write", "osc52-response-write", "PTY write returned no progress")
        offset += written
    return (time.monotonic() - started) * 1000


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


def response_for(case_id: str) -> tuple[bytes, str, int, str]:
    if case_id == "response-before-timeout":
        payload = b"timing-before-remote  \nline-two\n\n"
        return (
            b"\x1b]52;c;" + base64.b64encode(payload) + b"\x07",
            "timing-before-remote",
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        )
    if case_id == "response-after-timeout":
        payload = b"timing-after-remote  \nline-two\n\n"
        return (
            b"\x1b]52;c;" + base64.b64encode(payload) + b"\x07",
            "timing-after-remote",
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        )
    if case_id == "large-response":
        payload = build_payload("large-response", LARGE_DECODED_BYTES)
        return (
            b"\x1b]52;c;" + base64.b64encode(payload) + b"\x07",
            "large-response-end",
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        )
    if case_id == "oversized-response":
        payload = build_payload("oversized-response", OVERSIZED_DECODED_BYTES)
        return (
            b"\x1b]52;c;" + base64.b64encode(payload) + b"\x07",
            "oversized-response-end",
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        )
    raise ValueError(f"unknown case: {case_id}")


CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "response-before-timeout",
        "description": "usable OSC52 text supplied at a 100 ms target delay",
        "expected_outcome": "osc52-response",
        "delay_target_ms": 100,
        "late": False,
    },
    {
        "id": "response-after-timeout",
        "description": "usable OSC52 text supplied only after Hermes emits its timeout flush",
        "expected_outcome": "native-fallback",
        "delay_target_ms": None,
        "late": True,
    },
    {
        "id": "large-response",
        "description": "bounded 256 KiB decoded OSC52 payload supplied immediately",
        "expected_outcome": "osc52-response",
        "delay_target_ms": 0,
        "late": False,
    },
    {
        "id": "oversized-response",
        "description": "bounded 512 KiB decoded OSC52 payload supplied immediately",
        "expected_outcome": "osc52-response",
        "delay_target_ms": 0,
        "late": False,
    },
)


def run_case(reference: Path, case: dict[str, Any], timeout: float) -> dict[str, Any]:
    case_id = str(case["id"])
    response, remote_marker, decoded_bytes, decoded_sha256 = response_for(case_id)
    root = Path(tempfile.mkdtemp(prefix=f"had032-{case_id}-"))
    fake_bin = make_fake_xclip(root)
    home = root / "home"
    home.mkdir()
    native_log = root / "xclip.log"
    native_payload = f"native-{case_id}\n"
    pid, fd = spawn(reference, home, fake_bin, native_payload, native_log)
    buffer = b""
    query_observed_at = 0.0
    response_sent_at = None
    sentinel_observed_at = None
    response_write_ms = None
    try:
        buffer = wait_for(pid, fd, buffer, case_id, "startup", lambda current: contains(current, "Hermes Agent"), timeout)
        draft = f"timing-boundary-{case_id}"
        write_bytes(fd, draft.encode("utf-8"))
        buffer = wait_for(pid, fd, buffer, case_id, "draft", lambda current: contains(current, draft), timeout)
        start = len(buffer)
        write_bytes(fd, b"\x16")
        buffer = wait_for(pid, fd, buffer, case_id, "osc52-query", lambda current: OSC52_QUERY in current[start:], timeout)
        query_at = query_position(buffer, start)
        response_at = query_at + len(OSC52_QUERY)
        query_observed_at = time.monotonic()

        if case["late"]:
            buffer = wait_for(
                pid,
                fd,
                buffer,
                case_id,
                "timeout-flush",
                lambda current: DA1_SENTINEL in current[response_at:],
                timeout,
            )
            sentinel_observed_at = time.monotonic()
            timeout_elapsed_ms = (sentinel_observed_at - query_observed_at) * 1000
            if timeout_elapsed_ms < TIMEOUT_MS * 0.8:
                raise ProbeFailure(
                    case_id,
                    "timeout-boundary",
                    "Hermes timeout flush arrived earlier than the bounded race control",
                    {"timeout_elapsed_ms": round(timeout_elapsed_ms, 3)},
                )
            response_sent_at = time.monotonic()
            response_write_ms = write_nonblocking(fd, response, time.monotonic() + timeout)
            late_response_elapsed_ms = (response_sent_at - query_observed_at) * 1000
        else:
            delay_target_ms = int(case["delay_target_ms"])
            target = query_observed_at + delay_target_ms / 1000
            remaining = target - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            response_sent_at = time.monotonic()
            response_write_ms = write_nonblocking(fd, response, query_observed_at + TIMEOUT_MS / 1000 * 0.9)
            response_elapsed_ms = (response_sent_at - query_observed_at) * 1000
            if response_elapsed_ms >= TIMEOUT_MS * 0.8:
                raise ProbeFailure(
                    case_id,
                    "timeout-boundary",
                    "response was not supplied early enough to isolate the payload control",
                    {"response_elapsed_ms": round(response_elapsed_ms, 3)},
                )
            buffer = wait_for(
                pid,
                fd,
                buffer,
                case_id,
                "flush",
                lambda current: DA1_SENTINEL in current[response_at:],
                timeout,
            )
            sentinel_observed_at = time.monotonic()

        # Hermes has a standing DA1 query in addition to the OSC52 flush
        # barrier, so answer every sentinel observed in the capture.
        barrier_count = max(1, buffer.count(DA1_SENTINEL))
        sentinel_elapsed_ms = (sentinel_observed_at - query_observed_at) * 1000 if sentinel_observed_at else None
        da1_at = buffer.find(DA1_SENTINEL, response_at)
        write_bytes(fd, DA1_RESPONSE * barrier_count)

        native_marker = native_payload.rstrip("\n")
        try:
            buffer = wait_for(
                pid,
                fd,
                buffer,
                case_id,
                "response-outcome",
                lambda current: contains(current, remote_marker) or contains(current, native_marker),
                timeout,
            )
        except ProbeFailure as error:
            probe_tail = drain(pid, fd, buffer, 0.2)
            raise ProbeFailure(
                case_id,
                "response-outcome",
                error.message,
                {
                    "native_provider_arguments": native_log.read_text(encoding="utf-8") if native_log.exists() else "",
                    "raw_tail_hex": probe_tail[-512:].hex(" "),
                    "normalized_tail": normalize(probe_tail)[-2000:],
                    "response_remote_marker": remote_marker,
                    "remote_marker_in_raw": remote_marker.encode("utf-8") in probe_tail,
                    "native_marker_in_raw": native_marker.encode("utf-8") in probe_tail,
                    "da1_sentinel_count": probe_tail[response_at:].count(DA1_SENTINEL),
                },
            ) from error
        provider_arguments = native_log.read_text(encoding="utf-8") if native_log.exists() else ""
        remote_observed = contains(buffer, remote_marker)
        native_observed = contains(buffer, native_marker)
        if remote_observed and provider_arguments:
            outcome = "ambiguous"
        elif remote_observed:
            outcome = "osc52-response"
        elif native_observed and provider_arguments == NATIVE_ARGUMENTS:
            outcome = "native-fallback"
        else:
            outcome = "unresolved-output"
        if outcome != case["expected_outcome"]:
            raise ProbeFailure(
                case_id,
                "response-outcome",
                f"expected {case['expected_outcome']}, observed {outcome}",
                {
                    "native_provider_arguments": provider_arguments,
                    "screen_tail": normalize(buffer)[-2000:],
                    "response_write_ms": response_write_ms,
                    "sentinel_elapsed_ms": sentinel_elapsed_ms,
                },
            )

        normalized_tail = normalize(buffer)[-2000:]
        if "Ctrl+C to interrupt" in normalized_tail or "musing" in normalized_tail.lower():
            raise ProbeFailure(case_id, "ready-state", "Hermes retained its busy state after the clipboard control")
        if outcome == "osc52-response" and native_observed:
            raise ProbeFailure(case_id, "provider-order", "native output appeared with a winning OSC52 response")
        process_buffer, exited = finish_process(pid, fd, buffer, timeout)
        if not exited:
            raise ProbeFailure(case_id, "cleanup", "Hermes did not exit after Ctrl+C")

        terminal_response: dict[str, Any] = {
            "osc52_query_bytes_hex": OSC52_QUERY.hex(" "),
            "da1_sentinel_bytes_hex": DA1_SENTINEL.hex(" "),
            "da1_response_bytes_hex": DA1_RESPONSE.hex(" "),
            "osc52_response_prefix_hex": response[:16].hex(" "),
            "osc52_response_suffix_hex": response[-16:].hex(" "),
            "osc52_response_bytes": len(response),
            "decoded_payload_bytes": decoded_bytes,
            "decoded_payload_sha256": decoded_sha256,
            "query_offset": query_at,
            "da1_query_offset": da1_at,
            "da1_barriers_answered": barrier_count,
        }
        if decoded_bytes < 128:
            terminal_response["osc52_response_bytes_hex"] = response.hex(" ")

        timing: dict[str, Any] = {
            "timeout_race_ms": TIMEOUT_MS,
            "response_write_ms": round(response_write_ms, 3) if response_write_ms is not None else None,
            "sentinel_elapsed_ms": round(sentinel_elapsed_ms, 3) if sentinel_elapsed_ms is not None else None,
        }
        if case["late"]:
            timing.update(
                {
                    "boundary": "timeout-flush-before-response",
                    "late_response_elapsed_ms": round((response_sent_at - query_observed_at) * 1000, 3),
                }
            )
        else:
            timing.update(
                {
                    "boundary": "response-before-timeout-flush",
                    "response_elapsed_ms": round((response_sent_at - query_observed_at) * 1000, 3),
                    "target_delay_ms": case["delay_target_ms"],
                }
            )

        outcome_detail = {
            "status": "ready",
            "outcome": outcome,
            "provider_order": (
                "OSC52 response before native provider"
                if outcome == "osc52-response"
                else "timeout flush, then native provider after late OSC52 response"
            ),
            "timing_boundary": timing["boundary"],
            "native_provider": "xclip" if provider_arguments == NATIVE_ARGUMENTS else "not invoked",
            "native_provider_arguments": provider_arguments,
            "native_payload": native_payload,
            "decoded_payload_trailing_newlines": 2,
            "inserted_trailing_newlines": 0,
            "screen_markers": [draft, remote_marker if outcome == "osc52-response" else native_marker],
            "screen_absent_markers": ["Ctrl+C to interrupt", "musing"],
            "submission": "not submitted",
            "cleanup": "clean exit after bounded probe",
        }
        return {
            "id": case_id,
            "description": case["description"],
            "draft": draft,
            "ssh_marker": "SSH_TTY=/dev/pts/999",
            "input_sequence": [
                {"kind": "text", "value": draft, "bytes_hex": draft.encode("utf-8").hex(" ")},
                {"kind": "key", "value": "Ctrl+V", "bytes_hex": "16"},
            ],
            "terminal_response": terminal_response,
            "timing": timing,
            "output": outcome_detail,
            "screen_tail": normalize(process_buffer)[-2000:],
        }
    finally:
        stop(pid, fd)
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0032",
        "reference_observation": "OBS-0024",
        "reference": str(reference),
        "source_commit": SOURCE_COMMIT,
        "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY with raw bytes"},
        "cases": [],
        "passed": False,
    }
    try:
        for case in CASES:
            report["cases"].append(run_case(reference, case, args.timeout))
        report["unknowns"] = [
            "The 500 ms race and payload behavior are reported only for the supplied direct-PTY delays and bounded payload sizes.",
            "No universal timeout or maximum-size contract is claimed from these controls; wall-clock jitter is not product behavior.",
            "ST termination, TMUX/STY forwarding, images/paths, gateway behavior, and concurrent input remain separate unknowns.",
            "This research fixture does not claim Hades implementation parity.",
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
