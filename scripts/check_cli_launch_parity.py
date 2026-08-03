#!/usr/bin/env python3
"""Differential check: Rust replay-cli-launch vs Python replay_cli_launch.

Runs both replays against the same binary and requires identical reports.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "target/debug/hades"

py_report = ROOT / ".hades/runtime/cli-launch-py-parity.json"
rs_report = ROOT / ".hades/runtime/cli-launch-rs-parity.json"

py = subprocess.run(
    [sys.executable, "scripts/replay_cli_launch.py", "--binary", str(BINARY), "--report", str(py_report)],
    cwd=ROOT,
    capture_output=True,
    text=True,
    check=False,
)
rs = subprocess.run(
    [str(ROOT / "target/debug/replay_cli_launch"), "--binary", str(BINARY), "--report", str(rs_report)],
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

py_data = json.loads(py_report.read_text(encoding="utf-8"))
rs_data = json.loads(rs_report.read_text(encoding="utf-8"))
if py_data != rs_data:
    print("FAIL: reports differ")
    import difflib

    a = json.dumps(py_data, indent=1, sort_keys=True).splitlines()
    b = json.dumps(rs_data, indent=1, sort_keys=True).splitlines()
    for line in list(difflib.unified_diff(a, b, "py", "rs", lineterm=""))[:40]:
        print(line)
    sys.exit(1)

print(f"RESULT: PASS ({len(py_data.get('cases', []))} cases identical)")
