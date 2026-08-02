# Hades standalone tool checklist/provider boundary: OBS-0078

- Subject: bounded Hades standalone Tool Configuration checklist and first-install provider handoff
- Reference: [Hermes OBS-0077](OBS-0077-hermes-tool-provider-boundary-2026-08-02.md)
- Terminal: 120x40 direct PTY
- Task: HAD-083
- Fixture: `tests/fixtures/parity/OBS-0078-hades-tool-provider-boundary.json`
- Replay: `scripts/replay_standalone_tool_provider_boundary.py`

This replay covers the safe route through standalone Full setup, provider skip,
the displayed local backend, platform cancellation, the plain Tool
Configuration handoff, Escape into the raw checklist, one non-mutating `j`, and
one bounded Ctrl+C. It never enters a provider, credential, OAuth, network,
platform, or model value.

## Checklist surface

Escape opens the raw `Tools for 🖥️  CLI` surface with the observed
`SPACE toggle`, `ENTER confirm`, and `ESC cancel` controls. The bounded rows are
Web Search & Scraping, Browser Automation, Terminal & Processes, and File
Operations. The local enable state is typed and in-memory only; no persistence
contract is claimed.

The replay sends `j` and verifies that the process remains alive, no tool is
confirmed, and no provider boundary is crossed during the bounded 100 ms
navigation window. Cursor redraw timing is not used as a parity claim.

## First cancellation boundary

The first Ctrl+C from the checklist leaves the alternate screen, restores
canonical input and echo, keeps the process alive, and prints the observed
first-install continuation:

- `Configuring 6 tool(s):`
- Browser Automation
- Computer Use (macOS/Windows/Linux)
- Image Generation
- Text-to-Speech
- Vision / Image Analysis
- Web Search & Scraping
- `Browser Automation - Choose a provider`

The replay stops at this boundary. Provider inventory and selection, key
prompts, OAuth, network behavior, successful persistence, and later
cancellation remain unknown. Config stays at the non-secret setup baseline and
no `.env` file or new artifact is created.

## Capability boundary

The evidence boundary limits what Hades claims about unobserved Hermes
behavior. It is not a performance or capability ceiling: existing Hades
provider streaming, TUI, launcher, and setup paths remain intact, and the Rust
implementation is free to be faster or richer where that does not falsify this
specific reference contract.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0078-hades-tool-provider-boundary.json)
- [Direct-PTY replay](../../../scripts/replay_standalone_tool_provider_boundary.py)
- [Hermes source observation](OBS-0077-hermes-tool-provider-boundary-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
