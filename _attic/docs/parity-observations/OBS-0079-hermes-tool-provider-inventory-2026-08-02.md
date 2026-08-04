# Hermes Browser Automation provider inventory: OBS-0079

- Subject: standalone Hermes first-install provider inventory after the
  Browser Automation handoff
- Reference: pinned Hermes checkout at commit `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: 120x40 direct PTY
- Task: HAD-084
- Fixture: `tests/fixtures/parity/OBS-0079-hermes-tool-provider-inventory.json`
- Probe: `scripts/probe_hermes_tool_provider_inventory.py`

This probe repeats the safe route through Full setup, provider skip, the
displayed local terminal backend, platform cancellation, the raw `Tools for
CLI` checklist, and the first-install Browser Automation provider boundary.
It sends no provider choice, credential, OAuth action, or network-bearing
input. It then reads the provider surface for one second and stops with
harness-only forced child teardown.

## Observed provider surface

Hermes exposes the provider selection controls `Choose a provider:`,
`↑↓ navigate`, `ENTER/SPACE select`, and `ESC cancel`. The visible options in
the bounded read window are:

- `Local Browser [★ recommended · free]` — Headless Chromium, no API key needed
- `Nous Subscription (Browser Use cloud) [subscription]`
- `Camofox [free · local]` — Anti-detection browser (Firefox/Camoufox)
- `Browser Use [paid]` — Cloud browser with remote execution
- `Browserbase [paid]` — Cloud browser with stealth and proxies
- `Firecrawl [paid]` — Cloud browser with remote execution
- `Skip — keep defaults / configure later`

The selected row at first render is Local Browser. The provider inventory
arrives through a redraw during the one-second window, and the screen-model
snapshot changes while it arrives. The option labels are therefore recorded as
observed during a bounded redraw, not as a claim of stable frame identity or
complete provider discovery semantics. The longer description for the Nous
Subscription row is clipped at the 120-column terminal boundary.

At the provider surface, canonical input and echo are restored and the child
remains alive. The normalized 2003-byte config shape is unchanged from the
Tool Configuration boundary, no `.env` file is created, and no new artifact
class appears during the read-only window. The probe's forced process-group
teardown is harness cleanup only; it is not a Hermes cancellation or exit
result.

## Explicit unknowns

Provider selection semantics, key prompts, OAuth, network behavior, persistence
after selecting a provider, and later cancellation remain unobserved. The
inventory list is not treated as a complete provider-discovery contract, and
the redraw timing is not promoted into a universal timing guarantee.

The evidence boundary is not a performance ceiling for Hades. Rust may make
Hades faster or more capable wherever that does not falsify the observed
Hermes contract; this observation does not justify disabling or slowing any
existing Hades behavior.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0079-hermes-tool-provider-inventory.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_tool_provider_inventory.py)
- [Prior provider boundary](OBS-0077-hermes-tool-provider-boundary-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
