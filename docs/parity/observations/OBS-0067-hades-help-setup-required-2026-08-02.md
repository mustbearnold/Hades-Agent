# Hades implementation observation: OBS-0067

- Subject: delayed unconfigured `/help` to Setup Required transition
- Reference contract: [OBS-0066](OBS-0066-hermes-help-setup-timing-2026-08-02.md)
- Task: HAD-072
- Fixture: `tests/fixtures/parity/OBS-0067-hades-help-setup-required.json`
- Replay: `scripts/replay_unconfigured_help.py`

Hades now reproduces the observed distinction between an unconfigured startup
draft and the delayed `/help` setup route. In fresh 120x40 direct PTYs without a
provider endpoint, `/help` remains visible on the `starting agent` surface for
the bounded 8000 ms deadline. It then opens the existing Setup Required overlay
with `/model`, `/setup`, and Ctrl+C actions. The two debug replay samples
transitioned at 8125 ms and 8129 ms after submission.

The route is a typed `InputEvent::Tick` plus injected `Instant` deadline in the
application reducer. Focused tests advance the clock without sleeping. The
first Ctrl+C clears the retained draft while leaving the overlay active, and
the second exits cleanly; the direct PTY proves process liveness, exit status,
alternate-screen cleanup, and terminal restoration. No provider worker, user or
assistant message, config file, credential, or network request is created.

Both the default launch and explicit `tui` launch were replayed. The user-local
release launcher was refreshed with `just install-user` and the same replay was
run against both `hades` and `Hades` after the full no-skip verification gate.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0067-hades-help-setup-required.json)
- [Direct-PTY replay](../../../scripts/replay_unconfigured_help.py)
- [Focused app/TUI tests](../../../crates/hades-app/src/lib.rs)
- [Hermes timing observation](OBS-0066-hermes-help-setup-timing-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
