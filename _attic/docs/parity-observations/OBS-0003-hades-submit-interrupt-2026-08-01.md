# Core replay observation: OBS-0003

- Subject: Hades submit, busy, and interrupt transition
- Reference contract: OBS-0001 steps type-text, submit-unavailable-local-endpoint, and interrupt-active-turn
- Implementation seam: hades-app reducer, independent of terminal rendering
- Replay fixture: tests/fixtures/parity/OBS-0003-submit-interrupt.json
- Focused oracle: hades-app unit test ctrl_c_interrupts_busy_turn_before_quitting

## Contract

The first reference-backed transition is intentionally small:

| State | Input | Deterministic result |
| --- | --- | --- |
| Ready | Type hello | The composer contains hello and the session remains ready. |
| Ready | Press Enter | The user message is recorded, the composer is cleared, the dispatch outcome is Submitted(hello), and the turn becomes busy. |
| Busy | Press Ctrl+C | The turn becomes ready, the dispatch outcome is Interrupted, the session remains alive, and status becomes Interrupted. |
| Ready after interruption | Press Ctrl+C | The dispatch outcome is Quit and the session requests exit. |

The busy phase is typed as TurnState::Busy in hades-core. The reducer does not
perform terminal I/O, model calls, timing, or rendering; those boundaries remain
outside the deterministic transition.

The current response adapter is intentionally absent. Busy therefore records
the observable adapter boundary as status text without inventing an assistant
response. This is enough to prove the reference-backed cancellation transition,
not streaming or provider parity.

## Verification

The focused hades-app test replays the exact hello -> Enter -> Ctrl+C -> Ctrl+C
sequence. The PTY lifecycle probe also exercises the transition through the real
CLI: its interrupt-exit case now requires the first Ctrl+C to return to ready
and the second Ctrl+C to exit cleanly.

## Unknowns

- Actual model response streaming and completion.
- Busy-state timing, face text, tool calls, and cancellation payloads.
- Whether editing, resize, or other commands are accepted while busy.
- Full parity of Ctrl+C behavior across setup, overlays, and other Hermes modes.
