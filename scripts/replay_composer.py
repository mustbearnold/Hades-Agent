#!/usr/bin/env python3
"""Replay the implemented Hades composer contract in isolated tmux PTYs."""

from __future__ import annotations

import argparse
import json
import shutil
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "tests/fixtures/parity/OBS-0011-hades-composer-editing.json"
DEFAULT_BINARY = ROOT / "target/debug/hades"
SNAPSHOT_COLUMNS = 120
SNAPSHOT_ROWS = 40
Predicate = Callable[[str], bool]


class HoldProviderServer(ThreadingHTTPServer):
    """Hold an accepted provider request so PTY contracts can test Busy."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        self.request_seen = threading.Event()
        self.release_response = threading.Event()
        super().__init__(("127.0.0.1", 0), self._handler())

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                owner.request_seen.set()
                owner.release_response.wait(timeout=3.0)

        return Handler


def start_hold_provider() -> tuple[HoldProviderServer, threading.Thread]:
    server = HoldProviderServer()
    thread = threading.Thread(target=server.serve_forever, name="hades-replay-provider", daemon=True)
    thread.start()
    return server, thread


def finish_hold_provider(server: HoldProviderServer, thread: threading.Thread) -> None:
    server.release_response.set()
    server.shutdown()
    server.server_close()
    thread.join(timeout=2.0)


def hold_provider_environment(server: HoldProviderServer) -> dict[str, str]:
    return {
        "HADES_PROVIDER_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
        "HADES_MODEL": "palette-model",
        "HADES_PROVIDER_API_KEY": "",
    }


class ComposerReplayFailure(RuntimeError):
    """Raised when a composer contract assertion fails."""

    def __init__(self, case: str, step: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.case = case
        self.step = step
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "step": self.step,
            "message": self.message,
            **self.details,
        }


def load_contract(path: Path) -> dict[str, Any]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComposerReplayFailure("contract", "load", f"could not read {path}: {error}") from error
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise ComposerReplayFailure("contract", "load", "unsupported composer contract schema")
    cases = contract.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ComposerReplayFailure("contract", "load", "composer contract has no cases")
    case_ids: set[str] = set()
    for case_index, case in enumerate(cases):
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ComposerReplayFailure("contract", f"case[{case_index}]", "case needs an id")
        case_id = case["id"]
        if case_id in case_ids:
            raise ComposerReplayFailure("contract", case_id, "duplicate case id")
        case_ids.add(case_id)
        steps = case.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ComposerReplayFailure("contract", case_id, "case has no steps")
        step_ids: set[str] = set()
        for step_index, step in enumerate(steps):
            step_path = f"{case_id}[{step_index}]"
            if not isinstance(step, dict) or not isinstance(step.get("id"), str):
                raise ComposerReplayFailure("contract", step_path, "step needs an id")
            if step["id"] in step_ids:
                raise ComposerReplayFailure("contract", step["id"], "duplicate step id")
            step_ids.add(step["id"])
            input_value = step.get("input")
            if not isinstance(input_value, dict) or input_value.get("kind") not in {
                "text",
                "key",
                "paste",
            }:
                raise ComposerReplayFailure("contract", step["id"], "step input must be text, key, or paste")
            if not isinstance(input_value.get("value"), str):
                raise ComposerReplayFailure("contract", step["id"], "step input needs a string value")
            output = step.get("output")
            if not isinstance(output, dict):
                raise ComposerReplayFailure("contract", step["id"], "step output must be an object")
            markers = output.get("pty_markers")
            if not isinstance(markers, list) or not all(isinstance(marker, str) for marker in markers):
                raise ComposerReplayFailure("contract", step["id"], "pty_markers must be a string array")
            absent_markers = output.get("pty_absent_markers", [])
            if not isinstance(absent_markers, list) or not all(
                isinstance(marker, str) for marker in absent_markers
            ):
                raise ComposerReplayFailure(
                    "contract", step["id"], "pty_absent_markers must be a string array"
                )
    return contract


def contains_marker(screen: str, marker: str) -> bool:
    compact_screen = "".join(screen.split()).lower()
    compact_marker = "".join(marker.split()).lower()
    return marker in screen or compact_marker in compact_screen


def tmux_run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["tmux", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def capture_screen(session: str) -> str:
    result = tmux_run("capture-pane", "-p", "-t", session)
    if result.returncode != 0:
        return ""
    return result.stdout


def session_exists(session: str) -> bool:
    return tmux_run("has-session", "-t", session).returncode == 0


def wait_for_screen(session: str, description: str, predicate: Predicate, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    latest = ""
    while time.monotonic() < deadline:
        latest = capture_screen(session)
        if predicate(latest):
            return latest
        if not session_exists(session):
            raise ComposerReplayFailure(
                session,
                description,
                "tmux session exited before the screen assertion",
                {"screen_tail": "\n".join(latest.splitlines()[-12:])},
            )
        time.sleep(0.05)
    raise ComposerReplayFailure(
        session,
        description,
        f"timed out after {timeout:.1f}s",
        {"screen_tail": "\n".join(latest.splitlines()[-12:])},
    )


def key_payload(value: str) -> str:
    payloads = {
        "Enter": "C-m",
        "Ctrl+A": "C-a",
        "Ctrl+C": "C-c",
        "Ctrl+G": "C-g",
        "Ctrl+K": "C-k",
        "Ctrl+V": "C-v",
        "Backspace": "BSpace",
        "Up": "Up",
        "Down": "Down",
        "Left": "Left",
        "Right": "Right",
        "Home": "Home",
        "End": "End",
        "Tab": "Tab",
    }
    try:
        return payloads[value]
    except KeyError as error:
        raise ComposerReplayFailure("contract", value, f"unsupported composer key: {value}") from error


def send_input(session: str, input_value: dict[str, str]) -> None:
    if input_value["kind"] in {"text", "paste"}:
        value = input_value["value"]
        if input_value["kind"] == "paste":
            value = f"\x1b[200~{value}\x1b[201~"
        result = tmux_run("send-keys", "-t", session, "-l", value)
    else:
        result = tmux_run("send-keys", "-t", session, key_payload(input_value["value"]))
    if result.returncode != 0:
        raise ComposerReplayFailure(
            session,
            "input",
            f"tmux send-keys failed: {result.stderr.strip() or result.stdout.strip()}",
        )


def start_session(binary: Path, session: str, environment: dict[str, str] | None = None) -> None:
    environment = {"TERM": "xterm-256color", **(environment or {})}
    command = shlex.join(
        ["env", *(f"{key}={value}" for key, value in environment.items()), str(binary)]
    )
    result = tmux_run(
        "new-session",
        "-d",
        "-s",
        session,
        "-x",
        str(SNAPSHOT_COLUMNS),
        "-y",
        str(SNAPSHOT_ROWS),
        "-c",
        str(ROOT),
        command,
    )
    if result.returncode != 0:
        raise ComposerReplayFailure(
            session,
            "startup",
            f"tmux session failed to start: {result.stderr.strip() or result.stdout.strip()}",
        )


def run_case(
    binary: Path,
    case: dict[str, Any],
    timeout: float,
    ordinal: int,
    session_prefix: str = "had011-composer",
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    case_id = case["id"]
    session = f"{session_prefix}-{ordinal}-{int(time.time() * 1000)}"
    owned_history_home: Path | None = None
    hold_provider, hold_provider_thread = start_hold_provider()
    effective_environment = hold_provider_environment(hold_provider)
    effective_environment.update(environment or {})
    replayed_steps: list[dict[str, Any]] = []
    try:
        if "HERMES_HOME" not in effective_environment:
            owned_history_home = Path(tempfile.mkdtemp(prefix=f"{session_prefix}-history-"))
            effective_environment["HERMES_HOME"] = str(owned_history_home)
        start_session(binary, session, effective_environment)
        startup_markers = ("Hades Agent", "Underworld", "Available Tools", "Available Skills")
        wait_for_screen(
            session,
            "startup",
            lambda screen: all(contains_marker(screen, marker) for marker in startup_markers),
            timeout,
        )

        for step in case["steps"]:
            step_id = step["id"]
            input_value = step["input"]
            output_contract = step["output"]
            markers = output_contract["pty_markers"]
            absent_markers = output_contract.get("pty_absent_markers", [])
            send_input(session, input_value)

            if output_contract.get("process_exit"):
                deadline = time.monotonic() + timeout
                while session_exists(session) and time.monotonic() < deadline:
                    time.sleep(0.05)
                if session_exists(session):
                    raise ComposerReplayFailure(case_id, step_id, "process did not exit")
                observed = ["process exit"]
            elif markers or absent_markers:
                screen = wait_for_screen(
                    session,
                    step_id,
                    lambda current, expected=markers, absent=absent_markers: all(
                        contains_marker(current, marker) for marker in expected
                    )
                    and all(not contains_marker(current, marker) for marker in absent),
                    timeout,
                )
                observed = list(markers)
            else:
                time.sleep(0.08)
                if not session_exists(session):
                    raise ComposerReplayFailure(case_id, step_id, "process exited during a non-terminal step")
                screen = capture_screen(session)
                observed = []

            replayed_steps.append(
                {
                    "id": step_id,
                    "input": input_value,
                    "status": "passed",
                    "observed": observed,
                    "absent": absent_markers,
                }
            )

        return {
            "id": case_id,
            "status": "passed",
            "steps": replayed_steps,
            "capture": "tmux capture-pane -p",
        }
    finally:
        if session_exists(session):
            tmux_run("kill-session", "-t", session)
        if owned_history_home is not None:
            shutil.rmtree(owned_history_home, ignore_errors=True)
        finish_hold_provider(hold_provider, hold_provider_thread)


def emit_report(report: dict[str, Any], report_path: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8")


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
        "command": "replay-composer",
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
            report["checks"].append(run_case(binary, case, arguments.timeout, ordinal))
        report["passed"] = True
    except ComposerReplayFailure as error:
        report["failure"] = error.as_dict()
    except (OSError, ValueError) as error:
        report["failure"] = {"case": "report", "step": "runtime", "message": str(error)}

    try:
        emit_report(report, arguments.report.resolve() if arguments.report else None)
    except OSError as error:
        print(json.dumps({"passed": False, "error": f"could not write report: {error}"}))
        return 2
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
