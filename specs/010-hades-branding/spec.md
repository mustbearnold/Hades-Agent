# 010 — Hades branding

Status: active
Owner: project owner

## Purpose

Hades Agent carries a uniquely Hades-branded identity — bloody heavy-metal
logo, animated demon-skeleton with pitchfork, underworld theme — as a
deliberate, documented deviation from Hermes branding parity. The layout
still matches Hermes structurally (composer above the info line), but the
visual identity is Hades'.

## Requirements

- R1. The startup surface shows the Hades logo (rows 1–10), tagline, boxed
  title, animated demon-skeleton (4 braille frames, tick-driven, frame 0 =
  baked asset), model line, cwd, and session line.
- R2. The composer sits above the info line (composer row = height−2, info
  row = height−1); the help panel floats above the composer.
- R3. Animation frame 0 equals the baked static asset; golden tests and
  `--snapshot` replays use tick 0.
- R4. The deviation is recorded in the parity matrix
  (specs/001-parity-contract/matrix.md).
  branding parity with Hermes is explicitly out of scope.

## Acceptance criteria

- [ ] A1. Given a launch, when the startup surface renders, then the Hades
      logo and demon frame 0 match the baked assets (golden test).
- [ ] A2. Given a running TUI, when ticks advance, then the demon animation
      cycles its 4 frames.
- [ ] A3. Given the composer, when the info line is checked, then the
      composer is at height−2 and the info line at height−1.

## Out of scope

- Hermes branding parity (deliberate deviation).

## Open questions

- None recorded.

## Links

Code: `crates/hades-tui/assets/hades-*.txt` · Tests: golden tests in
`crates/hades-tui/src/lib.rs` · ADRs: deviation matrix in
`specs/001-parity-contract/matrix.md`
