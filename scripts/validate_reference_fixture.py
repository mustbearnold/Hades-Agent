#!/usr/bin/env python3
"""Validate a sanitized, provenance-bearing Hermes reference fixture."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "tests/fixtures/parity/OBS-0010-input-editing-keymap.json"
SHA1 = re.compile(r"^[0-9a-f]{40}$")
FORBIDDEN_MARKERS = ("local-test-key", "authorization:", "bearer ", "sk-")
# `sk-` keys appear at a token boundary ("sk-..."); hyphenated prose such as
# "task-specific" embeds `sk-` between word characters and must not trip the
# credential scan.
SK_TOKEN = re.compile(r"(^|[^a-z0-9_])sk-[a-z0-9]")


def fail(message: str) -> None:
    raise ValueError(message)


def require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{path} must be a non-empty string")
    return value


def require_string_list(value: Any, path: str, *, non_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (non_empty and not value):
        fail(f"{path} must be a non-empty string array")
    if not all(isinstance(item, str) and item.strip() for item in value):
        fail(f"{path} must contain only non-empty strings")
    return value


def validate_input_event(event: Any, path: str) -> None:
    if not isinstance(event, dict):
        fail(f"{path} must be an object")
    kind = require_string(event.get("kind"), f"{path}.kind")
    require_string(event.get("value"), f"{path}.value")
    if kind == "wait":
        return
    raw_hex = event.get("bytes_hex")
    if not isinstance(raw_hex, str) or not raw_hex.strip():
        fail(f"{path}.bytes_hex is required for non-wait input")
    compact = "".join(raw_hex.split())
    if len(compact) % 2 or not re.fullmatch(r"[0-9a-fA-F]+", compact):
        fail(f"{path}.bytes_hex must contain an even number of hexadecimal digits")


def validate_fixture(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"could not read {path}: {error}")
    if not isinstance(data, dict):
        fail("fixture must contain a JSON object")
    if data.get("schema_version") != 1:
        fail("schema_version must be 1")
    observation_id = require_string(data.get("observation_id"), "observation_id")
    reference = data.get("reference")
    if not isinstance(reference, dict):
        fail("reference must be an object")
    require_string(reference.get("product"), "reference.product")
    require_string(reference.get("version"), "reference.version")
    source_commit = require_string(reference.get("source_commit"), "reference.source_commit")
    if not SHA1.fullmatch(source_commit):
        fail("reference.source_commit must be a 40-character lowercase commit")
    terminal = reference.get("terminal")
    if not isinstance(terminal, dict) or not all(
        isinstance(terminal.get(key), int) and terminal[key] > 0 for key in ("columns", "rows")
    ):
        fail("reference.terminal must contain positive integer columns and rows")
    require_string(reference.get("capture"), "reference.capture")
    require_string_list(data.get("normalization"), "normalization")
    require_string_list(data.get("unknowns"), "unknowns")

    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        fail("steps must be a non-empty array")
    step_ids: set[str] = set()
    for index, step in enumerate(steps):
        path_prefix = f"steps[{index}]"
        if not isinstance(step, dict):
            fail(f"{path_prefix} must be an object")
        step_id = require_string(step.get("id"), f"{path_prefix}.id")
        if step_id in step_ids:
            fail(f"duplicate step id: {step_id}")
        step_ids.add(step_id)
        inputs = step.get("input_sequence")
        if not isinstance(inputs, list) or not inputs:
            fail(f"{path_prefix}.input_sequence must be a non-empty array")
        for event_index, event in enumerate(inputs):
            validate_input_event(event, f"{path_prefix}.input_sequence[{event_index}]")
        if not isinstance(step.get("output"), dict):
            fail(f"{path_prefix}.output must be an object")

    serialized = json.dumps(data, ensure_ascii=False).lower()
    for marker in FORBIDDEN_MARKERS:
        if marker != "sk-" and marker in serialized:
            fail(f"fixture contains a forbidden credential-like marker: {marker}")
    if SK_TOKEN.search(serialized):
        fail("fixture contains a forbidden credential-like marker: sk-")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args()
    path = args.fixture if args.fixture.is_absolute() else ROOT / args.fixture
    try:
        data = validate_fixture(path)
    except ValueError as error:
        print(f"reference fixture invalid: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "fixture": str(path.relative_to(ROOT)),
                "observation_id": data["observation_id"],
                "steps": len(data["steps"]),
                "valid": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
