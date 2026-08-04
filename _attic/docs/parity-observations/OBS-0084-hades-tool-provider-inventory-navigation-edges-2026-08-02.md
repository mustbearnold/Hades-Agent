# Hades provider inventory cursor edges: OBS-0084

- Subject: bounded standalone Browser Automation provider arrow navigation
- Reference interaction: [Hermes OBS-0083](OBS-0083-hermes-tool-provider-inventory-edges-2026-08-02.md)
- Terminal: 120x40 direct PTY
- Task: HAD-089
- Fixture: `tests/fixtures/parity/OBS-0084-hades-tool-provider-inventory-navigation-edges.json`
- Replay: `scripts/replay_standalone_tool_provider_inventory_navigation.py`

Hades now implements the observed cyclic provider cursor seam. Each replay case
starts a fresh standalone setup process, reaches the provider inventory through
the established bounded route, and sends only arrow bytes after the provider
surface is visible. No provider is submitted and no credential-bearing action
is attempted.

## Verified edge contract

The provider inventory starts with the cursor and selected row on Local Browser.
An Up sequence (`1b 5b 41`) wraps the cursor to Skip while Local Browser remains
selected. Seven Down sequences (`1b 5b 42`) walk through Nous Subscription,
Camofox, Browser Use, Browserbase, Firecrawl, Skip, and back to Local Browser.
A fresh Down followed by Up returns from Nous Subscription to Local Browser.

Cursor movement is typed state separate from provider selection. The renderer
shows the wrapped cursor markers:

- `→ (○) Skip — keep defaults / configure later`
- `→ (●) Local Browser`
- `(●) Local Browser`

## Runtime and persistence evidence

The direct-PTY replay covers all three fresh cases and records exact input
bytes, each expected cursor target, the accumulated unchanged selected-row
marker, raw terminal flags before and after navigation, process liveness,
alternate-screen lifecycle, and normalized config/artifact invariants. Every
case remains raw (`canonical=false`, `echo=false`), alive, config-stable, and
artifact-stable after navigation.

Enter/Space, Escape, Ctrl+C provider semantics, credentials, OAuth, networking,
persistence after a provider action, discovery completeness, and later setup
remain unknown. The ambiguous Hermes Ctrl+C cross-tool redraw is deliberately
not reproduced. Hermes defects, unsafe behavior, and failure cases are not
compatibility requirements, and this implementation does not cap Hades
performance or safer capabilities.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0084-hades-tool-provider-inventory-navigation-edges.json)
- [Direct-PTY replay](../../../scripts/replay_standalone_tool_provider_inventory_navigation.py)
- [Hermes edge observation](OBS-0083-hermes-tool-provider-inventory-edges-2026-08-02.md)
- [Hades provider inventory display](OBS-0080-hades-tool-provider-inventory-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
