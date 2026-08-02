# Hermes first-install tool-provider boundary: OBS-0077

- Subject: standalone Hermes first-install tool configuration and Browser
  Automation provider handoff
- Reference: pinned Hermes checkout at commit `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: 120x40 direct PTY
- Task: HAD-082
- Fixture: `tests/fixtures/parity/OBS-0077-hermes-tool-provider-boundary.json`
- Probe: `scripts/probe_hermes_tool_provider_boundary.py`

This probe repeats the safe route through Full setup, provider skip, the
displayed local terminal backend, platform cancellation, and the raw
`Tools for 🖥️  CLI` checklist. It sends one Ctrl+C from that checklist and
captures only the first-install continuation. No tool, provider, credential,
OAuth, platform, or model value is entered.

## First-install provider boundary

Within a 200 ms direct-PTY window, Hermes renders:

- `Configuring 6 tool(s):`
- Browser Automation
- Computer Use (macOS/Windows/Linux)
- Image Generation
- Text-to-Speech
- Vision / Image Analysis
- Web Search & Scraping
- `Browser Automation - Choose a provider`

The first Ctrl+C restores canonical input and echo while the process remains
alive. The provider choice list itself, provider discovery behavior, key
prompts, and later cancellation were not entered or inferred.

The normalized 2003-byte config remains unchanged at this boundary. No `.env`
file or new artifact class is created. The probe uses forced
child/process-group teardown after the evidence window; that is harness
cleanup, not a Hermes product exit or terminal-restoration claim.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0077-hermes-tool-provider-boundary.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_tool_provider_boundary.py)
- [Prior navigation boundary](OBS-0076-hermes-tool-configuration-navigation-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
