#!/usr/bin/env python3
"""Replay the OBS-0032 OSC52 timing and bounded-payload controls against Hades."""

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

from replay_osc52_clipboard import (
    COLUMNS,
    DA1_QUERY,
    DA1_RESPONSE,
    DEFAULT_BINARY,
    Osc52ReplayFailure,
    OSC52_QUERY,
    ROWS,
    child_status,
    contains_marker,
    create_xclip,
    emit_report,
    normalize,
    spawn,
    stop_child,
    wait_for,
    write_bytes,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "tests/fixtures/parity/OBS-0033-hades-osc52-timing-limits.json"
TIMEOUT_RACE_MS = 500
NATIVE_ARGUMENTS = "-selection clipboard -out"
LARGE_DECODED_BYTES = 256 * 1024
OVERSIZED_DECODED_BYTES = 512 * 1024


def build_payload(label: str, size: int) -> bytes:
    prefix = f"{label}-start\n".encode("ascii")
    suffix = f"\n{label}-end\n\n".encode("ascii")
    if size <= len(prefix) + len(suffix):
        raise ValueError(f"payload size is too small for {label}: {size}")
    fill = bytes((ord(label[0]),)) * (size - len(prefix) - len(suffix))
    return prefix + fill + suffix


def payload_for(case_id: str) -> bytes:
    if case_id == "response-before-timeout":
        return b"timing-before-remote  \nline-two\n\n"
    if case_id == "response-after-timeout":
        return b"timing-after-remote  \nline-two\n\n"
    if case_id == "large-response":
        return build_payload("large-response", LARGE_DECODED_BYTES)
    if case_id == "oversized-response":
        return build_payload("oversized-response", OVERSIZED_DECODED_BYTES)
    raise ValueError(f"unknown OBS-0033 case: {case_id}")


def write_nonblocking(fd: int, payload: bytes, deadline: float, case_id: str) -> float:
    started = time.monotonic()
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(fd, payload[offset : offset + 65_536])
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Osc52ReplayFailure(
                    case_id,
                    "osc52-response-write",
                    "bounded response did not reach the PTY before the pre-timeout deadline",
                    {"payload_bytes": len(payload), "written_bytes": offset},
                )
            select.select([], [fd], [], min(0.05, remaining))
            continue
        if written <= 0:
            raise Osc52ReplayFailure(case_id, "osc52-response-write", "PTY write returned no progress")
        offset += written
    return (time.monotonic() - started) * 1000


def sleep_until(deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


def load_contract(path: Path) -> dict[str, Any]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Osc52ReplayFailure("contract", "load", str(error)) from error
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise Osc52ReplayFailure("contract", "load", "unsupported OBS-0033 contract")
    if contract.get("observation_id") != "OBS-0033":
        raise Osc52ReplayFailure("contract", "load", "contract observation_id must be OBS-0033")
    steps = contract.get("steps")
    expected_ids = {
        "response-before-timeout",
        "response-after-timeout",
        "large-response",
        "oversized-response",
    }
    if not isinstance(steps, list) or {step.get("id") for step in steps if isinstance(step, dict)} != expected_ids:
        raise Osc52ReplayFailure("contract", "load", "OBS-0033 must contain the four timing-limit controls")
    return contract


def response_bytes(case_id: str, payload: bytes, case: dict[str, Any]) -> bytes:
    response = b"\x1b]52;c;" + base64.b64encode(payload) + b"\x07"
    terminal_response = case["terminal_response"]
    expected_hash = terminal_response["decoded_payload_sha256"]
    if hashlib.sha256(payload).hexdigest() != expected_hash:
        raise Osc52ReplayFailure(case_id, "payload-contract", "deterministic payload hash disagrees with OBS-0033")
    if len(payload) != terminal_response["decoded_payload_bytes"]:
        raise Osc52ReplayFailure(case_id, "payload-contract", "deterministic payload size disagrees with OBS-0033")
    if "osc52_response_bytes_hex" in terminal_response:
        if response.hex(" ") != terminal_response["osc52_response_bytes_hex"]:
            raise Osc52ReplayFailure(case_id, "payload-contract", "small response bytes disagree with OBS-0033")
    else:
        if len(response) != terminal_response["osc52_response_bytes"]:
            raise Osc52ReplayFailure(case_id, "payload-contract", "bounded response byte count disagrees with OBS-0033")
        if response[:16].hex(" ") != terminal_response["osc52_response_prefix_hex"]:
            raise Osc52ReplayFailure(case_id, "payload-contract", "bounded response prefix disagrees with OBS-0033")
        if response[-16:].hex(" ") != terminal_response["osc52_response_suffix_hex"]:
            raise Osc52ReplayFailure(case_id, "payload-contract", "bounded response suffix disagrees with OBS-0033")
    return response


def run_case(binary: Path, case: dict[str, Any], timeout: float, ordinal: int) -> dict[str, Any]:
    case_id = str(case["id"])
    payload = payload_for(case_id)
    response = response_bytes(case_id, payload, case)
    terminal_response = case["terminal_response"]
    if terminal_response["osc52_query_bytes_hex"] != OSC52_QUERY.hex(" "):
        raise Osc52ReplayFailure(case_id, "query-contract", "OBS-0033 query bytes are not the bare OSC52 query")
    if terminal_response["da1_sentinel_bytes_hex"] != DA1_QUERY.hex(" "):
        raise Osc52ReplayFailure(case_id, "query-contract", "OBS-0033 DA1 sentinel bytes are incorrect")
    if terminal_response["da1_response_bytes_hex"] != DA1_RESPONSE.hex(" "):
        raise Osc52ReplayFailure(case_id, "query-contract", "OBS-0033 DA1 response bytes are incorrect")

    output = case["output"]
    native_payload = output["native_payload"]
    home = Path(tempfile.mkdtemp(prefix=f"had033-{case_id}-{ordinal}-"))
    provider_dir = home / "bin"
    payload_path = home / "clipboard.payload"
    log_path = home / "clipboard.args"
    payload_path.write_bytes(native_payload.encode("utf-8"))
    create_xclip(provider_dir, payload_path, log_path)
    pid: int | None = None
    fd: int | None = None
    buffer = b""
    try:
        pid, fd = spawn(binary, home, provider_dir, payload_path, log_path)
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
        draft = case["input_sequence"][0]["value"]
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
            lambda current: OSC52_QUERY in current[start:],
            timeout,
        )
        query_at = buffer.find(OSC52_QUERY, start)
        query_observed_at = time.monotonic()
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case_id,
            "da1-query",
            lambda current: DA1_QUERY in current[query_at + len(OSC52_QUERY) :],
            timeout,
        )
        da1_at = buffer.find(DA1_QUERY, query_at + len(OSC52_QUERY))

        response_write_ms: float
        if case_id == "response-after-timeout":
            sleep_until(query_observed_at + 0.6)
            response_sent_at = time.monotonic()
            write_bytes(fd, response)
            write_bytes(fd, DA1_RESPONSE)
            response_write_ms = (time.monotonic() - response_sent_at) * 1000
            boundary = "response-after-500ms-timeout"
        elif case_id == "response-before-timeout":
            sleep_until(query_observed_at + 0.1)
            response_sent_at = time.monotonic()
            write_bytes(fd, response)
            write_bytes(fd, DA1_RESPONSE)
            response_write_ms = (time.monotonic() - response_sent_at) * 1000
            boundary = "response-before-500ms-timeout"
        else:
            response_sent_at = time.monotonic()
            response_write_ms = write_nonblocking(fd, response, query_observed_at + 0.45, case_id)
            write_bytes(fd, DA1_RESPONSE)
            boundary = "bounded-response-before-500ms-timeout"

        expected_outcome = output["outcome"]
        screen_markers = output["screen_markers"]
        buffer = wait_for(
            pid,
            fd,
            buffer,
            case_id,
            "response-outcome",
            lambda current: all(contains_marker(current, marker) for marker in screen_markers),
            timeout,
        )
        provider_arguments = log_path.read_text(encoding="utf-8")
        remote_marker = output.get("remote_marker")
        remote_observed = bool(remote_marker and contains_marker(buffer, remote_marker))
        native_observed = contains_marker(buffer, native_payload.rstrip("\n"))
        if expected_outcome == "osc52-response":
            if provider_arguments or not remote_observed or native_observed:
                raise Osc52ReplayFailure(
                    case_id,
                    "provider-order",
                    "Hades did not keep the usable OSC52 response ahead of native xclip",
                    {"native_provider_arguments": provider_arguments, "remote_observed": remote_observed},
                )
        elif expected_outcome == "native-fallback":
            if provider_arguments != NATIVE_ARGUMENTS or not native_observed or remote_observed:
                raise Osc52ReplayFailure(
                    case_id,
                    "provider-order",
                    "Hades did not fall back to native xclip after the delayed OSC52 response",
                    {"native_provider_arguments": provider_arguments, "remote_observed": remote_observed},
                )
        else:
            raise Osc52ReplayFailure(case_id, "contract", f"unsupported expected outcome: {expected_outcome}")

        for marker in output.get("screen_absent_markers", []):
            if contains_marker(buffer, marker):
                raise Osc52ReplayFailure(case_id, "screen", f"unexpected marker: {marker}")
        if child_status(pid)[0]:
            raise Osc52ReplayFailure(case_id, "ready-state", "Hades exited before cleanup")
        write_bytes(fd, b"\x03")
        buffer = wait_for(pid, fd, buffer, case_id, "cleanup", lambda _current: child_status(pid)[0], timeout)

        return {
            "id": case_id,
            "status": "passed",
            "draft": draft,
            "ssh_marker": "SSH_TTY=/dev/pts/999",
            "input_sequence": case["input_sequence"],
            "terminal_response": {
                "osc52_query_bytes_hex": OSC52_QUERY.hex(" "),
                "da1_sentinel_bytes_hex": DA1_QUERY.hex(" "),
                "da1_response_bytes_hex": DA1_RESPONSE.hex(" "),
                "osc52_response_prefix_hex": response[:16].hex(" "),
                "osc52_response_suffix_hex": response[-16:].hex(" "),
                "osc52_response_bytes": len(response),
                "decoded_payload_bytes": len(payload),
                "decoded_payload_sha256": hashlib.sha256(payload).hexdigest(),
                "query_offset": query_at,
                "da1_query_offset": da1_at,
            },
            "timing": {
                "timeout_race_ms": TIMEOUT_RACE_MS,
                "boundary": boundary,
                "response_elapsed_ms": round((response_sent_at - query_observed_at) * 1000, 3),
                "response_write_ms": round(response_write_ms, 3),
            },
            "output": {
                "status": "ready",
                "outcome": expected_outcome,
                "provider_order": output["provider_order"],
                "native_provider": output["native_provider"],
                "native_provider_arguments": provider_arguments,
                "screen_markers": screen_markers,
                "screen_absent_markers": output.get("screen_absent_markers", []),
                "submission": output["submission"],
                "cleanup": "clean exit after bounded replay",
            },
            "screen_tail": normalize(buffer)[-2000:],
        }
    finally:
        if pid is not None and fd is not None:
            stop_child(pid, fd)
        shutil.rmtree(home, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    binary = args.binary.resolve()
    contract_path = args.contract.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "command": "replay-osc52-timing-limits",
        "observation_id": "OBS-0033",
        "reference_observation": "OBS-0032",
        "binary": str(binary),
        "contract": str(contract_path),
        "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY with raw bytes"},
        "checks": [],
        "passed": False,
    }
    try:
        if not binary.is_file():
            raise Osc52ReplayFailure("input", "binary", f"binary not found: {binary}")
        contract = load_contract(contract_path)
        for ordinal, case in enumerate(contract["steps"], start=1):
            report["checks"].append(run_case(binary, case, args.timeout, ordinal))
        report["unknowns"] = [
            "The Hades replay proves only the OBS-0032 direct-PTY timing controls and bounded 256 KiB/512 KiB payloads.",
            "It does not claim a universal timeout or maximum-size contract, larger payload behavior, or wall-clock jitter parity.",
            "ST termination, TMUX/STY forwarding, images/paths, gateway behavior, and concurrent input remain separate controls.",
        ]
        report["passed"] = True
    except Osc52ReplayFailure as error:
        report["failure"] = error.as_dict()
    except (OSError, TypeError, ValueError, KeyError) as error:
        report["failure"] = {"case": "report", "step": "runtime", "message": str(error)}

    emit_report(report, args.report.resolve() if args.report else None)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
