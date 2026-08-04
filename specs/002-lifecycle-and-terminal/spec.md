# 002 — Lifecycle and terminal ownership

Status: active
Owner: project owner

## Purpose

The process lifecycle — startup, terminal initialization, raw mode, alternate
screen, input handling, and clean teardown — is the first observable surface
users see and the foundation every other surface builds on. Hades must match
the observed Hermes lifecycle exactly, including the two-press Ctrl+C exit
semantics in the ready state.

## Requirements

- R1. Startup renders the observed surface (logo, tool/skill inventory, model
  line) before accepting input; startup markers are matched on the contiguous
  first frame.
- R2. The terminal enters raw mode (no canonical, no echo) on startup and is
  restored (canonical + echo) on exit; the alternate screen
  (`\x1b[?1049h`/`\x1b[?1049l`) is entered and left.
- R3. On the unconfigured surface, the first Ctrl+C clears the retained draft
  without exiting; a second Ctrl+C exits cleanly with code 0.
- R4. In the configured ready state, the first Ctrl+C echoes `^C` into the
  composer and exit happens on the second press. [inferred — parity contract
  unconfirmed; see open question]
- R5. Modified Enter (`Shift+Enter`/`Alt+Enter`) submits without a trailing
  newline; the mapping is captured in a direct-PTY oracle.
- R6. Every external boundary (PTY, signals, environment) has a fake or replay
  seam; the harness strips host environment leakage
  (`HERMES_DESKTOP`, `PYTHONPATH`, TMUX/STY/WAYLAND_DISPLAY/WSL_*).

## Acceptance criteria

- [ ] A1. Given a fresh unconfigured launch in a 120x40 PTY, when startup
      completes, then the observed startup markers render and the terminal is
      in raw mode.
- [ ] A2. Given the ready state, when Ctrl+C is pressed once, then the
      process stays alive; when pressed twice, then the process exits 0 and
      the terminal is restored.
- [ ] A3. Given a PTY replay, when it finishes, then the alternate screen was
      restored and terminal flags are canonical+echo.

## Out of scope

- Input editing and history (spec 003).
- Provider lifecycle (spec 005).

## Open questions

- Configured-state Ctrl+C: whether the first press echoes `^C` into the
  composer is not yet confirmed against the reference.

## Links

Code: `crates/hades-app`, `crates/hades-tui` · Tests: `scripts/probe_tui_lifecycle.py`,
`scripts/replay_unconfigured_input.py` · ADRs: ADR-0001
