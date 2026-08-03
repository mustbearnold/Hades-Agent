#!/usr/bin/env python3
"""Differential check: Rust validate_fixture vs Python validate_reference_fixture.

Runs both validators over every JSON fixture in tests/fixtures/parity/ and
requires identical exit codes and identical JSON summary output.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = sorted((ROOT / "tests/fixtures/parity").glob("*.json"))
PY = sys.executable
RUST = str(ROOT / "target/debug/validate_fixture")


def run(command: list[str], fixture: Path) -> tuple[int, str]:
    result = subprocess.run(
        [*command, str(fixture)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    summary = result.stdout.strip()
    # Both validators print pretty JSON; parse to compare structurally.
    try:
        parsed = json.loads(summary) if summary else None
    except json.JSONDecodeError:
        parsed = {"raw": summary}
    return result.returncode, json.dumps(parsed, sort_keys=True)


mismatches = []
for fixture in FIXTURES:
    py_code, py_out = run([PY, "scripts/validate_reference_fixture.py"], fixture)
    rust_code, rust_out = run([RUST], fixture)
    if py_code != rust_code or py_out != rust_out:
        mismatches.append((fixture.name, py_code, rust_code, py_out, rust_out))

if mismatches:
    for name, py_code, rust_code, py_out, rust_out in mismatches:
        print(f"DIFF {name}: py={py_code} rust={rust_code}")
        print(f"  py:   {py_out[:200]}")
        print(f"  rust: {rust_out[:200]}")
    print(f"RESULT: FAIL ({len(mismatches)}/{len(FIXTURES)} fixtures differ)")
    sys.exit(1)

print(f"RESULT: PASS ({len(FIXTURES)}/{len(FIXTURES)} fixtures identical)")
