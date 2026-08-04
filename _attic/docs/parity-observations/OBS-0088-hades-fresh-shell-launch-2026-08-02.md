# Hades implementation observation: OBS-0088

- Subject: fresh-shell command resolution and installed TUI lifecycle
- Hades source: workspace implementation under test
- Terminal: clean Bash and Fish shells plus fresh 120x40 PTYs
- Capture: installed release launchers, version/help dispatch, visible startup, and cleanup
- Task: HAD-093
- Replay: `scripts/replay_fresh_shell_launch.py`

The user-facing launch path is now proved at the boundary that previously
caused an apparently inert `hades` command: the release launcher must be
installed in `~/.local/bin`, and that directory must be present on the shell's
PATH. The replay starts shells without profiles or configuration files, gives
them only that explicit PATH, and exercises both launcher spellings.

## Verified behavior

Fresh Bash and Fish shells resolve both `hades` and `Hades` to the current
`target/release/hades` artifact. Both names return the version marker and help
surface without entering the TUI. Fresh PTYs then run the no-argument and
explicit `tui` forms, reach the visible startup landmarks, enter raw mode and
the alternate screen, remain alive until Ctrl+C, exit with status 0, leave the
alternate screen, and restore canonical input and echo.

The replay is intentionally isolated: it uses a synthetic home/history
directory, does not read shell profiles, and does not contact a provider or
read credentials.

## Boundary

This does not claim that a user-local command can resolve when `~/.local/bin`
is absent from PATH. `just install-user` installs the release symlinks but does
not mutate shell configuration; a fresh terminal inherits the user's existing
PATH policy.

## Linked artifacts

- [fresh-shell replay](../../../scripts/replay_fresh_shell_launch.py)
- [launch fixture](../../../tests/fixtures/parity/OBS-0088-hades-fresh-shell-launch.json)
- [launcher installer](../../../scripts/install_user_launcher.sh)
- [task ledger](../../../.hades/tasks.json)
