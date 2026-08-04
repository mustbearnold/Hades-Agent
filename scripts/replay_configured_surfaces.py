#!/usr/bin/env python3
"""Replay the configured Hades journey through its primary interaction surfaces."""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from replay_vertical_slice import (
    DEFAULT_BINARY,
    ReplayFailure,
    VerticalSliceServer,
    marker_present,
    run_setup,
    send,
    spawn_tui,
    stop_process,
    terminal_flags,
    wait_for,
    wait_for_exit,
    wait_for_rendered,
    write_report,
)
from probe_hermes_terminal_palette import Screen as AnsiScreen


def modeled_marker(output: bytearray, marker: str) -> bool:
    screen = AnsiScreen()
    screen.feed(bytes(output))
    return marker_present("\n".join(screen.lines()), marker)


def wait_for_request(
    pid: int,
    fd: int,
    output: bytearray,
    server: VerticalSliceServer,
    count: int,
    timeout: float,
) -> None:
    wait_for(
        pid,
        fd,
        output,
        f"request-{count}",
        lambda _text: len(server.records) >= count,
        timeout,
    )
    wait_for(
        pid,
        fd,
        output,
        f"response-{count}",
        lambda text: marker_present(text, "Final streamed answer."),
        timeout,
    )
    if not server.response_complete.wait(timeout):
        raise ReplayFailure(f"response-{count}", "local response did not complete", bytes(output))
    # Let the event loop consume the completion boundary before the next key.
    time.sleep(0.15)


def assert_terminal_cleanup(
    raw: bytes,
    slave_path: str,
    status: int,
    step: str,
) -> dict[str, Any]:
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        raise ReplayFailure(step, f"unexpected exit status: {status}", raw)
    flags = terminal_flags(slave_path)
    if b"\x1b[?1049l" not in raw or not flags["canonical"] or not flags["echo"]:
        raise ReplayFailure(step, f"terminal restoration failed: {flags}", raw)
    return {
        "exit": {"kind": "exit", "code": 0},
        "alternate_screen_left": True,
        "terminal_restored": flags,
    }


def run_first_process(
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
            "startup",
            lambda text: "Hades Agent" in text and marker_present(text, "ready"),
            timeout,
        )

        send(fd, b"/he")
        wait_for_rendered(
            pid,
            fd,
            output,
            "slash-completion",
            lambda text: marker_present(text, "completions") and marker_present(text, "/help"),
            timeout,
        )
        if server.records:
            raise ReplayFailure("slash-completion", "completion opened a provider request", bytes(output))
        send(fd, b"\t")
        time.sleep(0.15)
        send(fd, b"\x1b")
        time.sleep(0.15)
        send(fd, b"/model")
        time.sleep(0.15)
        send(fd, b"\r")
        time.sleep(0.15)
        send(fd, b"\r")
        wait_for_rendered(
            pid,
            fd,
            output,
            "model-overlay",
            lambda text: marker_present(text, "Model picker")
            and marker_present(text, "Select provider (step 1/2)"),
            timeout,
        )
        if server.records:
            raise ReplayFailure("model-overlay", "model overlay opened a provider request", bytes(output))
        send(fd, b"\x1b")
        time.sleep(0.15)

        send(fd, b"\x18")
        wait_for(
            pid,
            fd,
            output,
            "sessions-overlay",
            lambda text: marker_present(text, "Sessions") and marker_present(text, "current session"),
            timeout,
        )
        if server.records:
            raise ReplayFailure("sessions-overlay", "sessions overlay opened a provider request", bytes(output))
        send(fd, b"\x1b")
        time.sleep(0.15)

        send(fd, b"surface prompt one")
        time.sleep(0.15)
        send(fd, b"\r")
        wait_for_request(pid, fd, output, server, 1, timeout)
        send(fd, b"surface prompt two")
        time.sleep(0.15)
        send(fd, b"\r")
        wait_for_request(pid, fd, output, server, 2, timeout)

        send(fd, b"\x1b[A")
        wait_for(
            pid,
            fd,
            output,
            "history-newest",
            lambda _text: modeled_marker(output, "surface prompt two"),
            timeout,
        )
        send(fd, b"\x1b[A")
        wait_for(
            pid,
            fd,
            output,
            "history-previous",
            lambda _text: modeled_marker(output, "surface prompt one"),
            timeout,
        )
        send(fd, b"\x1b[B")
        time.sleep(0.15)
        if len(server.records) != 2:
            raise ReplayFailure(
                "history-navigation",
                f"history navigation submitted a request (count={len(server.records)})",
                bytes(output),
            )

        send(fd, b"\x03")
        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        cleanup = assert_terminal_cleanup(bytes(output), slave_path, status, "first-cleanup")
        os.close(fd)
        history_path = home / ".hermes_history"
        if not history_path.is_file():
            raise ReplayFailure("history-persistence", "history file was not written", bytes(output))
        history = history_path.read_text(encoding="utf-8")
        if "surface prompt one" not in history or "surface prompt two" not in history:
            raise ReplayFailure("history-persistence", "submitted prompts were not persisted", bytes(output))
        return {
            "startup_ready": True,
            "slash_completion": {"typed_prefix": "/he", "visible": True, "applied_without_submit": True},
            "overlays": {
                "model_picker": {"opened": True, "closed_with_escape": True},
                "sessions": {"opened": True, "closed_with_escape": True},
            },
            "history": {
                "same_process_up_down": True,
                "submitted_prompt_count": 2,
                "persisted": True,
            },
            "cleanup": cleanup,
        }
    finally:
        if not reaped:
            stop_process(pid, fd, False)


