# Hades implementation observation: OBS-0043

- Subject: default and explicit Hades TUI launch forms
- Hades source: workspace implementation under test
- Terminal: fresh 120x40 direct PTY
- Capture: normalized startup landmarks and terminal cleanup flags
- Task: HAD-044
- Replay: `scripts/replay_cli_launch.py`

The launch seam is intentionally small and product-facing. The no-argument
binary form and the explicit `tui` subcommand both select the same typed CLI
dispatch branch and then the same TUI runtime.

## Verified behavior

The targeted replay passed for both `hades` (no arguments) and `hades tui`.
Each process reached the stable startup landmarks `Hermes Agent`, `Nous
Research`, `Available Tools`, and `Available Skills`, entered raw mode, and
exited with status 0 after Ctrl+C. The alternate screen was left and the PTY
was restored to canonical mode with echo enabled in both cases.

The pure dispatch tests also preserve `--snapshot`, `--help`, `--version`, and
unknown-argument handling. `Hades` uses the same executable through the
user-local capitalized launcher created by `just install-user`.

## Boundaries

This observation does not claim that a shell already has `~/.local/bin` on its
PATH, nor does it mutate shell configuration. Refreshing the installed release
artifact remains an explicit `just install-user` action. It also does not claim
any provider, credential, network, or model behavior.

## Linked artifacts

- [CLI dispatch](../../../crates/hades-cli/src/main.rs)
- [Direct-PTY replay](../../../scripts/replay_cli_launch.py)
- [Task ledger](../../../.hades/tasks.json)
