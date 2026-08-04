#!/usr/bin/env python3
"""Prove both installed launcher spellings carry the model-selection slice."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from replay_fresh_shell_launch import run_shell_command


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INSTALL_DIR = Path.home() / ".local" / "bin"
SHELL_CASES = (("bash", ["--noprofile", "--norc"]), ("fish", ["--no-config"]))
ALIASES = ("hades", "Hades")


class LauncherReplayFailure(RuntimeError):
    pass


def run_alias(
    alias: str,
    launcher_dir: Path,
    report_dir: Path,
    timeout: float,
) -> dict[str, Any]:
    launcher = launcher_dir / alias
    expected_binary = (ROOT / "target" / "release" / "hades").resolve()
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise LauncherReplayFailure(f"missing executable launcher: {launcher}")
    resolved_binary = launcher.resolve()
    if resolved_binary != expected_binary:
        raise LauncherReplayFailure(
            f"{alias} resolves to {resolved_binary}, expected {expected_binary}"
        )

    nested_report = report_dir / f"model-selection-{alias}.json"
    command = [
        sys.executable,
        str(ROOT / "scripts" / "replay_model_selection.py"),
        "--binary",
        str(launcher),
        "--report",
        str(nested_report),
        "--timeout",
        str(timeout),
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise LauncherReplayFailure(f"{alias} model-selection replay failed")
    try:
        nested = json.loads(nested_report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LauncherReplayFailure(f"{alias} replay report was unreadable: {error}") from error
    if not nested.get("passed"):
        raise LauncherReplayFailure(f"{alias} replay report did not pass")
    boundary = nested.get("boundary", {})
    steps = nested.get("steps", [])
    if (
        boundary.get("provider_request_count") != 2
        or not boundary.get("sidecar_unchanged")
        or boundary.get("hermes_config_created")
        or len(steps) != 3
        or steps[1].get("request", {}).get("model") != "palette-model"
        or steps[2].get("request", {}).get("model") != "vertical-model"
    ):
        raise LauncherReplayFailure(f"{alias} replay crossed an unexpected model boundary")
    return {
        "alias": alias,
        "launcher": f"~/.local/bin/{alias}",
        "resolved_binary": "target/release/hades",
        "replay_report": nested_report.name,
        "status": "passed",
        "selected_model": "palette-model",
        "fresh_process_model": "vertical-model",
        "provider_request_count": 2,
        "sidecar_unchanged": True,
        "hermes_config_created": False,
        "external_network": False,
        "authorization_values_recorded": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", help="accepted for parity-checker compatibility; ignored (this replay runs the installed launcher aliases)")
    parser.add_argument("--launcher-dir", type=Path, default=DEFAULT_INSTALL_DIR)
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / ".hades" / "runtime" / "installed-model-selection-replay.json",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    arguments = parser.parse_args()
    launcher_dir = arguments.launcher_dir.expanduser().resolve()
    report_path = arguments.report if arguments.report.is_absolute() else ROOT / arguments.report
    report_path = report_path.resolve()
    report_dir = report_path.parent
    report: dict[str, Any] = {
        "schema_version": 1,
        "command": "replay-installed-model-selection",
        "launcher_dir": "~/.local/bin",
        "release_binary": "target/release/hades",
        "steps": [],
        "passed": False,
    }
    home = Path(tempfile.mkdtemp(prefix="hades-installed-model-selection-"))
    try:
        if not launcher_dir.is_dir():
            raise LauncherReplayFailure(f"launcher directory is missing: {launcher_dir}")
        if not (ROOT / "target" / "release" / "hades").is_file():
            raise LauncherReplayFailure("target/release/hades is missing")

        for shell, options in SHELL_CASES:
            for alias in ALIASES:
                report["steps"].append(
                    {
                        "shell_resolution": run_shell_command(
                            shell,
                            options,
                            alias,
                            launcher_dir,
                            home,
                        )
                    }
                )
        for alias in ALIASES:
            report["steps"].append(run_alias(alias, launcher_dir, report_dir, arguments.timeout))
        report["boundary"] = {
            "aliases": list(ALIASES),
            "shells": [shell for shell, _options in SHELL_CASES],
            "all_aliases_resolved": True,
            "all_alias_replays_passed": True,
            "external_network": False,
            "authorization_values_recorded": False,
            "hermes_config_created": False,
        }
        report["passed"] = True
    except (OSError, LauncherReplayFailure, KeyError, TypeError, ValueError) as error:
        report["failure"] = {"message": str(error)}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    finally:
        shutil.rmtree(home, ignore_errors=True)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
