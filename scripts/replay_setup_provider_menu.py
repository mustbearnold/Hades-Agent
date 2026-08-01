#!/usr/bin/env python3
"""Replay the bounded Hades Full setup provider-menu contract in tmux."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from replay_composer import (
    DEFAULT_BINARY,
    ComposerReplayFailure,
    contains_marker,
    session_exists,
    start_session,
    tmux_run,
    wait_for_screen,
)


KEY_PAYLOADS = {
    "Enter": "C-m",
    "Down": "Down",
    "Ctrl+C": "C-c",
}


def load_contract(path: Path) -> dict[str, Any]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComposerReplayFailure("contract", "load", f"could not read {path}: {error}") from error
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise ComposerReplayFailure("contract", "load", "unsupported setup-provider contract schema")
    cases = contract.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ComposerReplayFailure("contract", "load", "setup-provider contract has no cases")
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ComposerReplayFailure("contract", "case", "case needs an id")
        steps = case.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ComposerReplayFailure("contract", case["id"], "case has no steps")
        for step in steps:
            if not isinstance(step, dict) or not isinstance(step.get("id"), str):
                raise ComposerReplayFailure("contract", case["id"], "step needs an id")
            input_value = step.get("input")
            if not isinstance(input_value, dict) or input_value.get("kind") not in {"text", "key"}:
                raise ComposerReplayFailure("contract", step["id"], "input must be text or key")
            if not isinstance(input_value.get("value"), str):
                raise ComposerReplayFailure("contract", step["id"], "input needs a string value")
            output = step.get("output")
            if not isinstance(output, dict):
                raise ComposerReplayFailure("contract", step["id"], "output must be an object")
            for key in ("pty_markers", "pty_absent_markers"):
                markers = output.get(key, [])
                if not isinstance(markers, list) or not all(isinstance(marker, str) for marker in markers):
                    raise ComposerReplayFailure("contract", step["id"], f"{key} must be a string array")
    return contract


def send_input(session: str, input_value: dict[str, str]) -> None:
    if input_value["kind"] == "text":
        result = tmux_run("send-keys", "-t", session, "-l", input_value["value"])
    else:
        try:
            payload = KEY_PAYLOADS[input_value["value"]]
        except KeyError as error:
            raise ComposerReplayFailure("input", input_value["value"], "unsupported setup-provider key") from error
        result = tmux_run("send-keys", "-t", session, payload)
    if result.returncode != 0:
        raise ComposerReplayFailure(
            session,
            "input",
            f"tmux send-keys failed: {result.stderr.strip() or result.stdout.strip()}",
        )


def run_case(binary: Path, case: dict[str, Any], timeout: float, ordinal: int) -> dict[str, Any]:
    case_id = case["id"]
    session = f"had046-provider-{ordinal}-{int(time.time() * 1000)}"
    history_home = Path(tempfile.mkdtemp(prefix="had046-provider-history-"))
    start_session(binary, session, {"HERMES_HOME": str(history_home)})
    replayed_steps: list[dict[str, Any]] = []
    try:
        startup_markers = ("Hermes Agent", "Nous Research", "Available Tools", "Available Skills")
        wait_for_screen(
            session,
            "startup",
            lambda screen: all(contains_marker(screen, marker) for marker in startup_markers),
            timeout,
        )
        for step in case["steps"]:
            step_id = step["id"]
            input_value = step["input"]
            output = step["output"]
            send_input(session, input_value)
            if output.get("process_exit"):
                deadline = time.monotonic() + timeout
                while session_exists(session) and time.monotonic() < deadline:
                    time.sleep(0.05)
                if session_exists(session):
                    raise ComposerReplayFailure(case_id, step_id, "process did not exit")
            else:
                markers = output.get("pty_markers", [])
                absent = output.get("pty_absent_markers", [])
                wait_for_screen(
                    session,
                    step_id,
                    lambda screen, expected=markers, forbidden=absent: all(
                        contains_marker(screen, marker) for marker in expected
                    )
                    and all(not contains_marker(screen, marker) for marker in forbidden),
                    timeout,
                )
            replayed_steps.append(
                {
                    "id": step_id,
                    "input": input_value,
                    "status": "passed",
                    "observed": output.get("pty_markers", []),
                    "absent": output.get("pty_absent_markers", []),
                }
            )
        return {"id": case_id, "status": "passed", "steps": replayed_steps, "capture": "tmux capture-pane -p"}
    finally:
        if session_exists(session):
            tmux_run("kill-session", "-t", session)
        shutil.rmtree(history_home, ignore_errors=True)


def emit_report(report: dict[str, Any], path: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--binary",
        type=Path,
        default=DEFAULT_BINARY,
    )
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=5.0)
    arguments = parser.parse_args()
    binary = arguments.binary.resolve()
    contract_path = arguments.contract.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "command": "replay-setup-provider",
        "passed": False,
        "binary": "<hades-binary>",
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
            report["checks"].append(run_case(binary, case, arguments.timeout, ordinal))
        report["passed"] = True
    except ComposerReplayFailure as error:
        report["failure"] = error.as_dict()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        report["failure"] = {"case": "report", "step": "runtime", "message": str(error)}

    emit_report(report, arguments.report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
