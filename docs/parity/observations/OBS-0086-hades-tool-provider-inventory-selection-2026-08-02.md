# Hades safe provider inventory actions: OBS-0086

- Subject: bounded standalone Browser Automation provider actions
- Reference: [Hermes OBS-0085](OBS-0085-hermes-tool-provider-inventory-selection-2026-08-02.md)
- Terminal: 120x40 direct PTY
- Task: HAD-091
- Fixture: `tests/fixtures/parity/OBS-0086-hades-tool-provider-inventory-selection.json`
- Replay: `scripts/replay_standalone_tool_provider_inventory_selection.py`

Hades now gives the observed provider-action boundary an explicit safe state
transition. Four fresh processes reach the provider inventory and exercise
Enter and Space on Local Browser, six Down inputs followed by Enter on Skip,
and Escape. No credentials, OAuth action, network-bearing input, provider
adapter, installer, or persistence action is used.

## Verified safe action contract

Each action leaves the raw provider surface, restores canonical input and echo,
and keeps the setup process alive for bounded readback. Hades emits an explicit
status for the selected Local Browser, skipped Browser Automation, or cancelled
provider action. A single Ctrl+C then exits with status 130 and leaves terminal
input restored.

The normalized setup config and artifact inventory are unchanged in every case.
The replay also checks that Hermes' observed `curl`/installer markers do not
appear. Paid and other provider-specific Enter/Space actions remain outside the
slice and are intentionally not guessed.

Hades deliberately fixes the Hermes implicit background installation/network
side effect rather than rebuilding it. This is a safety deviation, not a
performance cap or a reason to remove future explicit provider capabilities.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0086-hades-tool-provider-inventory-selection.json)
- [Direct-PTY replay](../../../scripts/replay_standalone_tool_provider_inventory_selection.py)
- [Hermes reference observation](OBS-0085-hermes-tool-provider-inventory-selection-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
