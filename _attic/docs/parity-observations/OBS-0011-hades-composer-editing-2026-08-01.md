# Hades composer contract: OBS-0011

- Subject: Hades cursor editing, session-local history, and multiline fallback
- Reference: [Hermes input observation OBS-0010](OBS-0010-hermes-input-editing-keymap-2026-08-01.md)
- Product surface: `hades-core`, `hades-app`, `hades-tui`, and `hades-cli`
- Contract fixture: `tests/fixtures/parity/OBS-0011-hades-composer-editing.json`
- Executable oracle: `scripts/replay_composer.py`, focused Rust tests, and `just verify`
- Task: HAD-011

## Contract

Hades now owns input through a dedicated cursor-aware `Composer` rather than a
raw append-only string. The implemented reference-backed subset is:

- Left insertion, Backspace, Home, End, Ctrl+A, and Ctrl+K;
- successful plain-draft recording in session-local history;
- Up recall of the newest submitted draft and Down return to the empty draft;
- the observed backslash-plus-Enter fallback, which removes the escape
  backslash, inserts a newline, and keeps the draft unsubmitted.

The composer uses character boundaries for editing, so cursor movement and
deletion do not slice inside a UTF-8 code point. Terminal cursor styling and
grapheme-cell width are not claimed by this task.

## Oracle

The replay contract runs three isolated 120x40 tmux-backed PTYs:

1. editing walks `abc` through Left/X, Backspace, Home/Z, End/!, Ctrl+A, and
   Ctrl+K;
2. history submits `alpha`, interrupts the busy turn, recalls it with Up, and
   returns to the empty draft with Down;
3. multiline types `line-one`, sends backslash-plus-Enter, and finishes with
   `line-two` without submitting.

Each assertion captures the reconstructed screen with `tmux capture-pane -p`,
so sparse crossterm redraw fragments cannot satisfy a later state by accident.
The focused reducer and snapshot tests cover the same transitions without a
terminal.

## Boundary

This is an implemented subset, not a claim of complete Hermes input parity.
History is memory-only for the current Hades process. Disk persistence,
duplicate suppression, modified word movement, Delete, native Shift+Enter or
Alt+Enter, completion, Ctrl+G editor handoff, paste, mouse input, and queue
editing remain outside this task.

## Linked artifacts

- [Hades composer contract](../../../tests/fixtures/parity/OBS-0011-hades-composer-editing.json)
- [Reference input contract](../../../tests/fixtures/parity/OBS-0010-input-editing-keymap.json)
- [Composer model](../../../crates/hades-core/src/lib.rs)
- [Application reducer](../../../crates/hades-app/src/lib.rs)
- [Terminal key mapping](../../../crates/hades-cli/src/main.rs)
- [Renderer and snapshot tests](../../../crates/hades-tui/src/lib.rs)
- [PTY replay](../../../scripts/replay_composer.py)
