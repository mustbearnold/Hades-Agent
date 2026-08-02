# Hades provider inventory navigation: OBS-0082

- Subject: bounded standalone Browser Automation provider Down navigation
- Reference interaction: [Hermes OBS-0081](OBS-0081-hermes-tool-provider-inventory-interaction-2026-08-02.md)
- Terminal: 120x40 direct PTY
- Task: HAD-087
- Fixture: `tests/fixtures/parity/OBS-0082-hades-tool-provider-inventory-navigation.json`
- Replay: `scripts/replay_standalone_tool_provider_inventory_navigation.py`

Hades now exposes the observed safe navigation seam at the standalone Browser
Automation provider inventory. The replay repeats the established setup route,
enters the provider surface, and sends exactly one Down sequence
(`1b 5b 42`). It does not submit a provider or enter a secret-bearing value.

## Verified interaction

The provider inventory runs in raw mode with canonical input and echo disabled.
The initial cursor and selected row are Local Browser. Down moves the cursor to
Nous Subscription while Local Browser remains selected. The process stays alive
after the input, and the rendered markers are:

- `→ (○) Nous Subscription (Browser Use cloud)`
- `(●) Local Browser`

The route enters and leaves the alternate screen before the provider
interaction, matching the observed lifecycle boundary. Hades uses typed state
for the cursor and redraws the current surface through the TUI renderer; it does
not implement provider submission in this slice.

## Runtime and persistence evidence

The direct-PTY replay confirms raw terminal flags before and after navigation,
process liveness, an unchanged non-secret setup config, and no new artifact or
`.env` file after Down. Forced child teardown is harness cleanup only and is
not a Hades product exit or cancellation result.

Enter/Space, Escape, Ctrl+C provider semantics, credentials, OAuth, networking,
persistence after a provider action, discovery completeness, and later setup
remain unknown. The ambiguous Hermes Ctrl+C transition into a second
FAL/image-generation surface is deliberately not reproduced. Hermes defects,
unsafe behavior, and failure cases are not compatibility requirements, and this
bounded implementation does not cap Hades performance or safer capabilities.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0082-hades-tool-provider-inventory-navigation.json)
- [Direct-PTY replay](../../../scripts/replay_standalone_tool_provider_inventory_navigation.py)
- [Hades provider inventory display](OBS-0080-hades-tool-provider-inventory-2026-08-02.md)
- [Hermes interaction observation](OBS-0081-hermes-tool-provider-inventory-interaction-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
