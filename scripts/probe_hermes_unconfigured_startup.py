#!/usr/bin/env python3
"""Capture Hermes startup with a fresh home and no configuration."""

from __future__ import annotations

import argparse
import json
import os
import pty
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from probe_hermes_setup_config_shape import config_shape, file_inventory
from probe_hermes_slash_commands import (
    COLUMNS,
    DEFAULT_REFERENCE,
    ROWS,
    SOURCE_COMMIT,
    ProbeFailure,
    clean_exit,
    safe_environment,
    safe_tail,
    stop,
    write_bytes,
)
from probe_hermes_terminal_palette import (
    child_status,
    drain,
    normalized,
    read_available,
    set_window_size,
)
from probe_hermes_full_setup import rendered_lines


BASE_MARKERS = (
    "Hermes Agent",
    "Nous Research",
    "Available Tools",
    "Available Skills",
)
PROMPT_MARKER = 'Try "/help" for commands'
STARTUP_PHASES = ("summoning hermes", "forging session", "starting agent")
OBSERVATION_WINDOW_SECONDS = 8.0


def spawn_unconfigured(reference: Path, home: Path) -> tuple[int, int]:
    environment = safe_environment(reference, home)
    for key in (
        "HADES_PROVIDER_BASE_URL",
        "HADES_PROVIDER_API_KEY",
        "HADES_MODEL",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
    ):
        environment.pop(key, None)

    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(reference)
        os.execvpe("uv", ["uv", "run", "hermes", "--tui"], environment)
    set_window_size(fd, COLUMNS, ROWS)
    os.set_blocking(fd, False)
    return pid, fd


def model_provider_marker(lines: list[str]) -> str | None:
    for line in lines:
        if "· Nous Research" not in line:
            continue
        model = line.split("· Nous Research", 1)[0].strip(" │")
        if model:
            return f"{model} · Nous Research"
    return None


def status_marker(lines: list[str]) -> str | None:
    for line in lines:
        if "starting agent" in line.lower():
            return "starting agent"
        if "─ ready" in line or "ready │" in line:
            return "ready"
    return None


def surface_state(raw: bytes) -> dict[str, Any] | None:
    lines = rendered_lines(raw)
    if not all(any(marker in line for line in lines) for marker in BASE_MARKERS):
        return None
    model = model_provider_marker(lines)
    status = status_marker(lines)
    if model is None or status is None:
        return None
    return {
        "base_markers": list(BASE_MARKERS),
        "model_provider": model,
        "status": status,
        "prompt_marker": PROMPT_MARKER if any(PROMPT_MARKER in line for line in lines) else None,
        "ready_footer_visible": status == "ready",
    }


def stable_surface(
    pid: int, fd: int, buffer: bytes, case: str, timeout: float
) -> tuple[bytes, dict[str, Any], int, int]:
    deadline = time.monotonic() + timeout
    previous: tuple[tuple[str, Any], ...] | None = None
    stable_samples = 0
    started = time.monotonic()
    while time.monotonic() < deadline:
        state = surface_state(buffer)
        if state is not None:
            signature = tuple(sorted(state.items()))
            if signature == previous:
                stable_samples += 1
            else:
                previous = signature
                stable_samples = 1
            if stable_samples >= 3:
                elapsed_ms = round((time.monotonic() - started) * 1000)
                return buffer, state, stable_samples, elapsed_ms
        exited, status = child_status(pid)
        if exited:
            buffer += read_available(fd)
            raise ProbeFailure(
                case,
                "stable-startup",
                "Hermes exited before the first stable startup surface",
                {"exit_status": status, "screen_tail": safe_tail(buffer)},
            )
        buffer = drain(pid, fd, buffer, 0.05)
    raise ProbeFailure(
        case,
        "stable-startup",
        f"timed out after {timeout:.1f}s waiting for the first stable startup surface",
        {"screen_tail": safe_tail(buffer)},
    )


def artifact_classes(paths: set[str]) -> list[str]:
    classes: set[str] = set()
    for name in paths:
        if name.startswith(".cache/uv/"):
            classes.add(".cache/uv/<artifact>")
        elif name == "SOUL.md":
            classes.add("SOUL.md")
        elif name.startswith("cache/"):
            classes.add("cache/<artifact>")
        elif name.startswith("logs/"):
            classes.add("logs/<artifact>")
        elif name == "projects.db":
            classes.add("projects.db")
        elif name.startswith("skills/"):
            classes.add("skills/<artifact>")
        elif name.startswith("state.db"):
            classes.add("state.db<suffix>")
        elif name == "tui-theme-boot.json":
            classes.add("tui-theme-boot.json")
        else:
            classes.add("<other-file>")
    return sorted(classes)


def phase_markers(raw: bytes) -> dict[str, bool]:
    text = normalized(raw).lower()
    return {phase: phase in text for phase in STARTUP_PHASES}


