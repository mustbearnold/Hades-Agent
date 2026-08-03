#!/usr/bin/env python3
"""Differential check: Rust hades-dev Screen vs Python Screen on live Hades output."""
from __future__ import annotations

import fcntl
import json
import os
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time

ROOT = "/home/mustbearn/Projects/Hades Agent"
BINARY = f"{ROOT}/target/debug/hades"
COLUMNS, ROWS = 120, 50

# 1. Capture raw Hades startup bytes on a 120x50 PTY.
master, slave = os.openpty()
os.set_blocking(master, False)
env = dict(os.environ)
env["TERM"] = "xterm-256color"
env["COLUMNS"] = str(COLUMNS)
env["LINES"] = str(ROWS)
proc = subprocess.Popen([BINARY], stdin=slave, stdout=slave, stderr=slave, env=env, cwd=ROOT)
os.close(slave)
fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLUMNS, 0, 0))

raw = bytearray()
deadline = time.monotonic() + 15
while time.monotonic() < deadline:
    r, _, _ = select.select([master], [], [], 0.2)
    if r:
        try:
            chunk = os.read(master, 65536)
            if not chunk:
                break
            raw.extend(chunk)
        except OSError:
            break
try:
    os.kill(proc.pid, signal.SIGKILL)
except ProcessLookupError:
    pass
proc.wait(timeout=5)
print(f"captured {len(raw)} raw bytes")

# 2. Feed through Python Screen.
sys.path.insert(0, f"{ROOT}/scripts")
from probe_hermes_terminal_palette import Screen as PyScreen  # noqa: E402

py_screen = PyScreen(COLUMNS, ROWS)
py_screen.feed(bytes(raw))
py_lines = py_screen.lines()
py_inventory = py_screen.inventory()

# 3. Feed through Rust Screen via a small driver binary.
import subprocess as sp  # noqa: E811

driver = f"{ROOT}/target/debug/screen_diff"
if not os.path.exists(driver):
    print("driver binary missing; build with: cargo build --bin screen_diff")
    sys.exit(2)
result = sp.run([driver], input=bytes(raw), capture_output=True)
if result.returncode != 0:
    print("driver failed:", result.stderr.decode()[:500])
    sys.exit(1)
rust_report = json.loads(result.stdout.decode())

# 4. Compare.
mismatches = 0
for row in range(ROWS):
    if py_lines[row] != rust_report["lines"][row]:
        mismatches += 1
        if mismatches <= 3:
            print(f"row {row} differs:\n  py:   {py_lines[row][:60]!r}\n  rust: {rust_report['lines'][row][:60]!r}")
print(f"line mismatches: {mismatches}/{ROWS}")

py_inv = json.dumps(py_inventory, sort_keys=True)
rust_inv = json.dumps(rust_report["inventory"], sort_keys=True)
print(f"inventory match: {py_inv == rust_inv}")
if py_inv != rust_inv:
    print("py:", py_inv[:400])
    print("rust:", rust_inv[:400])

# 5. Marker style spot check.
for marker in ("Hades Agent", "Available Tools", "ready"):
    py_style = py_screen.marker_style(marker)
    rust_marker = rust_report["markers"].get(marker)
    print(f"marker {marker!r}: py={py_style} rust={rust_marker} match={py_style == rust_marker}")

ok = mismatches == 0 and py_inv == rust_inv
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
