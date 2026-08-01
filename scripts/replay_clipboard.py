#!/usr/bin/env python3
"""Replay the implemented Hades empty-clipboard fallback in a tmux PTY."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from replay_composer import ComposerReplayFailure, emit_report, load_contract, run_case


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "tests/fixtures/parity/OBS-0015-hades-empty-clipboard.json"
DEFAULT_BINARY = ROOT / "target/debug/hades"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=5.0)
    arguments = parser.parse_args()
    binary = arguments.binary.resolve()
    contract_path = arguments.contract.resolve()
    report: dict[str, object] = {
        "schema_version": 1,
        "command": "replay-clipboard",
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
        checks = report["checks"]
        assert isinstance(checks, list)
        for ordinal, case in enumerate(contract["cases"], start=1):
            checks.append(
                run_case(
                    binary,
                    case,
                    arguments.timeout,
                    ordinal,
                    session_prefix="had015-clipboard",
                )
            )
        report["passed"] = True
    except ComposerReplayFailure as error:
        report["failure"] = error.as_dict()
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["failure"] = {"case": "report", "step": "runtime", "message": str(error)}

    try:
        emit_report(report, arguments.report.resolve() if arguments.report else None)
    except OSError as error:
        print(json.dumps({"passed": False, "error": f"could not write report: {error}"}))
        return 2
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
