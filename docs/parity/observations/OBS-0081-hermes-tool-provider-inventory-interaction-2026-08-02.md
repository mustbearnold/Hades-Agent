# Hermes provider inventory interaction: OBS-0081

- Subject: bounded first-install Browser Automation provider navigation and cancellation
- Reference inventory: [OBS-0079](OBS-0079-hermes-tool-provider-inventory-2026-08-02.md)
- Terminal: 120x40 direct PTY
- Task: HAD-086
- Fixture: `tests/fixtures/parity/OBS-0081-hermes-tool-provider-inventory-interaction.json`
- Probe: `scripts/probe_hermes_tool_provider_inventory_interaction.py`

This observation repeats the safe first-install route into the Browser
Automation provider inventory in three fresh Hermes processes. Each case sends
one bounded input only, then reads the result for 750 ms. No provider, key,
OAuth action, network-bearing input, or persistence action is sent.

## Observed interaction boundary

At the provider surface Hermes is in raw mode with canonical input and echo
disabled. The initial selected row is Local Browser. A Down sequence
(`1b 5b 42`) moves the cursor to Nous Subscription while Local Browser remains
selected, and the child stays alive. This is a non-submitting navigation
observation; it does not establish Enter/Space submission semantics.

Escape (`1b`) produces no visible delta during the 750 ms window and leaves the
child alive in raw mode. Delayed cancellation behavior remains unknown.

Ctrl+C (`03`) leaves the child alive during the bounded window but produces a
second `Choose a provider:` surface with a Nous Subscription/FAL image
generation row and Skip. The cross-tool redraw is recorded as an ambiguous
Hermes transition, not as a Hades contract. It may require separate reference
investigation; Hades must not blindly reproduce an unsafe or defective failure
case.

## Runtime and persistence evidence

All three fresh cases enter and leave the alternate screen before the
interaction boundary, keep the config unchanged, create no new artifact after
Tool Configuration, and create no `.env` file. Forced process-group teardown
of still-live cases is harness cleanup only and is not a Hermes cancellation or
exit result.

## Hades implementation boundary

This reference task does not authorize copying Hermes’ ambiguous Ctrl+C
transition. Hermes observations define compatibility intent, while defects,
unsafe behavior, and failure cases are things to fix. The evidence boundary
also does not cap Hades’ Rust performance or safer capabilities.

Provider submission, credentials, OAuth, network behavior, persistence,
discovery completeness, and behavior after the bounded window remain unknown.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0081-hermes-tool-provider-inventory-interaction.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_tool_provider_inventory_interaction.py)
- [Prior Hermes inventory](OBS-0079-hermes-tool-provider-inventory-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
