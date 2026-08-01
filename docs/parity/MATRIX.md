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
| Keymap | Observed | [OBS-0010](observations/OBS-0010-hermes-input-editing-keymap-2026-08-01.md) (terminal-observed subset) | [composer replay](../../scripts/replay_composer.py) + [completion replay](../../scripts/replay_completion.py) + [paste replay](../../scripts/replay_paste.py) + [editor replay](../../scripts/replay_editor.py) + [clipboard replay](../../scripts/replay_clipboard.py) | HAD-010 / HAD-011 / HAD-012 / HAD-013 / HAD-014 / HAD-015 |
| Native modified Enter | Verified | [OBS-0020](observations/OBS-0020-hermes-modified-enter-2026-08-01.md) (direct-PTY CSI-u capture) | [OBS-0021 modified-Enter replay + focused tests](observations/OBS-0021-hades-modified-enter-2026-08-01.md) | HAD-020 / HAD-021 |
| Focus and navigation | Observed | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [lifecycle trace](../../tests/fixtures/parity/OBS-0001-lifecycle.json) | HAD-001 / HAD-004 |
| Session switcher overlay | Verified | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [session contract + differential replay](../../tests/fixtures/parity/OBS-0007-session-switcher.json) | HAD-008 |
| Input editing | Verified | [OBS-0010](observations/OBS-0010-hermes-input-editing-keymap-2026-08-01.md) | [OBS-0011 composer replay + focused tests](../../docs/parity/observations/OBS-0011-hades-composer-editing-2026-08-01.md) | HAD-011 |
| Slash completion | Verified | [OBS-0010](observations/OBS-0010-hermes-input-editing-keymap-2026-08-01.md) | [OBS-0012 completion replay + focused tests](observations/OBS-0012-hades-slash-completion-2026-08-01.md) | HAD-012 |
| Bracketed paste | Verified | [OBS-0010](observations/OBS-0010-hermes-input-editing-keymap-2026-08-01.md) | [OBS-0013 paste replay + focused tests](observations/OBS-0013-hades-bracketed-paste-2026-08-01.md) | HAD-013 |
| Editor handoff (unchanged draft) | Verified | [OBS-0010](observations/OBS-0010-hermes-input-editing-keymap-2026-08-01.md) + [OBS-0018](observations/OBS-0018-hermes-editor-outcomes-2026-08-01.md) | [OBS-0014 editor replay + focused tests](observations/OBS-0014-hades-editor-handoff-2026-08-01.md) | HAD-014 / HAD-018 |
| Editor modified/cancelled outcomes | Verified | [OBS-0018](observations/OBS-0018-hermes-editor-outcomes-2026-08-01.md) | [OBS-0019 editor-outcome replay + focused tests](observations/OBS-0019-hades-editor-outcomes-2026-08-01.md) | HAD-018 / HAD-019 |
| Empty clipboard fallback | Verified | [OBS-0010](observations/OBS-0010-hermes-input-editing-keymap-2026-08-01.md) | [OBS-0015 clipboard replay + focused tests](observations/OBS-0015-hades-empty-clipboard-2026-08-01.md) | HAD-015 |
| Successful text clipboard | Verified (native text path) | [OBS-0022](observations/OBS-0022-hermes-text-clipboard-2026-08-01.md) (synthetic xclip direct-PTY capture) | [OBS-0023 text-clipboard replay + focused tests](observations/OBS-0023-hades-text-clipboard-2026-08-01.md) | HAD-022 / HAD-023 |
| Remote OSC52 clipboard precedence | Verified (bare SSH_TTY path) | [OBS-0024](observations/OBS-0024-hermes-osc52-clipboard-2026-08-01.md) (synthetic SSH_TTY direct-PTY capture) | [OBS-0025 OSC52 replay + focused tests](observations/OBS-0025-hades-osc52-clipboard-2026-08-01.md) | HAD-024 / HAD-025 |
| Remote OSC52 response boundaries | Verified (bare SSH_TTY fallback controls) | [OBS-0026](observations/OBS-0026-hermes-osc52-response-boundaries-2026-08-01.md) (empty/malformed direct-PTY controls) | [OBS-0027 response-boundary replay + focused tests](observations/OBS-0027-hades-osc52-response-boundaries-2026-08-01.md) | HAD-026 / HAD-027 |
| Remote OSC52 ST termination | Verified (bare SSH_TTY path) | [OBS-0028](observations/OBS-0028-hermes-osc52-st-termination-2026-08-01.md) (valid, empty, malformed direct-PTY controls) | [OBS-0029 ST replay + focused tests](observations/OBS-0029-hades-osc52-st-termination-2026-08-01.md) | HAD-028 / HAD-029 |
| Persistent input history | Verified | [OBS-0016](observations/OBS-0016-hermes-input-history-persistence-2026-08-01.md) | [OBS-0017 history replay + focused tests](observations/OBS-0017-hades-input-history-persistence-2026-08-01.md) | HAD-016 / HAD-017 |
| Submission behavior | Observed | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [submit/interrupt trace](../../tests/fixtures/parity/OBS-0003-submit-interrupt.json) | HAD-001 / HAD-004 |
| Busy/interrupt visual state | Verified | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [visual contract + differential replay](../../tests/fixtures/parity/OBS-0006-busy-interrupt-visual.json) | HAD-007 |
| Streaming behavior | Unknown | — | — | Future task |
| Setup-required error path | Verified | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [setup contract + differential replay](../../tests/fixtures/parity/OBS-0008-setup-required.json) | HAD-009 |
| Errors and retries | Observed | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) (setup-required path only) | [lifecycle trace](../../tests/fixtures/parity/OBS-0001-lifecycle.json) | Future task |
| Resize behavior | Observed | [OBS-0001](observations/OBS-0001-hermes-main-2026-08-01.md) | [lifecycle probe](../../scripts/probe_tui_lifecycle.py) | HAD-003 / Future task |
| Persistence and recovery | Observed (input history only) | [OBS-0016](observations/OBS-0016-hermes-input-history-persistence-2026-08-01.md) | [history replay](observations/OBS-0017-hades-input-history-persistence-2026-08-01.md); session recovery remains unimplemented | HAD-016 / HAD-017 / Future task |

Status vocabulary: `Unknown`, `Observed`, `Specified`, `Implemented`,
`Verified`, and `Blocked`. A row must not jump directly from `Unknown` to
`Verified`.

`Observed` means only that the named path was seen in the pinned reference
run. It does not claim complete coverage of the surface, visual equivalence,
or Hades implementation parity.
