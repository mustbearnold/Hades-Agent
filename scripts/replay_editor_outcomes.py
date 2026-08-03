#!/usr/bin/env python3
"""Replay deterministic Hades editor outcomes in isolated tmux PTYs."""

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
    finish_hold_provider,
    hold_provider_environment,
    session_exists,
    start_hold_provider,
    start_session,
    tmux_run,
    wait_for_screen,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "tests/fixtures/parity/OBS-0019-hades-editor-outcomes.json"
DEFAULT_BINARY = ROOT / "target/debug/hades"


def send_text(session: str, text: str) -> None:
    result = tmux_run("send-keys", "-t", session, "-l", text)
    if result.returncode != 0:
        raise ComposerReplayFailure(session, "type-draft", result.stderr.strip() or "tmux send failed")


def send_key(session: str, key: str) -> None:
    payload = {"Ctrl+G": "C-g", "Ctrl+C": "C-c"}[key]
    result = tmux_run("send-keys", "-t", session, payload)
    if result.returncode != 0:
        raise ComposerReplayFailure(session, key, result.stderr.strip() or "tmux send failed")


def wait_for_exit(session: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while session_exists(session) and time.monotonic() < deadline:
        time.sleep(0.05)
    if session_exists(session):
        raise ComposerReplayFailure(session, "exit", "process did not exit")


def load_contract(path: Path) -> dict[str, Any]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComposerReplayFailure("contract", "load", str(error)) from error
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise ComposerReplayFailure("contract", "load", "unsupported editor outcome contract")
    cases = contract.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ComposerReplayFailure("contract", "load", "editor outcome contract has no cases")
    ids = [case.get("id") for case in cases if isinstance(case, dict)]
    required = {
        "modified-clean-exit",
        "multiline-clean-exit",
        "trailing-newline-trim",
        "empty-clean-exit",
        "cancelled-nonzero-exit",
    }
    if set(ids) != required:
        raise ComposerReplayFailure("contract", "load", f"case ids must be {sorted(required)}")
    return contract


def run_case(
    binary: Path,
    case: dict[str, Any],
    timeout: float,
    ordinal: int,
    provider_environment: dict[str, str],
) -> dict[str, Any]:
    case_id = case["id"]
    session = f"had019-editor-{ordinal}-{int(time.time() * 1000)}"
    history_home = Path(tempfile.mkdtemp(prefix=f"had019-editor-{case_id}-"))
    expected = case["expected"]
    try:
        start_session(
            binary,
            session,
            {
                **provider_environment,
                "HERMES_HOME": str(history_home),
                "VISUAL": "",
                "EDITOR": case["editor"],
            },
        )
        startup_markers = ("Hades Agent", "Underworld", "Available Tools", "Available Skills")
        wait_for_screen(
            session,
            "startup",
            lambda screen: all(contains_marker(screen, marker) for marker in startup_markers),
            timeout,
        )

        send_text(session, case["draft"])
        wait_for_screen(session, "type-draft", lambda screen: contains_marker(screen, case["draft"]), timeout)
        send_key(session, "Ctrl+G")

        if "Ctrl+C to interrupt" in expected["screen_markers"]:
            screen = wait_for_screen(
                session,
                "editor-submit",
                lambda current: all(contains_marker(current, marker) for marker in expected["screen_markers"]),
                timeout,
            )
        else:
            time.sleep(0.35)
            if not session_exists(session):
                raise ComposerReplayFailure(case_id, "editor-return", "process exited after editor return")
            screen = capture_screen(session)

        for marker in expected["screen_markers"]:
            if not contains_marker(screen, marker):
                raise ComposerReplayFailure(case_id, "editor-return", f"missing marker: {marker}")
        for marker in expected.get("screen_absent_markers", []):
            if contains_marker(screen, marker):
                raise ComposerReplayFailure(case_id, "editor-return", f"unexpected marker: {marker}")

        history_path = history_home / ".hermes_history"
        history = history_path.read_text(encoding="utf-8") if history_path.exists() else ""
        for record in expected.get("history_records", []):
            if record not in history:
                raise ComposerReplayFailure(case_id, "history-readback", f"missing history record: {record}")
        if expected.get("history_records") == [] and history:
            raise ComposerReplayFailure(case_id, "history-readback", "unexpected history entry")

        steps = [
            {"id": "type-draft", "status": "passed", "observed": [case["draft"]]},
            {"id": "editor-return", "status": "passed", "observed": expected["screen_markers"]},
            {"id": "history-readback", "status": "passed", "observed": expected.get("history_records", [])},
        ]

        send_key(session, "Ctrl+C")
        if "Ctrl+C to interrupt" in expected["screen_markers"]:
            wait_for_screen(session, "interrupt", lambda current: contains_marker(current, "interrupted"), timeout)
        send_key(session, "Ctrl+C")
        wait_for_exit(session, timeout)
        steps.extend(
            [
                {"id": "interrupt-or-clear", "status": "passed", "observed": ["ready after editor outcome"]},
                {"id": "exit", "status": "passed", "observed": ["process exit"]},
            ]
        )
        return {"id": case_id, "status": "passed", "steps": steps, "capture": "tmux capture-pane -p"}
    finally:
        if session_exists(session):
            tmux_run("kill-session", "-t", session)
        shutil.rmtree(history_home, ignore_errors=True)


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
        "command": "replay-editor-outcomes",
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
        for ordinal, case in enumerate(contract["cases"], start=1):
            provider, provider_thread = start_hold_provider()
            try:
                report["checks"].append(
                    run_case(
                        binary,
                        case,
                        arguments.timeout,
                        ordinal,
                        hold_provider_environment(provider),
                    )
                )
            finally:
                finish_hold_provider(provider, provider_thread)
        report["passed"] = True
    except ComposerReplayFailure as error:
        report["failure"] = error.as_dict()
    except (OSError, TypeError, ValueError) as error:
        report["failure"] = {"case": "report", "step": "runtime", "message": str(error)}

    try:
        emit_report(report, arguments.report.resolve() if arguments.report else None)
    except OSError as error:
        print(json.dumps({"passed": False, "error": f"could not write report: {error}"}))
        return 2
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
