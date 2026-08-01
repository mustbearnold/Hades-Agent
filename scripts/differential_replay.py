#!/usr/bin/env python3
"""Replay a sanitized Hermes parity trace against the Hades binary."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from probe_tui_lifecycle import (
    ProbeError,
    clean_output,
    describe_status,
    output_tail,
    send,
    spawn,
    terminal_flags,
    wait_for,
    wait_for_exit,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE = ROOT / "tests/fixtures/parity/OBS-0003-submit-interrupt.json"
DEFAULT_GOLDEN = ROOT / "tests/fixtures/parity/OBS-0001-startup-120x40.txt"
DEFAULT_VISUAL_CONTRACT = ROOT / "tests/fixtures/parity/OBS-0006-busy-interrupt-visual.json"
DEFAULT_SESSION_TRACE = ROOT / "tests/fixtures/parity/OBS-0007-session-switcher.json"
DEFAULT_SESSION_CONTRACT = ROOT / "tests/fixtures/parity/OBS-0007-session-switcher.json"
DEFAULT_BINARY = ROOT / "target/debug/hades"
DEFAULT_REPORT = ROOT / ".hades/runtime/differential-replay.json"
SNAPSHOT_COLUMNS = 120
SNAPSHOT_ROWS = 40


class ReplayFailure(RuntimeError):
    """Raised when the replay cannot prove the expected contract."""

    def __init__(
        self,
        kind: str,
        step: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.step = step
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "step": self.step,
            "message": self.message,
            **self.details,
        }


def normalize_rows(text: str, columns: int, rows: int) -> list[str]:
    """Normalize plain snapshot output to exactly the requested cell bounds."""

    source_rows = text.replace("\r", "").splitlines()[:rows]
    source_rows.extend("" for _ in range(rows - len(source_rows)))
    return [source_row[:columns].rstrip(" ") for source_row in source_rows]


def cell_at(row: str, column: int) -> str:
    return row[column] if column < len(row) else " "


def describe_cell(value: str) -> str:
    if value == " ":
        return "<space>"
    return f"U+{ord(value):04X} {value}"


def contains_marker(text: str, marker: str) -> bool:
    """Match both full text and sparse cursor-addressed terminal output."""

    return marker in text or "".join(marker.split()) in "".join(text.split())


def contains_all_markers(text: str, markers: tuple[str, ...]) -> bool:
    return not missing_markers(text, markers)


def missing_markers(text: str, markers: tuple[str, ...]) -> list[str]:
    compact = "".join(text.split()).lower()
    return [marker for marker in markers if "".join(marker.lower().split()) not in compact]


def first_cell_diff(actual: list[str], expected: list[str]) -> dict[str, Any] | None:
    for row_index, (actual_row, expected_row) in enumerate(zip(actual, expected)):
        for column_index in range(SNAPSHOT_COLUMNS):
            actual_cell = cell_at(actual_row, column_index)
            expected_cell = cell_at(expected_row, column_index)
            if actual_cell != expected_cell:
                return {
                    "row": row_index + 1,
                    "column": column_index + 1,
                    "actual": describe_cell(actual_cell),
                    "expected": describe_cell(expected_cell),
                    "actual_row": actual_row,
                    "expected_row": expected_row,
                }
    return None


def load_json(path: Path, step: str) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ReplayFailure("input", step, f"could not read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ReplayFailure("input", step, f"expected an object in {path}")
    return value


def load_trace(path: Path) -> dict[str, Any]:
    trace = load_json(path, "trace")
    if trace.get("schema_version") != 1:
        raise ReplayFailure("input", "trace", f"unsupported trace schema in {path}")
    steps = trace.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ReplayFailure("input", "trace", f"trace has no replayable steps: {path}")
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get("id"), str):
            raise ReplayFailure("input", f"trace[{index}]", "each trace step needs an id")
        input_value = step.get("input")
        if not isinstance(input_value, dict):
            raise ReplayFailure("input", step["id"], "each trace step needs an input object")
        if input_value.get("kind") not in {"text", "key"}:
            raise ReplayFailure("input", step["id"], "trace input kind must be text or key")
        if not isinstance(input_value.get("value"), str):
            raise ReplayFailure("input", step["id"], "trace input value must be a string")
    return trace


def load_visual_contract(path: Path) -> dict[str, Any]:
    contract = load_json(path, "visual-contract")
    if contract.get("schema_version") != 1:
        raise ReplayFailure("input", "visual-contract", f"unsupported contract schema in {path}")
    steps = contract.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ReplayFailure("input", "visual-contract", f"contract has no steps: {path}")
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get("id"), str):
            raise ReplayFailure("input", f"visual-contract[{index}]", "each contract step needs an id")
        output = step.get("output")
        if not isinstance(output, dict):
            raise ReplayFailure("input", step["id"], "each contract step needs an output object")
        for marker_key in ("snapshot_markers", "pty_markers"):
            markers = output.get(marker_key)
            if not isinstance(markers, list) or not all(isinstance(marker, str) for marker in markers):
                raise ReplayFailure("input", step["id"], f"{marker_key} must be a string array")
    return contract


def run_snapshot(binary: Path, golden_path: Path, timeout: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [str(binary), "--snapshot"],
            cwd=ROOT,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReplayFailure("visual", "snapshot", f"snapshot command failed: {error}") from error

    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ReplayFailure(
            "visual",
            "snapshot",
            f"snapshot command exited with code {completed.returncode}",
            {"stderr": stderr},
        )

    try:
        golden = golden_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ReplayFailure("input", "golden-frame", f"could not read {golden_path}: {error}") from error

    actual_rows = normalize_rows(
        completed.stdout.decode("utf-8", errors="replace"), SNAPSHOT_COLUMNS, SNAPSHOT_ROWS
    )
    expected_rows = normalize_rows(golden, SNAPSHOT_COLUMNS, SNAPSHOT_ROWS)
    difference = first_cell_diff(actual_rows, expected_rows)
    if difference is not None:
        raise ReplayFailure(
            "visual",
            "snapshot",
            "normalized snapshot differs at the first divergent cell",
            {
                "dimensions": {"columns": SNAPSHOT_COLUMNS, "rows": SNAPSHOT_ROWS},
                "first_diff": difference,
            },
        )

    return {
        "name": "visual_snapshot",
        "status": "passed",
        "dimensions": {"columns": SNAPSHOT_COLUMNS, "rows": SNAPSHOT_ROWS},
        "normalization": [
            "remove carriage returns",
            "limit to 120 columns by 40 rows",
            "trim trailing ASCII spaces per row",
        ],
        "first_diff": None,
    }


def key_payload(value: str) -> bytes:
    payloads = {
        "Enter": b"\r",
        "Ctrl+C": b"\x03",
        "Ctrl+X": b"\x18",
        "Escape": b"\x1b",
    }
    try:
        return payloads[value]
    except KeyError as error:
        raise ReplayFailure("input", "trace", f"unsupported key in trace: {value}") from error


def contract_step(contract: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in contract["steps"]:
        if step["id"] == step_id:
            return step
    raise ReplayFailure("input", step_id, "visual contract is missing the replay step")


def run_behavior(
    binary: Path, trace: dict[str, Any], visual_contract: dict[str, Any], timeout: float
) -> dict[str, Any]:
    pid, master, slave_path = spawn(binary, SNAPSHOT_COLUMNS, SNAPSHOT_ROWS)
    output = bytearray()
    reaped = False
    replayed_steps: list[dict[str, Any]] = []
    interrupt_count = 0

    try:
        startup_markers = (
            "Hermes Agent",
            "Nous Research",
            "Available Tools",
            "Available Skills",
        )
        wait_for(
            pid,
            master,
            output,
            "startup",
            lambda text: all(contains_marker(text, marker) for marker in startup_markers),
            timeout,
        )
        startup_flags = terminal_flags(slave_path)
        if startup_flags["canonical"] or startup_flags["echo"]:
            raise ReplayFailure(
                "behavior",
                "startup",
                f"terminal did not enter raw mode: {startup_flags}",
                {"terminal_flags": startup_flags, "output_tail": output_tail(output)},
            )

        for step in trace["steps"]:
            step_id = step["id"]
            input_value = step["input"]
            kind = input_value["kind"]
            value = input_value["value"]
            if kind == "text":
                payload = value.encode("utf-8")
                send(master, payload)
                wait_for(
                    pid,
                    master,
                    output,
                    f"{step_id}: text input",
                    lambda text, expected=value: contains_marker(text, expected),
                    timeout,
                )
                observed = [value]
            else:
                send(master, key_payload(value))
                if value == "Enter":
                    busy_contract = contract_step(visual_contract, "busy")
                    busy_markers = tuple(busy_contract["output"]["pty_markers"])
                    wait_for(
                        pid,
                        master,
                        output,
                        f"{step_id}: busy transition",
                        lambda text, markers=busy_markers: contains_all_markers(text, markers),
                        timeout,
                    )
                    observed = list(busy_markers)
                else:
                    interrupt_count += 1
                    if interrupt_count == 1:
                        interrupted_contract = contract_step(visual_contract, "interrupted")
                        interrupted_markers = tuple(
                            interrupted_contract["output"]["pty_markers"]
                        )
                        wait_for(
                            pid,
                            master,
                            output,
                            f"{step_id}: interrupt transition",
                            lambda text, markers=interrupted_markers: contains_all_markers(
                                text, markers
                            ),
                            timeout,
                        )
                        observed = list(interrupted_markers)
                    elif interrupt_count == 2:
                        status = wait_for_exit(pid, master, output, timeout)
                        reaped = True
                        exit_status = describe_status(status)
                        if exit_status != {"kind": "exit", "code": 0}:
                            raise ReplayFailure(
                                "behavior",
                                step_id,
                                f"unexpected exit status: {exit_status}",
                                {"exit": exit_status, "output_tail": output_tail(output)},
                            )
                        observed = ["process exit 0"]
                    else:
                        raise ReplayFailure(
                            "input", step_id, "trace contains more than two Ctrl+C inputs"
                        )

            replayed_steps.append(
                {
                    "id": step_id,
                    "input": input_value,
                    "status": "passed",
                    "observed": observed,
                }
            )

        if not reaped:
            raise ReplayFailure(
                "behavior",
                "trace",
                "trace completed without a terminal exit step",
                {"output_tail": output_tail(output)},
            )

        raw_output = bytes(output)
        if b"\x1b[?1049h" not in raw_output:
            raise ReplayFailure(
                "behavior",
                "cleanup",
                "alternate-screen enter sequence was not observed",
                {"output_tail": output_tail(output)},
            )
        if b"\x1b[?1049l" not in raw_output:
            raise ReplayFailure(
                "behavior",
                "cleanup",
                "alternate-screen leave sequence was not observed",
                {"output_tail": output_tail(output)},
            )

        cleanup_flags = terminal_flags(slave_path)
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ReplayFailure(
                "behavior",
                "cleanup",
                f"terminal was not restored: {cleanup_flags}",
                {"terminal_flags": cleanup_flags, "output_tail": output_tail(output)},
            )

        return {
            "name": "behavior_replay",
            "status": "passed",
            "trace_observation": trace.get("observation_id"),
            "startup": {
                "dimensions": {"columns": SNAPSHOT_COLUMNS, "rows": SNAPSHOT_ROWS},
                "markers": list(startup_markers),
                "raw_mode": startup_flags,
            },
            "steps": replayed_steps,
            "cleanup": {
                "alternate_screen_entered": True,
                "alternate_screen_left": True,
                "cursor_restore_observed": b"\x1b[?25h" in raw_output,
                "terminal_flags": cleanup_flags,
            },
        }
    except ProbeError as error:
        raise ReplayFailure(
            "behavior",
            "replay",
            str(error),
            {"output_tail": output_tail(output)},
        ) from error
    finally:
        if not reaped:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        try:
            os.close(master)
        except OSError:
            pass


def run_session_overlay(
    binary: Path, trace: dict[str, Any], contract: dict[str, Any], timeout: float
) -> dict[str, Any]:
    pid, master, slave_path = spawn(binary, SNAPSHOT_COLUMNS, SNAPSHOT_ROWS)
    output = bytearray()
    reaped = False
    replayed_steps: list[dict[str, Any]] = []
    overlay_open = False

    try:
        startup_markers = (
            "Hermes Agent",
            "Nous Research",
            "Available Tools",
            "Available Skills",
        )
        wait_for(
            pid,
            master,
            output,
            "session-switcher startup",
            lambda text: all(contains_marker(text, marker) for marker in startup_markers),
            timeout,
        )
        startup_flags = terminal_flags(slave_path)
        if startup_flags["canonical"] or startup_flags["echo"]:
            raise ReplayFailure(
                "behavior",
                "session-switcher startup",
                f"terminal did not enter raw mode: {startup_flags}",
                {"terminal_flags": startup_flags, "output_tail": output_tail(output)},
            )

        for step in trace["steps"]:
            step_id = step["id"]
            input_value = step["input"]
            kind = input_value["kind"]
            value = input_value["value"]
            if kind == "text":
                if overlay_open:
                    raise ReplayFailure(
                        "behavior",
                        step_id,
                        "composer input was accepted while the overlay was open",
                    )
                send(master, value.encode("utf-8"))
                wait_for(
                    pid,
                    master,
                    output,
                    f"{step_id}: composer input",
                    lambda text, expected=value: contains_marker(text, expected),
                    timeout,
                )
                replayed_steps.append(
                    {"id": step_id, "input": input_value, "status": "passed", "observed": [value]}
                )
                continue

            send(master, key_payload(value))
            if value == "Ctrl+X":
                open_contract = contract_step(contract, "open-session-switcher")
                markers = tuple(open_contract["output"]["pty_markers"])
                wait_for(
                    pid,
                    master,
                    output,
                    f"{step_id}: overlay open",
                    lambda text, expected=markers: contains_all_markers(text, expected),
                    timeout,
                )
                overlay_open = True
                observed = list(markers)
            elif value == "Escape":
                if not overlay_open:
                    raise ReplayFailure("behavior", step_id, "Esc was replayed without an open overlay")
                output_length = len(output)
                wait_for(
                    pid,
                    master,
                    output,
                    f"{step_id}: overlay redraw",
                    lambda _text, previous_length=output_length: len(output) > previous_length,
                    timeout,
                )
                overlay_open = False
                observed = ["overlay closed"]
            elif value == "Ctrl+C":
                status = wait_for_exit(pid, master, output, timeout)
                reaped = True
                exit_status = describe_status(status)
                if exit_status != {"kind": "exit", "code": 0}:
                    raise ReplayFailure(
                        "behavior",
                        step_id,
                        f"unexpected exit status: {exit_status}",
                        {"exit": exit_status, "output_tail": output_tail(output)},
                    )
                observed = ["process exit 0"]
            else:
                raise ReplayFailure("input", step_id, f"unsupported session key: {value}")

            replayed_steps.append(
                {"id": step_id, "input": input_value, "status": "passed", "observed": observed}
            )

        if not reaped:
            raise ReplayFailure(
                "behavior",
                "session-switcher trace",
                "trace completed without a terminal exit step",
                {"output_tail": output_tail(output)},
            )

        raw_output = bytes(output)
        if b"\x1b[?1049h" not in raw_output or b"\x1b[?1049l" not in raw_output:
            raise ReplayFailure(
                "behavior",
                "session-switcher cleanup",
                "alternate-screen enter/leave sequence was not observed",
                {"output_tail": output_tail(output)},
            )
        cleanup_flags = terminal_flags(slave_path)
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ReplayFailure(
                "behavior",
                "session-switcher cleanup",
                f"terminal was not restored: {cleanup_flags}",
                {"terminal_flags": cleanup_flags, "output_tail": output_tail(output)},
            )

        return {
            "name": "session_switcher_replay",
            "status": "passed",
            "trace_observation": trace.get("observation_id"),
            "startup": {
                "dimensions": {"columns": SNAPSHOT_COLUMNS, "rows": SNAPSHOT_ROWS},
                "raw_mode": startup_flags,
            },
            "steps": replayed_steps,
            "cleanup": {
                "alternate_screen_entered": True,
                "alternate_screen_left": True,
                "cursor_restore_observed": b"\x1b[?25h" in raw_output,
                "terminal_flags": cleanup_flags,
            },
        }
    except ProbeError as error:
        raise ReplayFailure(
            "behavior",
            "session-switcher replay",
            str(error),
            {
                "output_tail": output_tail(output),
                "missing_markers": missing_markers(clean_output(output), markers)
                if "markers" in locals()
                else [],
            },
        ) from error
    finally:
        if not reaped:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        try:
            os.close(master)
        except OSError:
            pass


def emit_report(report: dict[str, Any], report_path: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--visual-contract", type=Path, default=DEFAULT_VISUAL_CONTRACT)
    parser.add_argument("--session-trace", type=Path, default=DEFAULT_SESSION_TRACE)
    parser.add_argument("--session-contract", type=Path, default=DEFAULT_SESSION_CONTRACT)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="seconds allowed for each replay assertion (default: 5)",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    binary = arguments.binary.resolve()
    trace_path = arguments.trace.resolve()
    golden_path = arguments.golden.resolve()
    visual_contract_path = arguments.visual_contract.resolve()
    session_trace_path = arguments.session_trace.resolve()
    session_contract_path = arguments.session_contract.resolve()
    report_path = arguments.report.resolve() if arguments.report is not None else None
    report: dict[str, Any] = {
        "schema_version": 1,
        "command": "differential-replay",
        "passed": False,
        "binary": str(binary),
        "trace": str(trace_path),
        "golden_frame": str(golden_path),
        "visual_contract": str(visual_contract_path),
        "session_trace": str(session_trace_path),
        "session_contract": str(session_contract_path),
        "checks": [],
    }

    if not binary.is_file():
        report["failure"] = {
            "kind": "input",
            "step": "binary",
            "message": f"binary not found: {binary}",
        }
        emit_report(report, report_path)
        return 2

    try:
        trace = load_trace(trace_path)
        visual_contract = load_visual_contract(visual_contract_path)
        session_trace = load_trace(session_trace_path)
        session_contract = load_visual_contract(session_contract_path)
        report["trace_observation"] = trace.get("observation_id")
        report["visual_contract_observation"] = visual_contract.get("observation_id")
        report["session_trace_observation"] = session_trace.get("observation_id")
        report["session_contract_observation"] = session_contract.get("observation_id")
        report["checks"].append(run_snapshot(binary, golden_path, arguments.timeout))
        report["checks"].append(
            run_behavior(binary, trace, visual_contract, arguments.timeout)
        )
        report["checks"].append(
            run_session_overlay(binary, session_trace, session_contract, arguments.timeout)
        )
        report["passed"] = True
    except ReplayFailure as error:
        report["failure"] = error.as_dict()
        if error.kind == "visual" and error.details.get("first_diff") is not None:
            report["first_diff"] = error.details["first_diff"]
    except (OSError, ValueError) as error:
        report["failure"] = {
            "kind": "runtime",
            "step": "report",
            "message": str(error),
        }

    try:
        emit_report(report, report_path)
    except OSError as error:
        print(json.dumps({"passed": False, "error": f"could not write report: {error}"}))
        return 2
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
