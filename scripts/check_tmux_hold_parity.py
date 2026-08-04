#!/usr/bin/env python3
"""Differential check: Rust configured-family runtime extensions vs Python.

Compares the HAD-132 hold-provider + tmux helpers between the Python
originals in `replay_composer.py` and the Rust port in `hades-dev`:

- contains_marker (raw substring or compact LOWERCASE match)
- key_payload (contract key -> tmux key)
- real tmux session lifecycle (start / send text / send key / capture /
  kill) and hold-provider request_seen gating against a live loopback
  request.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from replay_composer import (  # noqa: E402
    contains_marker as py_contains_marker,
    finish_hold_provider,
    hold_provider_environment,
    key_payload as py_key_payload,
    start_hold_provider,
    tmux_run,
)

failures = []

# 1. contains_marker parity (lowercase compact matching).
marker_samples = [
    ("Hades Agent v0.1.0  Underworld", "hades agent"),
    ("HadesAgent  Underworld", "Hades Agent"),
    ("a  b", "A B"),
    ("MUSING…", "musing"),
    ("Ctrl+C to interrupt", "Ctrl+C to interrupt"),
    ("abc", "x"),
]
py_markers = [
    {"screen": screen, "marker": marker, "match": py_contains_marker(screen, marker)}
    for screen, marker in marker_samples
]

# 2. key_payload parity.
key_samples = [
    "Enter", "Ctrl+A", "Ctrl+C", "Ctrl+G", "Ctrl+K", "Ctrl+V", "Backspace",
    "Up", "Down", "Left", "Right", "Home", "End", "Tab",
]
py_keys = []
for key in key_samples:
    try:
        py_keys.append({"key": key, "payload": py_key_payload(key)})
    except Exception as error:  # noqa: BLE001 - parity surfaces any divergence
        py_keys.append({"key": key, "error": str(error)})

# 3. Real tmux session lifecycle + hold provider.
session = f"had132-diff-py-{int(time.time() * 1000)}"
py_tmux = {}
start_result = tmux_run(
    "new-session", "-d", "-s", session, "-x", "120", "-y", "40", "-c", str(ROOT), "sh"
)
py_tmux["start_session"] = {"result": "ok" if start_result.returncode == 0 else start_result.stderr}
py_tmux["exists_after_start"] = tmux_run("has-session", "-t", session).returncode == 0
py_tmux["send_text"] = {"result": "ok"}
if tmux_run("send-keys", "-t", session, "-l", "hello-diff").returncode != 0:
    py_tmux["send_text"] = {"result": "error"}
py_tmux["send_key"] = {"result": "ok"}
if tmux_run("send-keys", "-t", session, "C-m").returncode != 0:
    py_tmux["send_key"] = {"result": "error"}
time.sleep(0.3)
py_tmux["capture_has_text"] = "hello-diff" in tmux_run("capture-pane", "-p", "-t", session).stdout
tmux_run("kill-session", "-t", session)
py_tmux["kill"] = {"result": "ok"}
py_tmux["exists_after_kill"] = tmux_run("has-session", "-t", session).returncode == 0

provider, provider_thread = start_hold_provider()
env = hold_provider_environment(provider)
base_url = env["HADES_PROVIDER_BASE_URL"]
py_hold = {
    "environment": {
        "base_url_prefix": base_url.startswith("http://127.0.0.1:"),
        "model": env["HADES_MODEL"],
        "api_key_empty": env["HADES_PROVIDER_API_KEY"] == "",
    },
    "request_seen_before_any": False,
    "request_seen_after_connect": None,
}
import socket  # noqa: E402

try:
    host = base_url.replace("http://", "")
    sock = socket.create_connection((host, 80), timeout=3.0)
    sock.close()
except OSError:
    pass
time.sleep(0.3)
py_hold["request_seen_after_connect"] = provider.request_seen.is_set()
finish_hold_provider(provider, provider_thread)

py_payload = {
    "markers": py_markers,
    "keys": py_keys,
    "tmux": py_tmux,
    "hold": py_hold,
}

# Run the Rust driver.
driver = ROOT / "target/debug/tmux_hold_diff"
if not driver.exists():
    print("driver missing; build with: cargo build --bin tmux_hold_diff")
    sys.exit(2)
result = subprocess.run([str(driver)], capture_output=True, text=True, check=False)
if result.returncode != 0:
    print("driver failed:", result.stderr[:500])
    sys.exit(1)
rust = json.loads(result.stdout)

if py_payload != rust:
    for section in ("markers", "keys", "tmux", "hold"):
        if py_payload[section] != rust[section]:
            print(f"DIFF {section}:")
            print("  py:  ", json.dumps(py_payload[section], sort_keys=True)[:800])
            print("  rust:", json.dumps(rust[section], sort_keys=True)[:800])
    print("RESULT: FAIL")
    sys.exit(1)
print("RESULT: PASS")
