# Hermes provider inventory selection and cancellation: OBS-0085

- Subject: bounded first-install Browser Automation provider actions
- Prior interaction: [OBS-0083](OBS-0083-hermes-tool-provider-inventory-edges-2026-08-02.md)
- Terminal: 120x40 direct PTY
- Task: HAD-090
- Fixture: `tests/fixtures/parity/OBS-0085-hermes-tool-provider-inventory-selection.json`
- Probe: `scripts/probe_hermes_tool_provider_inventory_selection.py`

This observation repeats the established standalone Full setup route in four
fresh synthetic homes. After a one-second no-input window at the provider
inventory, it sends only Enter on the default Local Browser row, Space on the
same row, six Down inputs followed by Enter on Skip, or Escape. No credentials,
OAuth action, or later setup value is entered.

## Observed bounded actions

Enter and Space both leave the provider list, report that Local Browser is in
local mode and needs no configuration, and restore canonical input and echo.
The Skip case walks through the six observed rows while Local Browser remains
selected, then leaves the list with `Skipped Browser Automation`. Escape leaves
the provider list with no stable transition marker in the bounded delta. All
four cases keep the Hermes process alive and leave the alternate screen.

Every first action also exposes a background Computer Use installer. The direct
PTY process tree shows new `bash` and `curl` descendants, and the synthetic home
receives `.cua-driver/packages/.install.lock.d/info`; the normalized config
shape remains unchanged. This work was visible without sending a
network-bearing input and is not a safe Hades compatibility requirement.

Hades must not start implicit network or installation work from a provider
selection/cancellation surface. Hermes defects, unsafe behavior, and failure
cases are findings to fix rather than behavior to reproduce. The observation
does not cap Hades performance or safer capabilities.

## Boundaries and unknowns

The observation does not claim the full installer lifecycle, provider
discovery, credentials, OAuth, durable persistence, or later setup behavior.
The probe stops at the bounded window and force-tears down only its own live
process group; that cleanup is not a Hermes product outcome.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0085-hermes-tool-provider-inventory-selection.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_tool_provider_inventory_selection.py)
- [Prior Hermes edge observation](OBS-0083-hermes-tool-provider-inventory-edges-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
