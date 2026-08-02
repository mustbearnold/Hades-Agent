# Hades Browser Automation provider inventory: OBS-0080

- Subject: bounded Hades standalone first-install Browser Automation provider inventory
- Reference contract: [Hermes OBS-0079](OBS-0079-hermes-tool-provider-inventory-2026-08-02.md)
- Terminal: 120x40 direct PTY
- Task: HAD-085
- Fixture: `tests/fixtures/parity/OBS-0080-hades-tool-provider-inventory.json`
- Replay: `scripts/replay_standalone_tool_provider_inventory.py`

Hades now carries the observed standalone setup route through the Browser
Automation provider inventory. The replay uses a fresh synthetic home, sends
only the bounded setup-route keys, and stops after reading the rendered
provider surface. It does not submit a provider, credential, OAuth action, or
network-bearing input.

## Verified provider surface

The raw interactive boundary renders `Choose a provider:`, the
`↑↓ navigate`, `ENTER/SPACE select`, and `ESC cancel` controls, and the seven
observed options:

- `Local Browser [★ recommended · free]` — Headless Chromium, no API key needed
- `Nous Subscription (Browser Use cloud) [subscription]` — Managed Browser Use billed to your subscription
- `Camofox [free · local]` — Anti-detection browser (Firefox/Camoufox)
- `Browser Use [paid]` — Cloud browser with remote execution
- `Browserbase [paid]` — Cloud browser with stealth and proxies
- `Firecrawl [paid]` — Cloud browser with remote execution
- `Skip — keep defaults / configure later`

Local Browser is rendered as the selected recommended row. Hades now keeps the
provider surface in raw mode so safe arrow navigation can be handled without
line buffering; the display-only replay still sends no provider input. Provider
selection, Enter/Space/Escape behavior, discovery timing, and later cancellation
remain unknown until directly observed.

## Runtime and persistence evidence

The direct-PTY replay confirms that the provider inventory process remains
alive, canonical input and echo are restored, the non-secret setup config is
unchanged after the Tool Configuration boundary, and no new artifact or
`.env` secrets file appears during the read-only window. Forced child teardown
is harness cleanup only and is not a Hades product exit or cancellation claim.

Hermes observations define compatibility intent, not defects to preserve. This
implementation does not intentionally reproduce Hermes bugs or failure cases,
and the evidence boundary is not a performance or capability ceiling for
Rust-based Hades.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0080-hades-tool-provider-inventory.json)
- [Direct-PTY replay](../../../scripts/replay_standalone_tool_provider_inventory.py)
- [Hermes source observation](OBS-0079-hermes-tool-provider-inventory-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