def observe_instance(
    reference: Path,
    home: Path,
    case: str,
    timeout: float,
    files_before: set[str],
) -> tuple[dict[str, Any], set[str]]:
    pid, fd = spawn_unconfigured(reference, home)
    buffer = b""
    try:
        buffer, first_state, stable_samples, startup_ms = stable_surface(
            pid, fd, buffer, case, timeout
        )
        first_files = file_inventory(home)
        first_config = config_shape(home / "config.yaml")
        phases = phase_markers(buffer)
        status_transitions = {first_state["status"]}
        ready_seen = first_state["ready_footer_visible"]
        observation_deadline = time.monotonic() + OBSERVATION_WINDOW_SECONDS
        while time.monotonic() < observation_deadline and not child_status(pid)[0]:
            buffer = drain(pid, fd, buffer, 0.15)
            state = surface_state(buffer)
            if state is not None:
                status_transitions.add(state["status"])
                ready_seen = ready_seen or state["ready_footer_visible"]

        write_bytes(fd, b"\x03")
        buffer = drain(pid, fd, buffer, 0.3)
        buffer, exited = clean_exit(pid, fd, buffer, case, timeout)
        files_after = file_inventory(home)
        after_config = config_shape(home / "config.yaml")
        return (
            {
                "id": case,
                "status": "passed",
                "first_surface": first_state,
                "stable_samples": stable_samples,
                "time_to_first_stable_ms": startup_ms,
                "startup_phases_observed": phases,
                "status_transitions": sorted(status_transitions),
                "ready_seen_during_observation_window": ready_seen,
                "observation_window_seconds": OBSERVATION_WINDOW_SECONDS,
                "config_at_first_surface": first_config,
                "config_after_cleanup": after_config,
                "config_exists_at_first_surface": first_config["exists"],
                "config_changed_during_cleanup": first_config != after_config,
                "artifact_classes_at_first_surface": artifact_classes(first_files - files_before),
                "artifact_classes_during_cleanup": artifact_classes(files_after - first_files),
                "clean_exit": exited,
            },
            files_after,
        )
    finally:
        if not child_status(pid)[0]:
            stop(pid, fd)
        else:
            try:
                os.close(fd)
            except OSError:
                pass


def emit_report(report: dict[str, Any], path: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(serialized, end="")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")


def safe_failure(error: BaseException) -> Any:
    if not isinstance(error, ProbeFailure):
        return str(error)
    details = dict(error.details)
    if "screen_tail" in details:
        details["screen_tail"] = safe_tail(str(details["screen_tail"]).encode())
    return {"case": error.case, "step": error.step, "message": error.message, **details}


def run_case(reference: Path, timeout: float) -> dict[str, Any]:
    case = "unconfigured-startup"
    root = Path(tempfile.mkdtemp(prefix="hades-hermes-unconfigured-startup-"))
    home = root / "home"
    home.mkdir()
    try:
        files_before = file_inventory(home)
        first, files_after_first = observe_instance(
            reference, home, "unconfigured-startup-first-process", timeout, files_before
        )
        second, _ = observe_instance(
            reference,
            home,
            "unconfigured-startup-fresh-process",
            timeout,
            files_after_first,
        )
        return {
            "id": case,
            "status": "passed",
            "input": [
                {
                    "kind": "environment",
                    "value": "fresh synthetic HOME/HERMES_HOME with no config or provider endpoint",
                },
                {
                    "kind": "observation",
                    "value": "wait for first stable startup surface without submitting a prompt",
                },
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "bounded cleanup"},
            ],
            "startup_markers": list(BASE_MARKERS),
            "startup_phases": list(STARTUP_PHASES),
            "first_process": first,
            "fresh_process": second,
            "fresh_process_repeats_status": first["first_surface"]["status"]
            == second["first_surface"]["status"],
            "fresh_process_repeats_model_provider": first["first_surface"]["model_provider"]
            == second["first_surface"]["model_provider"],
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    reference = args.reference.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "observation_id": "OBS-0059",
        "reference": {
            "path": "<reference-checkout>",
            "source_commit": SOURCE_COMMIT,
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "capture": "direct PTY with redacted ANSI screen model",
            },
        },
        "normalization": [
            "Reference checkout, synthetic HOME/HERMES_HOME paths, provider endpoints, credentials, session identifiers, timestamps, raw config values, and animated redraw bytes are omitted or replaced by placeholders.",
            "The process starts with no config and no Hades/OpenAI provider environment; no prompt is submitted, no setup choice is entered, and no external provider or OAuth flow is exercised.",
            "Startup timing is recorded only as this run's bounded diagnostic; it is not generalized into a universal Hermes timeout or readiness contract.",
            "Artifact evidence is reduced to normalized classes and config evidence contains only key paths, scalar/container kinds, existence, and byte counts.",
        ],
        "cases": [],
        "passed": False,
    }
    try:
        if not reference.is_dir():
            raise ProbeFailure("reference", "precondition", f"reference checkout does not exist: {reference}")
        report["cases"].append(run_case(reference, args.timeout))
        report["passed"] = True
    except (OSError, ProbeFailure, RuntimeError, ValueError) as error:
        report["failure"] = safe_failure(error)
    emit_report(report, args.report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
