# Hades empty-platform confirmation: OBS-0087

- Subject: standalone `hades setup` empty-platform confirmation
- Reference contract: [OBS-0058](OBS-0058-hermes-empty-platform-confirmation-2026-08-02.md)
- Binary: current Hades debug CLI under direct PTY
- Terminal: 120x40
- Task: HAD-092
- Fixture: `tests/fixtures/parity/OBS-0087-hades-empty-platform-confirmation.json`
- Replay: `scripts/replay_standalone_empty_platform_confirmation.py`

Hades now gives the observed empty-platform boundary an explicit typed action.
Enter on the platform picker with every platform unselected is a safe no-op:
the same unconfigured platform rows remain visible, the process stays alive in
raw mode, the alternate screen remains active, and no provider or persistence
work starts. Space and all platform-selection behavior remain unknown and are
not inferred from this capture.

The existing cancellation boundary remains intact. Ctrl+C leaves the picker for
the plain Tool Configuration surface with canonical input and echo restored;
the second Ctrl+C exits with status 130. The isolated config remains unchanged,
no secrets file is created, and the replay observes no provider error or
provider-environment activity.

This is a bounded safe implementation of the OBS-0058 no-op. It does not claim
that Hermes or Hades can complete a zero-platform setup beyond the observed
window, and it does not reproduce unrelated Hermes defects or failure cases.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0087-hades-empty-platform-confirmation.json)
- [Direct-PTY replay](../../../scripts/replay_standalone_empty_platform_confirmation.py)
- [Hermes reference observation](OBS-0058-hermes-empty-platform-confirmation-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
