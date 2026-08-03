#!/usr/bin/env python3
"""Differential check: Rust replay-unconfigured-startup vs Python replay.

Runs both replays against the same binary and requires identical reports.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "target/debug/hades"
SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "replay_unconfigured_startup"
BIN_NAME = sys.argv[2] if len(sys.argv) > 2 else "replay_unconfigured_startup"

py_report = ROOT / f".hades/runtime/{BIN_NAME}-py-parity.json"
rs_report = ROOT / f".hades/runtime/{BIN_NAME}-rs-parity.json"

py = subprocess.run(
    [sys.executable, f"scripts/{SCRIPT}.py", "--binary", str(BINARY), "--report", str(py_report)],
    cwd=ROOT,
    capture_output=True,
    text=True,
    check=False,
)
rs = subprocess.run(
    [str(ROOT / "target/debug" / BIN_NAME), "--binary", str(BINARY), "--report", str(rs_report)],
    cwd=ROOT,
    capture_output=True,
    text=True,
    check=False,
)

if py.returncode != 0 or rs.returncode != 0:
    print(f"FAIL: exit codes py={py.returncode} rs={rs.returncode}")
    print("py stderr:", py.stderr[-300:])
    print("rs stderr:", rs.stderr[-300:])
    sys.exit(1)

def normalize_report(data):
    """Normalize run-to-run timing fields before comparison."""
    text = json.dumps(data, sort_keys=True)
    # pre_delay_ms and observed_transition_ms vary by run; both replays
    # assert the same bounds, so compare their presence, not exact values.
    text = re.sub(r'"(pre_delay_ms|observed_transition_ms)": \d+', r'"\1": <timing>', text)
    return text


py_data = json.loads(py_report.read_text(encoding="utf-8"))
rs_data = json.loads(rs_report.read_text(encoding="utf-8"))
if normalize_report(py_data) != normalize_report(rs_data):
    print("FAIL: reports differ")
    import difflib

    a = normalize_report(py_data).splitlines()
    b = normalize_report(rs_data).splitlines()
    for line in list(difflib.unified_diff(a, b, "py", "rs", lineterm=""))[:40]:
        print(line)
    sys.exit(1)

print(f"RESULT: PASS ({len(py_data.get('cases', []))} cases identical)")
