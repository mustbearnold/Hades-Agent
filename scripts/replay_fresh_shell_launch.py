#!/usr/bin/env python3
"""Prove fresh Bash/Fish command resolution and the installed TUI lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import pty
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from probe_tui_lifecycle import (
    ProbeError,
    clean_output,
    describe_status,
    retain_slave_descriptor,
    set_window_size,
    slave_path_for_pid,
    terminal_flags,
    wait_for,
    wait_for_exit,
)


ROOT = Path(__file__).resolve().parents[1]
STARTUP_MARKERS = ("Hermes Agent", "Nous Research", "Available Tools", "Available Skills")


def runtime_environment(launcher_dir: Path, home: Path) -> dict[str, str]:
    return {
        "HOME": str(home),
        "HERMES_HOME": str(home / "hermes"),
        "PATH": os.pathsep.join((str(launcher_dir), "/usr/bin", "/bin")),
        "TERM": "xterm-256color",
        "COLUMNS": "120",
        "LINES": "40",
    }


def shell_path(name: str, environment: dict[str, str]) -> str:
    path = shutil.which(name, path=environment["PATH"])
    if path is None:
        raise ProbeError(f"required shell is unavailable: {name}")
    return path


def run_shell_command(
    shell: str,
    shell_options: list[str],
    command_name: str,
    launcher_dir: Path,
    home: Path,
) -> dict[str, object]:
    environment = runtime_environment(launcher_dir, home)
    command = f"command -v {command_name}; {command_name} --version; {command_name} --help"
    result = subprocess.run(
        [shell_path(shell, environment), *shell_options, "-c", command],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    expected_path = str(launcher_dir / command_name)
    if result.returncode != 0:
        raise ProbeError(f"{shell} {command_name}: shell command failed: {output.strip()}")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines or lines[0] != expected_path:
        raise ProbeError(
            f"{shell} {command_name}: command resolved to {lines[:1]}, expected {expected_path}"
        )
    if "Hades Agent 0.1.0" not in output or "Usage: hades" not in output:
        raise ProbeError(f"{shell} {command_name}: version/help output was incomplete: {output}")
    return {
        "shell": shell,
        "command": command_name,
        "resolved_path": lines[0],
        "version_marker": "Hades Agent 0.1.0",
        "help_marker": "Usage: hades",
    }


def spawn_shell(
    shell: str,
    shell_options: list[str],
    command_name: str,
    command_arguments: list[str],
    launcher_dir: Path,
    home: Path,
) -> tuple[int, int, str, Path]:
    history_home = Path(tempfile.mkdtemp(prefix="hades-fresh-shell-history-"))
    environment = runtime_environment(launcher_dir, home)
    command = "exec " + " ".join([command_name, *command_arguments])
    pid, master = pty.fork()
    if pid == 0:
        try:
            set_window_size(0, 120, 40)
            os.environ.clear()
            os.environ.update(environment)
            os.environ["HERMES_HOME"] = str(history_home / "hermes")
            os.makedirs(os.environ["HERMES_HOME"], exist_ok=True)
            shell_executable = shell_path(shell, environment)
            os.execv(shell_executable, [shell_executable, *shell_options, "-c", command])
        except BaseException as error:
            os.write(2, f"fresh-shell child failed to start: {error}\n".encode())
            os._exit(127)

    set_window_size(master, 120, 40)
    slave_path = slave_path_for_pid(pid)
    retain_slave_descriptor(slave_path)
    return pid, master, slave_path, history_home


def run_tui_case(
    shell: str,
    shell_options: list[str],
    command_name: str,
    command_arguments: list[str],
    launcher_dir: Path,
    home: Path,
    timeout: float,
) -> dict[str, object]:
    pid, master, slave_path, history_home = spawn_shell(
        shell,
        shell_options,
        command_name,
        command_arguments,
        launcher_dir,
        home,
    )
    output = bytearray()
    reaped = False
    try:
        wait_for(
            pid,
            master,
            output,
            f"{shell} {command_name} {' '.join(command_arguments) or 'default'} startup",
            lambda text: all(marker in text for marker in STARTUP_MARKERS),
            timeout,
        )
        startup_flags = terminal_flags(slave_path)
        if startup_flags["canonical"] or startup_flags["echo"]:
            raise ProbeError(f"{shell} {command_name}: startup was not raw: {startup_flags}")

        os.write(master, b"\x03")
        status = wait_for_exit(pid, master, output, timeout)
        reaped = True
        exit_status = describe_status(status)
        if exit_status != {"kind": "exit", "code": 0}:
            raise ProbeError(f"{shell} {command_name}: unexpected exit: {exit_status}")

        raw_output = bytes(output)
        if b"\x1b[?1049h" not in raw_output or b"\x1b[?1049l" not in raw_output:
            raise ProbeError(f"{shell} {command_name}: alternate-screen lifecycle was incomplete")
        cleanup_flags = terminal_flags(slave_path)
        if not cleanup_flags["canonical"] or not cleanup_flags["echo"]:
            raise ProbeError(f"{shell} {command_name}: terminal was not restored: {cleanup_flags}")
        return {
            "shell": shell,
            "command": command_name,
            "arguments": command_arguments,
            "startup_markers": list(STARTUP_MARKERS),
            "startup_raw_mode": startup_flags,
            "process_alive_until": "explicit Ctrl+C",
            "exit": exit_status,
            "alternate_screen_entered": True,
            "alternate_screen_left": True,
            "terminal_restored": cleanup_flags,
        }
    finally:
        if not reaped:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        os.close(master)
        shutil.rmtree(history_home, ignore_errors=True)


def write_report(report: dict[str, object], path: Path | None, status: int) -> int:
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher-dir", default="~/.local/bin")
    parser.add_argument("--release-binary", default="target/release/hades")
    parser.add_argument("--report")
    parser.add_argument("--timeout", type=float, default=5.0)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    launcher_dir = Path(arguments.launcher_dir).expanduser().resolve()
    release_binary = Path(arguments.release_binary)
    if not release_binary.is_absolute():
        release_binary = ROOT / release_binary
    release_binary = release_binary.resolve()
    report_path = Path(arguments.report) if arguments.report else None
    report: dict[str, object] = {
        "probe": "hades-fresh-shell-launch",
        "launcher_dir": str(launcher_dir),
        "release_binary": str(release_binary),
        "dimensions": {"columns": 120, "rows": 40},
        "shells": [],
        "tui_cases": [],
    }

    try:
        if not release_binary.is_file() or not os.access(release_binary, os.X_OK):
            raise ProbeError(f"release binary is missing or not executable: {release_binary}")
        launcher_paths: dict[str, str] = {}
        for command_name in ("hades", "Hades"):
            launcher = launcher_dir / command_name
            if not launcher.is_symlink():
                raise ProbeError(f"launcher is not a symlink: {launcher}")
            resolved = launcher.resolve(strict=True)
            if resolved != release_binary:
                raise ProbeError(f"{launcher} resolves to {resolved}, expected {release_binary}")
            launcher_paths[command_name] = str(resolved)
        report["launcher_paths"] = launcher_paths

        with tempfile.TemporaryDirectory(prefix="hades-fresh-shell-home-") as temporary_home:
            home = Path(temporary_home)
            report["shells"] = [
                run_shell_command("bash", ["--noprofile", "--norc"], command, launcher_dir, home)
                for command in ("hades", "Hades")
            ]
            report["shells"].extend(
                run_shell_command("fish", ["--no-config"], command, launcher_dir, home)
                for command in ("hades", "Hades")
            )
            report["tui_cases"] = [
                run_tui_case("bash", ["--noprofile", "--norc"], "hades", [], launcher_dir, home, arguments.timeout),
                run_tui_case("bash", ["--noprofile", "--norc"], "Hades", ["tui"], launcher_dir, home, arguments.timeout),
                run_tui_case("fish", ["--no-config"], "hades", ["tui"], launcher_dir, home, arguments.timeout),
                run_tui_case("fish", ["--no-config"], "Hades", [], launcher_dir, home, arguments.timeout),
            ]
        report["passed"] = True
    except (OSError, ProbeError, subprocess.SubprocessError) as error:
        report.update({"passed": False, "error": str(error)})
        return write_report(report, report_path, 1)

    return write_report(report, report_path, 0)


if __name__ == "__main__":
    raise SystemExit(main())