def run_history_restart(
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
            "history-restart-startup",
            lambda text: "Hades Agent" in text and marker_present(text, "ready"),
            timeout,
        )
        before_history_request_count = len(server.records)
        send(fd, b"\x1b[A")
        time.sleep(0.2)
        if len(server.records) != before_history_request_count:
            raise ReplayFailure(
                "history-restart-newest",
                "history navigation opened a provider request",
                bytes(output),
            )
        send(fd, b"!")
        time.sleep(0.1)
        send(fd, b"\r")
        expected_request_count = before_history_request_count + 1
        wait_for_request(pid, fd, output, server, expected_request_count, timeout)
        recalled_prompt = server.records[expected_request_count - 1]["body"]["messages"][-1]["content"]
        if recalled_prompt != "surface prompt two!":
            raise ReplayFailure(
                "history-restart-newest",
                "Up did not restore the newest persisted prompt",
                bytes(output),
            )
        send(fd, b"\x03")
        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        cleanup = assert_terminal_cleanup(bytes(output), slave_path, status, "history-restart-cleanup")
        os.close(fd)
        return {
            "history_available_after_restart": True,
            "history_recall_verified_by_request": True,
            "provider_requests": 1,
            "cleanup": cleanup,
        }
    finally:
        if not reaped:
            stop_process(pid, fd, False)


def run_clipboard_process(
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
            "clipboard-startup",
            lambda text: "Hades Agent" in text and marker_present(text, "ready"),
            timeout,
        )
        send(fd, b"\x16")
        time.sleep(0.3)
        if len(server.records) != 3:
            raise ReplayFailure("clipboard-insert", "Ctrl+V submitted before Enter", bytes(output))
        send(fd, b"\r")
        wait_for_request(pid, fd, output, server, 4, timeout)
        record = server.records[3]
        prompt = record["body"]["messages"][-1]["content"]
        if prompt != "configured clipboard payload":
            raise ReplayFailure("clipboard-request", "clipboard text was not delivered to the request", bytes(output))
        send(fd, b"\x03")
        status = wait_for_exit(pid, fd, output, timeout)
        reaped = True
        cleanup = assert_terminal_cleanup(bytes(output), slave_path, status, "clipboard-cleanup")
        os.close(fd)
        return {
            "clipboard": {
                "provider": "synthetic xclip",
                "inserted_without_submit": True,
                "submitted_on_enter": True,
                "request_prompt_marker": "configured clipboard payload",
            },
            "cleanup": cleanup,
        }
    finally:
        if not reaped:
            stop_process(pid, fd, False)


def make_fake_clipboard(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    command = directory / "xclip"
    command.write_text("#!/bin/sh\nprintf '%s\\n' 'configured clipboard payload'\n", encoding="utf-8")
    command.chmod(command.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=8.0)
    arguments = parser.parse_args()
    binary = arguments.binary.resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "command": "replay-configured-surfaces",
        "binary": str(binary),
        "dimensions": {"columns": 120, "rows": 40, "emulator": "direct PTY"},
        "steps": [],
        "passed": False,
    }
    home = Path(tempfile.mkdtemp(prefix="hades-configured-surfaces-"))
    clipboard_bin = home / "fake-bin"
    make_fake_clipboard(clipboard_bin)
    old_environment = os.environ.copy()
    server = VerticalSliceServer()
    server.release_response.set()
    os.environ["PATH"] = f"{clipboard_bin}:{old_environment.get('PATH', '')}"
    for key in ("WAYLAND_DISPLAY", "WSL_INTEROP", "WSL_DISTRO_NAME", "SSH_TTY", "SSH_CONNECTION", "SSH_CLIENT", "TMUX", "STY"):
        os.environ.pop(key, None)
    thread = None
    try:
        if not binary.is_file():
            raise ReplayFailure("binary", f"binary not found: {binary}")
        thread = threading.Thread(
            target=server.serve_forever, name="hades-configured-surfaces", daemon=True
        )
        thread.start()
        report["steps"].append(run_setup(binary, home, server))
        report["steps"].append(run_first_process(binary, home, server, arguments.timeout))
        report["steps"].append(run_history_restart(binary, home, server, arguments.timeout))
        report["steps"].append(run_clipboard_process(binary, home, server, arguments.timeout))
        if (home / "config.yaml").exists():
            raise ReplayFailure("config-boundary", "Hermes config.yaml was created or changed", b"")
        if len(server.records) != 4:
            raise ReplayFailure("request-count", f"expected four requests, got {len(server.records)}", b"")
        report["request_summary"] = {
            "count": len(server.records),
            "paths": [record["path"] for record in server.records],
            "models": [record["body"]["model"] for record in server.records],
            "prompt_markers": [record["body"]["messages"][-1]["content"] for record in server.records],
            "stream": all(record["body"]["stream"] is True for record in server.records),
        }
        report["passed"] = True
    except (OSError, ReplayFailure, ValueError, KeyError, TypeError) as error:
        report["failure"] = (
            error.as_dict() if isinstance(error, ReplayFailure) else {"message": str(error)}
        )
        return write_report(report, arguments.report.resolve() if arguments.report else None, 1)
    finally:
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=2.0)
        os.environ.clear()
        os.environ.update(old_environment)
        shutil.rmtree(home, ignore_errors=True)
    return write_report(report, arguments.report.resolve() if arguments.report else None, 0)


if __name__ == "__main__":
    raise SystemExit(main())
