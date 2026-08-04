# 003 — Composer and input

Status: active
Owner: project owner

## Purpose

The composer is the primary input surface: a Unicode-safe editing model with
session-local history recall, multiline input, bracketed paste, clipboard
integration (native + OSC52), and editor handoff. Each slice is implemented
only where a reference observation exists.

## Requirements

- R1. The composer supports the observed keymap subset: cursor editing,
  terminal Home/End mapping, backslash-plus-Enter multiline input,
  session-local history recall (up/down), and slash completion (exact `/he`
  items, Tab applies `/help`).
- R2. Bracketed paste inserts at the cursor with preserved newlines and never
  implies submission; the empty-clipboard Ctrl+V path shows the exact miss
  message and leaves the draft unchanged.
- R3. Clipboard provider discovery follows the observed order: OSC52 (bare
  SSH) with a DA1 barrier, then native xclip fallback with the exact
  arguments (`-selection clipboard -out`).
- R4. OSC52 responses are bounded: a usable response wins before the native
  provider; malformed/empty responses and DA1-acknowledged timeouts fall back;
  the 500 ms timeout race and 256 KiB/512 KiB payload limits are observed
  controls.
- R5. Editor handoff (Ctrl+G) writes a temporary draft file, invokes the
  configured `EDITOR`, suspends/restores the terminal, and submits after a
  clean exit; empty output and nonzero cancellation are captured.
- R6. Modified Enter submits without trailing newline; the Shift/Alt mapping
  is verified in a direct-PTY oracle.

## Acceptance criteria

- [ ] A1. Given typed text, when Ctrl+V with a usable clipboard, then the
      text is inserted at the cursor with newlines preserved.
- [ ] A2. Given an empty clipboard, when Ctrl+V, then the exact miss message
      renders and the draft is unchanged.
- [ ] A3. Given a bare-SSH session, when Ctrl+V, then the OSC52 query and DA1
      barrier are emitted and a bounded response wins before xclip.
- [ ] A4. Given history, when up/down arrows are pressed, then session-local
      recall cycles with duplicate suppression and the newest-1,000 cap.

## Out of scope

- Mouse selection and image/path paste (explicit unknowns).
- Session overlay (spec 004).

## Open questions

- None recorded beyond the observed-slice boundaries in the parity matrix
  (specs/001-parity-contract/matrix.md).

## Links

Code: `crates/hades-tui/src/lib.rs`, `crates/hades-app` · Tests:
`scripts/replay_composer.py`, `scripts/replay_osc52_*.py`, `scripts/replay_clipboard*.py` ·
ADRs: ADR-0001
