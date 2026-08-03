#!/usr/bin/env python3
"""Differential check: Rust replay runtime vs probe_tui_lifecycle helpers.

Compares clean-output stripping, marker matching, and real-subprocess exit
status shapes between the Python and Rust runtimes.
"""
from __future__ import annotations

import json
import os
import pty
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from probe_tui_lifecycle import clean_output as py_clean  # noqa: E402
from probe_tui_lifecycle import describe_status, wait_for_exit as py_wait_exit  # noqa: E402

failures = []

# 1. clean_output parity.
raw = b"\x1b[31mred\x1b[0m\r\ntext\x1b]0;title\x07tail"
py_cleaned = py_clean(bytearray(raw))

# 2. marker_present parity (direct + compact whitespace matching).
markers = ["Hades Agent", "a b", "Underworld", "Available Tools"]
sample = "HadesAgent v0.1.0  Underworld  AvailableTools"
py_markers = {}
for marker in markers:
    py_markers[marker] = marker in sample or "".join(marker.split()) in "".join(sample.split())

# 3. Real subprocess exit shapes.
py_statuses = {}
for label, code in [("exit0", "exit 0"), ("exit7", "exit 7"), ("exit3", "exit 3")]:
    pid, master = pty.fork()
    if pid == 0:
        os.execv("/bin/sh", ["/bin/sh", "-c", code])
    try:
        status = py_wait_exit(pid, master, bytearray(), 5.0)
        py_statuses[label] = describe_status(status)
    finally:
        try:
            os.close(master)
        except OSError:
            pass

# Run the Rust driver.
driver = ROOT / "target/debug/replay_runtime_diff"
if not driver.exists():
    print("driver missing; build with: cargo build --bin replay_runtime_diff")
    sys.exit(2)
result = subprocess.run([str(driver)], capture_output=True, text=True, check=False)
if result.returncode != 0:
    print("driver failed:", result.stderr[:500])
    sys.exit(1)
rust = json.loads(result.stdout)

if py_cleaned != rust["clean_output"]:
    failures.append(("clean_output", py_cleaned, rust["clean_output"]))
for marker, py_result in py_markers.items():
    rust_result = rust["markers"].get(marker)
    if py_result != rust_result:
        failures.append((f"marker:{marker}", py_result, rust_result))
for label, py_shape in py_statuses.items():
    rust_shape = rust["statuses"].get(label)
    if json.dumps(py_shape, sort_keys=True) != json.dumps(rust_shape, sort_keys=True):
        failures.append((f"status:{label}", py_shape, rust_shape))

if failures:
    for label, py_value, rust_value in failures:
        print(f"DIFF {label}: py={py_value!r} rust={rust_value!r}")
    print("RESULT: FAIL")
    sys.exit(1)
print("RESULT: PASS")
