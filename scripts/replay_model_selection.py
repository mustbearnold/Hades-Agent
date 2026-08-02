#!/usr/bin/env python3
"""Replay session-scoped model selection through two clean Hades processes."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from replay_configured_surfaces import assert_terminal_cleanup, modeled_marker
from replay_vertical_slice import (
    DEFAULT_BINARY,
    ReplayFailure,
    VerticalSliceServer,
    marker_present,
    run_setup,
    send,
    spawn_tui,
    stop_process,
    wait_for,
    wait_for_exit,
    write_report,
)


def wait_for_stream(
    pid: int,
    fd: int,
    output: bytearray,
    server: VerticalSliceServer,
    request_count: int,
    timeout: float,
) -> None:
    wait_for(
        pid,
        fd,
        output,
        f"request-{request_count}",
        lambda _text: len(server.records) >= request_count,
        timeout,
    )
    wait_for(
        pid,
        fd,
        output,
        f"first-delta-{request_count}",
        lambda text: marker_present(text, "First streamed delta."),
        timeout,
    )
    if server.response_complete.is_set():
        raise ReplayFailure(
            f"first-delta-{request_count}",
            "stream completed before the first delta was observed",
            bytes(output),
        )
    server.release_response.set()
    wait_for(
        pid,
        fd,
        output,
        f"completion-{request_count}",
        lambda _text: server.response_complete.is_set(),
        timeout,
    )
    wait_for(
        pid,
        fd,
        output,
        f"answer-{request_count}",
        lambda text: marker_present(text, "Final streamed answer."),
        timeout,
    )
    time.sleep(0.15)


def send_text(fd: int, text: str, delay: float = 0.04) -> None:
    for character in text:
        send(fd, character.encode())
        time.sleep(delay)


def open_and_select_model(
    pid: int,
    fd: int,
    output: bytearray,
    server: VerticalSliceServer,
    timeout: float,
) -> None:
    send_text(fd, "/model")
    wait_for(
        pid,
        fd,
        output,
        "model-completion",
        lambda text: marker_present(text, "/model"),
        timeout,
    )
    send(fd, b"\r")
    time.sleep(0.15)
    send(fd, b"\r")
    wait_for(
        pid,
        fd,
        output,
        "model-overlay",
        lambda text: marker_present(text, "Select provider (step 1/2)"),
        timeout,
    )
    if server.records:
        raise ReplayFailure("model-overlay", "opening /model submitted a provider request", bytes(output))

    send_text(fd, "palette")
    wait_for(
        pid,
        fd,
        output,
        "provider-filter",
        lambda _text: modeled_marker(output, "filter: palette"),
        timeout,
    )
    send(fd, b"\r")
    wait_for(
        pid,
        fd,
        output,
        "model-stage",
        lambda _text: modeled_marker(output, "Select model (step 2/2)"),
        timeout,
    )
    send(fd, b"\r")
    wait_for(
        pid,
        fd,
        output,
        "model-selection",
        lambda _text: modeled_marker(output, "model → palette-model"),
        timeout,
    )
    if server.records:
        raise ReplayFailure("model-selection", "model selection submitted a provider request", bytes(output))


def run_selected_process(
    binary: Path,
    home: Path,
    server: VerticalSliceServer,
    timeout: float,
) -> dict[str, Any]:
    pid, fd, slave_path = spawn_tui(binary, home)
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            fd,
            output,
            "selected-startup",
            lambda text: "Hermes Agent" in text and marker_present(text, "ready"),
            timeout,
        )
        open_and_select_model(pid, fd, output, server, timeout)
        send(fd, b"selected prompt\r")
        wait_for_stream(pid, fd, output, server, 1, timeout)

        record = server.records[0]
        body = record["body"]
        if record["path"] != "/v1/chat/completions":
            raise ReplayFailure("selected-request", f"unexpected request path: {record['path']}", bytes(output))
        if record["content_type"] != "application/json" or record["authorization_present"]:
            raise ReplayFailure("selected-request", "request crossed the sanitized local boundary", bytes(output))
        if body["model"] != "palette-model" or body["stream"] is not True:
            raise ReplayFailure("selected-request", "session model selection was not applied", bytes(output))
        if body["messages"][-1]["content"] != "selected prompt":
            raise ReplayFailure("selected-request", "selected prompt was not delivered", bytes(output))

        send(fd, b"\x03")
        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        cleanup = assert_terminal_cleanup(bytes(output), slave_path, status, "selected-cleanup")
        os.close(fd)
        return {
            "startup_ready": True,
            "selection": {
                "status_marker": "model → palette-model",
                "visible": True,
                "provider_request_during_selection": False,
            },
            "request": {
                "path": record["path"],
                "content_type": record["content_type"],
                "authorization_present": False,
                "model": body["model"],
                "message_roles": [message["role"] for message in body["messages"]],
                "prompt_marker": "selected prompt",
                "stream": body["stream"],
            },
            "stream": {
                "first_delta_visible_before_completion": True,
                "final_delta_marker": "Final streamed answer.",
            },
            "cleanup": cleanup,
        }
    finally:
        if not reaped:
            stop_process(pid, fd, False)


def run_fresh_process(
    binary: Path,
    home: Path,
    server: VerticalSliceServer,
    timeout: float,
) -> dict[str, Any]:
    server.request_seen.clear()
    server.first_delta_sent.clear()
    server.response_complete.clear()
    server.release_response.clear()
    pid, fd, slave_path = spawn_tui(binary, home)
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            fd,
            output,
            "fresh-startup",
            lambda text: "Hermes Agent" in text and marker_present(text, "ready"),
            timeout,
        )
        send(fd, b"fresh process prompt\r")
        wait_for_stream(pid, fd, output, server, 2, timeout)

        record = server.records[1]
        body = record["body"]
        if body["model"] != "vertical-model":
            raise ReplayFailure("fresh-request", "session selection persisted into a fresh process", bytes(output))
        if record["authorization_present"]:
            raise ReplayFailure("fresh-request", "fresh request exposed authorization material", bytes(output))

        send(fd, b"\x03")
        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        cleanup = assert_terminal_cleanup(bytes(output), slave_path, status, "fresh-cleanup")
        os.close(fd)
        return {
            "fresh_process": True,
            "request": {
                "path": record["path"],
                "model": body["model"],
                "authorization_present": False,
                "prompt_marker": "fresh process prompt",
            },
            "non_persistence": {
                "same_sidecar_reused": True,
                "configured_model_used_again": True,
            },
            "cleanup": cleanup,
        }
    finally:
        if not reaped:
            stop_process(pid, fd, False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=8.0)
    arguments = parser.parse_args()
    binary = arguments.binary.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "command": "replay-model-selection",
        "binary": str(binary),
        "dimensions": {"columns": 120, "rows": 40, "emulator": "direct PTY"},
        "steps": [],
        "passed": False,
    }
    home = Path(tempfile.mkdtemp(prefix="hades-model-selection-"))
    server = VerticalSliceServer()
    thread = None
    try:
        if not binary.is_file():
            raise ReplayFailure("binary", f"binary not found: {binary}")
        thread = threading.Thread(target=server.serve_forever, name="hades-model-selection", daemon=True)
        thread.start()
        report["steps"].append(run_setup(binary, home, server))
        sidecar = home / "hades-local-provider.conf"
        sidecar_before = sidecar.read_bytes()
        report["steps"].append(run_selected_process(binary, home, server, arguments.timeout))
        report["steps"].append(run_fresh_process(binary, home, server, arguments.timeout))
        if sidecar.read_bytes() != sidecar_before:
            raise ReplayFailure("persistence-boundary", "model selection changed the saved sidecar")
        if (home / "config.yaml").exists():
            raise ReplayFailure("persistence-boundary", "model selection created Hermes config.yaml")
        if len(server.records) != 2:
            raise ReplayFailure("request-count", f"expected two explicit requests, got {len(server.records)}")
        report["boundary"] = {
            "sidecar_unchanged": True,
            "hermes_config_created": False,
            "provider_request_count": len(server.records),
            "authorization_values_recorded": False,
            "external_network": False,
        }
        report["passed"] = True
    except (OSError, ReplayFailure, KeyError, TypeError, ValueError) as error:
        report["failure"] = error.as_dict() if isinstance(error, ReplayFailure) else {"message": str(error)}
        return write_report(report, arguments.report.resolve() if arguments.report else None, 1)
    finally:
        server.release_response.set()
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=2.0)
        shutil.rmtree(home, ignore_errors=True)
    return write_report(report, arguments.report.resolve() if arguments.report else None, 0)


if __name__ == "__main__":
    raise SystemExit(main())
