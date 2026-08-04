# Hermes provider inventory cursor edges: OBS-0083

- Subject: bounded first-install Browser Automation provider arrow navigation
- Prior interaction: [OBS-0081](OBS-0081-hermes-tool-provider-inventory-interaction-2026-08-02.md)
- Terminal: 120x40 direct PTY
- Task: HAD-088
- Fixture: `tests/fixtures/parity/OBS-0083-hermes-tool-provider-inventory-edges.json`
- Probe: `scripts/probe_hermes_tool_provider_inventory_edges.py`

This observation repeats the safe Hermes route in three fresh processes and
sends only arrow-key bytes at the provider inventory. Every input is observed
for 350 ms before the next input. No provider choice, secret, OAuth action,
network-bearing input, or persistence action is sent.

## Observed cyclic cursor behavior

The initial cursor and selected row are Local Browser. Up at that first row
wraps to `Skip — keep defaults / configure later`; Local Browser remains the
selected row.

Eight Down inputs advance one row at a time through the observed options:

`Nous Subscription → Camofox → Browser Use → Browserbase → Firecrawl → Skip → Local Browser → Nous Subscription`.

The lower edge therefore wraps to the first row rather than clamping. A fresh
Down then Up case returns the cursor to Local Browser. The selected row remains
Local Browser in all three cases.

## Runtime and persistence evidence

All cases remain alive in raw mode with canonical input and echo disabled. The
route enters and leaves the alternate screen before interaction. Config shape
and artifact inventory remain unchanged after each arrow case, and no `.env`
file appears. Forced teardown of the live cases is harness cleanup only.

Provider submission, Enter/Space, Escape, Ctrl+C, credentials, OAuth, network
behavior, persistence after selection, discovery completeness, and later setup
remain unknown. The cyclic result is recorded as reference behavior; Hermes
bugs, unsafe behavior, and failure cases are not requirements for Hades, and
this observation does not cap Hades performance or capabilities.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0083-hermes-tool-provider-inventory-edges.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_tool_provider_inventory_edges.py)
- [Prior Hermes interaction](OBS-0081-hermes-tool-provider-inventory-interaction-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
