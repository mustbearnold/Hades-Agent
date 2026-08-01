# Reference observation: OBS-0016

- Subject: Hermes TUI persistent input history
- Reference: Hermes Agent 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: tmux-backed PTY at 120x40
- Capture: live PTY input with `tmux send-keys`, stable screen text with `tmux capture-pane -p`, and sanitized `.hermes_history` readback
- Runtime: Node 22.22.2, npm 10.9.7, Python 3.11.14, uv 0.12.1
- Task: HAD-016
- Contract fixture: `tests/fixtures/parity/OBS-0016-hermes-input-history-persistence.json`
- Executable oracle: `scripts/validate_reference_fixture.py`

The existing local reference directory had drifted to a newer shallow checkout,
so this observation used a fresh isolated checkout fetched directly at the
documented commit. The exact TUI bundle was built with `npm install
--ignore-scripts --no-audit --no-fund`, `npm run build:ink`, and `npm run build`.
Python dependencies were installed with `uv sync --frozen --no-dev`.

## Capture method

Every TUI process used a fresh synthetic `HERMES_HOME` unless the step
explicitly tested restart behavior. The home contained only a minimal custom
provider configuration targeting `http://127.0.0.1:8765/v1`; no server was
started, so submissions entered the observable busy state and were interrupted
with Ctrl+C. No credential, model response, or private Hermes state was copied.

The runtime command was equivalent to:

```text
HERMES_HOME=<synthetic-home> HERMES_TUI_DIR=<reference-checkout>/ui-tui \
HERMES_TUI_THEME=dark HERMES_TUI_STARTUP_TIMEOUT_MS=8000 \
uv run hermes --tui
```

## Observed contract

| Probe | Input | Observed result |
| --- | --- | --- |
| Seed and submit | Type `hades-history-single-016`, Enter, Ctrl+C | The entry was written to `.hermes_history` as a `+` record after the interrupted turn. |
| Process restart | Exit the first TUI, launch a second TUI with the same `HERMES_HOME`, Up, Down | Up recalled `hades-history-single-016`; Down restored the empty draft. |
| Consecutive duplicate | Submit the same entry again | The history file stayed byte-for-byte unchanged; the newest duplicate was suppressed. |
| Multiline encoding | Bracketed-paste `multi-paste-one\nmulti-paste-two`, Enter, Ctrl+C | The file stored `+multi-paste-one` and `+multi-paste-two` on separate lines, reconstructing one multiline entry. |
| Load cap | Seed 1,001 sanitized entries, launch, press Up once | The newest entry `cap-1001` was recalled and the loaded history count was 1,000. |
| Oldest retained entry | Press Up 999 more times at a controlled 10 ms interval | The composer reached `cap-0002`, proving `cap-0001` was excluded by the load cap. One more Up stayed at `cap-0002`. |

The reference source implements the same contract in its TUI history module:
the history path is `<HERMES_HOME>/.hermes_history`, entries are trimmed before
append, consecutive newest duplicates are ignored, multiline entries are
encoded one logical line per `+` record, and loading keeps the newest 1,000
entries. The PTY probes above verify the restart, duplicate, multiline, and
load-navigation effects against the executable.

## History-file shape

The sanitized multiline record observed on disk was:

```text
# <timestamp>
+multi-paste-one
+multi-paste-two
```

The timestamp is metadata and is intentionally not part of the parity claim.
The leading plus markers and newline reconstruction are part of the claim.

## Explicitly unknown or unavailable

- Write failures, malformed history lines, concurrent writers, and profile
  migration were not exercised.
- Non-consecutive duplicates and explicit history clearing were not exercised.
- The load cap was observed by navigation over a seeded file; physical file
  compaction after appending more than 1,000 entries was not exercised.
- This task records reference behavior only. Hades has not yet claimed disk
  history implementation parity.

## Linked artifacts

- [Sanitized reference fixture](../../../tests/fixtures/parity/OBS-0016-hermes-input-history-persistence.json)
- [Fixture validator](../../../scripts/validate_reference_fixture.py)
- [Input keymap observation](OBS-0010-hermes-input-editing-keymap-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
