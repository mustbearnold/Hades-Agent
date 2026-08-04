# 007 — Help and overlays

Status: active
Owner: project owner

## Purpose

The help surface (`/help`) and floating overlays render above the composer
with stable geometry: a bordered panel showing available commands and the
tool/skill inventory, plus slash-command completion and model/session
overlays. Geometry must survive terminal resizes.

## Requirements

- R1. `/help` opens a bordered panel (top/bottom borders of 116 `═` at
  120x40) listing commands, tools, and skills; the command row shows
  "/help Show available commands".
- R2. The panel floats above the composer row and below the info line; the
  composer is at row height−2, the info line at height−1.
- R3. On resize (120x40 → 100x30 → 160x50), the panel geometry is recomputed
  arithmetically: panel y = rows−5, composer y = rows−2.
- R4. Escape closes the panel; the lifecycle (open → stable → close) is
  captured with three stable samples before assertion.
- R5. On the unconfigured surface, `/help` shows the Setup Required
  transition after the 8 s delay with retained input; the first Ctrl+C
  clears the draft, the second exits.
- R6. Slash completion renders the exact observed `/he` items and applies
  `/help` on Tab before the fallback surface cycle.

## Acceptance criteria

- [ ] A1. Given a configured launch, when `/help` is typed, then a stable
      bordered panel renders with all markers and no "Setup Required".
- [ ] A2. Given the panel, when the terminal is resized, then the panel stays
      inside the viewport with the arithmetic geometry.
- [ ] A3. Given the panel, when Escape is pressed, then the panel closes and
      the surface returns to ready.

## Out of scope

- Gateway behavior and concurrent input (explicit unknowns).

## Open questions

- None recorded beyond the observed contracts (OBS-0098..OBS-0103).

## Links

Code: `crates/hades-tui/src/lib.rs` (help overlay) · Tests:
`scripts/replay_configured_help.py`, `scripts/replay_configured_help_lifecycle.py`,
`scripts/replay_configured_help_resize.py` · ADRs: ADR-0001
