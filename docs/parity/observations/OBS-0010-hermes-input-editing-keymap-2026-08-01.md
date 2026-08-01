# Reference observation: OBS-0010

- Subject: Hermes TUI input editing and keymap surface
- Reference: Hermes Agent 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: tmux-backed PTY at 120x40
- Capture: live PTY input with `tmux send-keys`; stable screen text with `tmux capture-pane -p`
- Runtime: Node 22.22.2, npm 10.9.7, Python 3.11.14, uv 0.12.1
- Task: HAD-010
- Contract fixture: `tests/fixtures/parity/OBS-0010-input-editing-keymap.json`
- Executable oracle: `scripts/validate_reference_fixture.py`

The reference checkout was the same official Hermes source and pinned commit used
by OBS-0001. Each probe used a fresh synthetic `HERMES_HOME` with a dummy
loopback custom provider and no listening model endpoint. The TUI therefore
reached its ready state without a real provider, while submit probes stopped in
the observable busy state. No credentials, model payloads, or private Hermes
state were copied into the fixture.

## Capture method

The runtime command was equivalent to:

```text
HERMES_HOME=<fresh synthetic home> HERMES_TUI_DIR=<pinned checkout>/ui-tui HERMES_TUI_THEME=dark HERMES_TUI_STARTUP_TIMEOUT_MS=8000 uv run hermes --tui
```

For the editor probe only, `EDITOR=/bin/true` was added. The input byte stream
for each probe is recorded in hexadecimal in the fixture after tmux key
translation. A completion wait represents the documented debounce plus the
local completion response. Screen captures were read after the corresponding
stable redraw and were reduced to composer, status, completion, and message
landmarks.

## Observed contract

| Probe | Input | Observed result |
| --- | --- | --- |
| History seed | Type `alpha`, Enter, Ctrl+C | The turn entered busy, Ctrl+C produced `interrupted`, and the ready composer was empty. |
| History recall | Up, then Down | Up recalled `alpha`; Down returned to the empty draft after the newest entry. |
| Cursor insertion | Type `abc`, Left, type `X` | Composer became `abXc`. |
| Deletion | Backspace after the inserted `X` | Composer returned to `abc`. |
| Line movement | Home + `z`, End + `!` | Composer became `zabc!`. |
| Kill-to-end | Ctrl+A, Ctrl+K | Composer was cleared and the rotating placeholder returned. |
| Multiline fallback | Type `line-one`, `\`, Enter, type `line-two` | Composer displayed two lines, `line-one` and `line-two`; the draft was not submitted. |
| Slash completion | Type `/he`, wait for completion | A completion panel showed `/help`, `/hermes-agent`, and `/hermes-agent-skill-authoring`. |
| Apply completion | Tab | The composer became `/help` and the panel collapsed to the applied item. |
| Editor handoff | With `EDITOR=/bin/true`, type `editor-probe`, Ctrl+G | The editor returned cleanly and the unchanged draft was submitted, entering busy state with the interrupt affordance. The rotating face text is not asserted. |
| Bracketed paste | Paste `paste-one\npaste-two` with `ESC[200~`/`ESC[201~` markers | The newline was preserved inline; the paste did not submit the draft. |
| Clipboard fallback | Ctrl+V with no readable clipboard | The TUI reported `No image found in clipboard` and left the composer unchanged. |

The fixture preserves the exact bytes and normalized outputs for these steps.
The stable claims are intentionally narrower than Hermes's source-level keymap
documentation: they describe what this pinned executable exposed through this
terminal harness.

## Explicitly unknown or unavailable

- Native Shift+Enter and Alt+Enter could not be isolated through `tmux
  send-keys`; the probe emitted ordinary Enter and submitted the draft.
- Mouse injection was not stable through this capture method, so selection,
  scrolling, and click behavior remain unknown.
- Only the empty-clipboard miss path was available. Successful text/image/path
  paste was not observed.
- History persistence across process restart, duplicate suppression, truncation,
  and multiline history encoding remain unknown beyond the one recalled entry.
- Modified word movement, queue-edit precedence, editor cancellation or edited
  content, and completion behavior in multiline/busy contexts remain unknown.

These gaps are preserved in the fixture's `environment_sensitive` and `unknowns`
sections. They must not be treated as implementation requirements until another
reference capture makes them observable.

## Linked artifacts

- [Sanitized reference fixture](../../../tests/fixtures/parity/OBS-0010-input-editing-keymap.json)
- [Fixture validator](../../../scripts/validate_reference_fixture.py)
- [Initial reference observation](OBS-0001-hermes-main-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
