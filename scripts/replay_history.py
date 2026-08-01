#!/usr/bin/env python3
"""Replay Hades persistent input history across isolated PTY processes."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from replay_composer import (
    ComposerReplayFailure,
    capture_screen,
    contains_marker,
    emit_report,
    send_input,
    session_exists,
    start_session,
    tmux_run,
    wait_for_screen,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "tests/fixtures/parity/OBS-0017-hades-input-history-persistence.json"
DEFAULT_BINARY = ROOT / "target/debug/hades"
SNAPSHOT_COLUMNS = 120
SNAPSHOT_ROWS = 40
STARTUP_MARKERS = ("Hermes Agent", "Nous Research", "Available Tools", "Available Skills")


def load_contract(path: Path) -> dict[str, Any]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComposerReplayFailure("contract", "load", f"could not read {path}: {error}") from error
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise ComposerReplayFailure("contract", "load", "unsupported history contract schema")
    cases = contract.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ComposerReplayFailure("contract", "load", "history contract has no cases")
    required = {"restart-recall", "duplicate-suppression", "multiline-readback", "load-cap"}
    actual = {case.get("id") for case in cases if isinstance(case, dict)}
    if actual != required:
        raise ComposerReplayFailure("contract", "load", f"history cases must be {sorted(required)}")
    return contract


def start_history_session(binary: Path, session: str, history_home: Path, timeout: float) -> None:
    start_session(binary, session, {"HERMES_HOME": str(history_home)})
    wait_for_screen(
        session,
        "startup",
        lambda screen: all(contains_marker(screen, marker) for marker in STARTUP_MARKERS),
        timeout,
    )


def wait_for_exit(session: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while session_exists(session) and time.monotonic() < deadline:
        time.sleep(0.05)
    if session_exists(session):
        raise ComposerReplayFailure(session, "exit", "process did not exit")


def interrupt_and_exit(session: str, timeout: float, case_id: str, steps: list[dict[str, Any]]) -> None:
    send_input(session, {"kind": "key", "value": "Ctrl+C"})
    wait_for_screen(session, "interrupt", lambda screen: contains_marker(screen, "interrupted"), timeout)
    steps.append({"id": "interrupt", "status": "passed", "observed": ["interrupted"]})
    send_input(session, {"kind": "key", "value": "Ctrl+C"})
    wait_for_exit(session, timeout)
    steps.append({"id": "exit", "status": "passed", "observed": ["process exit"]})


def submit_draft(
    session: str,
    draft: str,
    timeout: float,
    steps: list[dict[str, Any]],
    *,
    paste: bool = False,
) -> None:
    input_value = {"kind": "paste" if paste else "text", "value": draft}
    send_input(session, input_value)
    wait_for_screen(
        session,
        "draft",
        lambda screen: all(contains_marker(screen, marker) for marker in draft.split("\n")),
        timeout,
    )
    steps.append({"id": "draft", "input": input_value, "status": "passed", "observed": draft.split("\n")})
    send_input(session, {"kind": "key", "value": "Enter"})
    wait_for_screen(
        session,
        "submit",
        lambda screen: all(contains_marker(screen, marker) for marker in ("musing", "mulling", "Ctrl+C to interrupt")),
        timeout,
    )
    steps.append({"id": "submit", "status": "passed", "observed": ["musing", "mulling", "Ctrl+C to interrupt"]})


def run_restart_case(
    binary: Path, case: dict[str, Any], timeout: float, history_home: Path
) -> dict[str, Any]:
    session_a = f"had017-history-a-{int(time.time() * 1000)}"
    session_b = f"had017-history-b-{int(time.time() * 1000)}"
    steps: list[dict[str, Any]] = []
    draft = str(case["draft"])
    try:
        start_history_session(binary, session_a, history_home, timeout)
        submit_draft(session_a, draft, timeout, steps)
        interrupt_and_exit(session_a, timeout, "restart-recall", steps)
        history_path = history_home / ".hermes_history"
        history_text = history_path.read_text(encoding="utf-8")
        expected_entry = str(case["expected_history_entry"])
        if expected_entry not in history_text:
            raise ComposerReplayFailure("restart-recall", "history-write", f"missing history record {expected_entry}")

        start_history_session(binary, session_b, history_home, timeout)
        send_input(session_b, {"kind": "key", "value": "Up"})
        recalled = str(case["expected_recalled_draft"])
        wait_for_screen(session_b, "history-up", lambda screen: contains_marker(screen, recalled), timeout)
        steps.append({"id": "history-up", "status": "passed", "observed": [recalled]})
        send_input(session_b, {"kind": "key", "value": "Down"})
        empty_marker = str(case["expected_empty_draft_marker"])
        wait_for_screen(session_b, "history-down", lambda screen: contains_marker(screen, empty_marker), timeout)
        steps.append({"id": "history-down", "status": "passed", "observed": ["empty draft"]})
        send_input(session_b, {"kind": "key", "value": "Ctrl+C"})
        wait_for_exit(session_b, timeout)
        steps.append({"id": "exit", "status": "passed", "observed": ["process exit"]})
        return {"id": "restart-recall", "status": "passed", "steps": steps}
    finally:
        for session in (session_a, session_b):
            if session_exists(session):
                tmux_run("kill-session", "-t", session)


def run_duplicate_case(
    binary: Path, case: dict[str, Any], timeout: float, history_home: Path
) -> dict[str, Any]:
    session = f"had017-history-dup-{int(time.time() * 1000)}"
    steps: list[dict[str, Any]] = []
    try:
        start_history_session(binary, session, history_home, timeout)
        history_path = history_home / ".hermes_history"
        before = history_path.read_bytes()
        submit_draft(session, str(case["draft"]), timeout, steps)
        send_input(session, {"kind": "key", "value": "Ctrl+C"})
        wait_for_screen(session, "interrupt", lambda screen: contains_marker(screen, "interrupted"), timeout)
        after = history_path.read_bytes()
        if before != after:
            raise ComposerReplayFailure("duplicate-suppression", "history-write", "history file changed for a consecutive duplicate")
        steps.append({"id": "duplicate-readback", "status": "passed", "observed": ["file unchanged"]})
        send_input(session, {"kind": "key", "value": "Ctrl+C"})
        wait_for_exit(session, timeout)
        steps.append({"id": "exit", "status": "passed", "observed": ["process exit"]})
        return {"id": "duplicate-suppression", "status": "passed", "steps": steps, "file_unchanged": True}
    finally:
        if session_exists(session):
            tmux_run("kill-session", "-t", session)


def run_multiline_case(
    binary: Path, case: dict[str, Any], timeout: float, history_home: Path
) -> dict[str, Any]:
    session = f"had017-history-multi-{int(time.time() * 1000)}"
    steps: list[dict[str, Any]] = []
    try:
        start_history_session(binary, session, history_home, timeout)
        lines = [str(line) for line in case["lines"]]
        submit_draft(session, "\n".join(lines), timeout, steps, paste=True)
        interrupt_and_exit(session, timeout, "multiline-readback", steps)
        history_text = (history_home / ".hermes_history").read_text(encoding="utf-8")
        for record in case["expected_history_records"]:
            if str(record) + "\n" not in history_text:
                raise ComposerReplayFailure("multiline-readback", "history-readback", f"missing record {record}")
        steps.append({"id": "history-readback", "status": "passed", "observed": ["multiline + records"]})
        return {"id": "multiline-readback", "status": "passed", "steps": steps}
    finally:
        if session_exists(session):
            tmux_run("kill-session", "-t", session)


def run_cap_case(binary: Path, case: dict[str, Any], timeout: float, history_home: Path) -> dict[str, Any]:
    session = f"had017-history-cap-{int(time.time() * 1000)}"
    steps: list[dict[str, Any]] = []
    history_path = history_home / ".hermes_history"
    seed_count = int(case["seed_count"])
    history_path.write_text(
        "".join(f"\n# timestamp\n+cap-{index:04d}\n" for index in range(1, seed_count + 1)),
        encoding="utf-8",
    )
    try:
        start_history_session(binary, session, history_home, timeout)
        send_input(session, {"kind": "key", "value": "Up"})
        newest = str(case["newest_entry"])
        wait_for_screen(session, "cap-newest", lambda screen: contains_marker(screen, newest), timeout)
        steps.append({"id": "cap-newest", "status": "passed", "observed": [newest]})
        for _ in range(999):
            tmux_run("send-keys", "-t", session, "Up")
            time.sleep(0.01)
        oldest = str(case["oldest_retained_entry"])
        wait_for_screen(session, "cap-oldest", lambda screen: contains_marker(screen, oldest), timeout)
        steps.append({"id": "cap-oldest", "status": "passed", "observed": [oldest]})
        tmux_run("send-keys", "-t", session, "Up")
        wait_for_screen(session, "cap-floor", lambda screen: contains_marker(screen, oldest), timeout)
        steps.append({"id": "cap-floor", "status": "passed", "observed": [oldest]})
        send_input(session, {"kind": "key", "value": "Ctrl+C"})
        wait_for_exit(session, timeout)
        steps.append({"id": "exit", "status": "passed", "observed": ["process exit"]})
        return {"id": "load-cap", "status": "passed", "steps": steps, "seed_count": seed_count}
    finally:
        if session_exists(session):
            tmux_run("kill-session", "-t", session)


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
        "command": "replay-history",
        "passed": False,
        "binary": str(binary),
        "contract": str(contract_path),
        "checks": [],
    }
    try:
        if not binary.is_file():
            raise ComposerReplayFailure("input", "binary", f"binary not found: {binary}")
        contract = load_contract(contract_path)
        report["contract_observation"] = contract["observation_id"]
        report["reference_observation"] = contract.get("reference_observation")
        report["dimensions"] = contract["terminal"]
        checks = report["checks"]
        with tempfile.TemporaryDirectory(prefix="had017-history-") as root:
            root_path = Path(root)
            checks.append(run_restart_case(binary, next(case for case in contract["cases"] if case["id"] == "restart-recall"), arguments.timeout, root_path / "restart"))
            checks.append(run_duplicate_case(binary, next(case for case in contract["cases"] if case["id"] == "duplicate-suppression"), arguments.timeout, root_path / "restart"))
            checks.append(run_multiline_case(binary, next(case for case in contract["cases"] if case["id"] == "multiline-readback"), arguments.timeout, root_path / "multiline"))
            cap_home = root_path / "cap"
            cap_home.mkdir(parents=True, exist_ok=True)
            checks.append(run_cap_case(binary, next(case for case in contract["cases"] if case["id"] == "load-cap"), arguments.timeout, cap_home))
        report["passed"] = True
    except (ComposerReplayFailure, OSError, ValueError, KeyError, TypeError) as error:
        if isinstance(error, ComposerReplayFailure):
            report["failure"] = error.as_dict()
        else:
            report["failure"] = {"case": "report", "step": "runtime", "message": str(error)}

    try:
        emit_report(report, arguments.report.resolve() if arguments.report else None)
    except OSError as error:
        print(json.dumps({"passed": False, "error": f"could not write report: {error}"}))
        return 2
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
