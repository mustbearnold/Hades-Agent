# Reference observation: OBS-0018

- Subject: Hermes TUI editor handoff outcomes
- Reference: Hermes Agent 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: tmux-backed PTY at 120x40
- Capture: live tmux input with stable screen capture and sanitized history-file readback
- Runtime: Node 22.22.2, npm 10.9.7, Python 3.11.14, uv 0.12.1
- Task: HAD-018
- Contract fixture: `tests/fixtures/parity/OBS-0018-hermes-editor-outcomes.json`
- Oracle: `scripts/validate_reference_fixture.py`

The reference was the pinned Hermes checkout used by OBS-0010 and OBS-0016.
Each case used a fresh synthetic `HERMES_HOME`, the loopback custom provider,
and no listening model endpoint. The editor was a deterministic command so the
probe could isolate the TUI's post-editor decision without depending on an
interactive editor UI.

## Capture method

The runtime command was equivalent to:

```text
HERMES_HOME=<fresh synthetic home> HERMES_TUI_DIR=<pinned checkout>/ui-tui \
HERMES_TUI_THEME=dark HERMES_TUI_STARTUP_TIMEOUT_MS=8000 \
EDITOR=<deterministic editor command> uv run hermes --tui
```

For successful cases, the editor rewrote the temporary file and exited 0. The
probe also tested an empty file with `truncate -s 0` and cancellation with an
editor that exited 1. After the successful whitespace case, the generated
`.hermes_history` file was read back to distinguish trailing-newline trimming
from broader whitespace trimming.

## Observed contract

| Case | Editor result | Post-handoff state | Composer/submission behavior |
| --- | --- | --- | --- |
| Modified clean exit | `edited-one\\nedited-two\\n`, exit 0 | Busy; `Ctrl+C to interrupt…` visible | Original composer is cleared; `edited-one\\nedited-two` is submitted. |
| Multiline clean exit | `multi-one\\nmulti-two\\n`, exit 0 | Busy; `Ctrl+C to interrupt…` visible | Internal newline is preserved and the final newline is removed before submission. |
| Trailing-newline trim | `edge-one  \\nedge-two\\n`, exit 0 | Busy | The final newline is removed, but the two spaces before the internal newline remain; history stores `+edge-one  ` and `+edge-two`. |
| Empty clean exit | empty file, exit 0 | Ready | The original `empty-probe` draft remains and nothing is submitted. |
| Nonzero cancellation | exit 1 | Ready | The original `cancel-probe` draft remains and nothing is submitted. |

The source-level behavior and the executable capture agree on `trimEnd()`:
successful non-empty editor output is submitted after trailing line endings are
removed; an empty post-trim result is ignored without clearing the composer;
and a nonzero editor exit is treated as cancellation.

## Explicitly unknown or unavailable

- Interactive editor save/cancel prompts and unsaved-change behavior were not
  exercised.
- Unavailable-editor fallback selection, launch failures, and unreadable
  temporary files remain unknown.
- This observation does not cover editor handoff while busy, with attachments,
  queue editing, overlays, or an empty initial composer.

These gaps are preserved in the fixture's `environment_sensitive` and
`unknowns` sections. They must not be treated as implementation requirements
until another reference capture makes them observable.

## Linked artifacts

- [Sanitized reference fixture](../../../tests/fixtures/parity/OBS-0018-hermes-editor-outcomes.json)
- [Fixture validator](../../../scripts/validate_reference_fixture.py)
- [Input editing observation](OBS-0010-hermes-input-editing-keymap-2026-08-01.md)
- [Unchanged-draft Hades contract](../../../tests/fixtures/parity/OBS-0014-hades-editor-handoff.json)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
