# Hermes parity matrix

This matrix starts with unknowns on purpose. Replace an entry only when the
observation, contract, implementation, and oracle are all linked from a task.

| Surface | Status | Reference evidence | Hades oracle | Owner/task |
| --- | --- | --- | --- | --- |
| Startup sequence | Observed | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [startup frame](../../tests/fixtures/parity/OBS-0001-startup-120x40.txt) | HAD-001 / HAD-003 |
| Terminal initialization | Observed | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [lifecycle probe](../../scripts/probe_tui_lifecycle.py) | HAD-001 / HAD-003 |
| Terminal cleanup | Observed | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [lifecycle probe](../../scripts/probe_tui_lifecycle.py) | HAD-001 / HAD-003 |
| Initial geometry | Verified | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [golden snapshot test](../../crates/hades-tui/src/lib.rs) | HAD-001 / HAD-005 |
| Color and text styling | Unknown | — | — | HAD-001 / HAD-005 |
| Keymap | Observed | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) (tested subset) | [lifecycle trace](../../tests/fixtures/parity/OBS-0001-lifecycle.json) | HAD-001 / HAD-004 |
| Focus and navigation | Observed | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [lifecycle trace](../../tests/fixtures/parity/OBS-0001-lifecycle.json) | HAD-001 / HAD-004 |
| Session switcher overlay | Verified | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [session contract + differential replay](../../tests/fixtures/parity/OBS-0007-session-switcher.json) | HAD-008 |
| Input editing | Observed | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) (text entry only) | [lifecycle trace](../../tests/fixtures/parity/OBS-0001-lifecycle.json) | HAD-001 / HAD-004 |
| Submission behavior | Observed | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [submit/interrupt trace](../../tests/fixtures/parity/OBS-0003-submit-interrupt.json) | HAD-001 / HAD-004 |
| Busy/interrupt visual state | Verified | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [visual contract + differential replay](../../tests/fixtures/parity/OBS-0006-busy-interrupt-visual.json) | HAD-007 |
| Streaming behavior | Unknown | — | — | Future task |
| Setup-required error path | Verified | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [setup contract + differential replay](../../tests/fixtures/parity/OBS-0008-setup-required.json) | HAD-009 |
| Errors and retries | Observed | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) (setup-required path only) | [lifecycle trace](../../tests/fixtures/parity/OBS-0001-lifecycle.json) | Future task |
| Resize behavior | Observed | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [lifecycle probe](../../scripts/probe_tui_lifecycle.py) | HAD-003 / Future task |
| Persistence and recovery | Unknown | — | — | Future task |

Status vocabulary: `Unknown`, `Observed`, `Specified`, `Implemented`,
`Verified`, and `Blocked`. A row must not jump directly from `Unknown` to
`Verified`.

`Observed` means only that the named path was seen in the pinned reference
run. It does not claim complete coverage of the surface, visual equivalence,
or Hades implementation parity.
