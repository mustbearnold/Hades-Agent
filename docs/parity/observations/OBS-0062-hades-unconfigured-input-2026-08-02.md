# Hades implementation observation: OBS-0062

- Subject: bounded input during unconfigured startup
- Reference contract: [OBS-0061](OBS-0061-hermes-unconfigured-input-queue-2026-08-02.md)
- Task: HAD-066
- Fixture: `tests/fixtures/parity/OBS-0062-hades-unconfigured-input.json`
- Replay: `scripts/replay_unconfigured_input.py`

Hades now follows the captured Hermes input boundary without pretending that a
provider is available. With no provider endpoint, printable input and Enter
remain in the typed unconfigured startup state, render as `❯ queued hello`, do
not add a user message, and do not start a provider request. The starting-agent
footer remains visible and no ready footer or provider error is rendered.

The first Ctrl+C clears the non-empty draft and leaves startup active; a second
Ctrl+C exits with status zero. An empty unconfigured startup still exits with a
single Ctrl+C. The direct PTY replay covers both `hades` and `hades tui` launch
forms, raw mode, alternate-screen cleanup, and terminal restoration. Focused
app/TUI tests provide the exact draft-clear oracle where a PTY diff stream is
not a reliable full-screen snapshot.

Provider setup, persistence, credentials, OAuth, eventual startup resolution,
and actual delivery of a visible draft remain future work.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0062-hades-unconfigured-input.json)
- [Direct-PTY replay](../../../scripts/replay_unconfigured_input.py)
- [Hermes reference observation](OBS-0061-hermes-unconfigured-input-queue-2026-08-02.md)
- [Focused app/TUI tests](../../../crates/hades-app/src/lib.rs)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
