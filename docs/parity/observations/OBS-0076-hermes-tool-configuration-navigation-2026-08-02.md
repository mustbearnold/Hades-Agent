# Hermes Tool Configuration navigation boundary: OBS-0076

- Subject: standalone Hermes Tool Configuration checklist navigation and the
  first-install cancellation handoff
- Reference: pinned Hermes checkout at commit `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Terminal: 120x40 direct PTY
- Task: HAD-081
- Fixture: `tests/fixtures/parity/OBS-0076-hermes-tool-configuration-navigation.json`
- Probe: `scripts/probe_hermes_tool_configuration_navigation.py`

This probe repeats the safe OBS-0075 route through Full setup, provider skip,
the displayed local terminal backend, platform cancellation, and the plain
Tool Configuration handoff. Escape opens the raw `Tools for 🖥️  CLI` checklist.
The probe then sends one `j` navigation key and one Ctrl+C. It never toggles or
confirms a tool and never enters a provider, credential, OAuth, or platform
value.

## Checklist surface

The stable checklist title is `Tools for 🖥️  CLI`. Its controls are `SPACE
toggle`, `ENTER confirm`, and `ESC cancel`. The bounded visible rows are:

- Web Search & Scraping
- Browser Automation
- Terminal & Processes
- File Operations

The first visible cursor styling is on Web Search & Scraping (bold green in the
screen model). The screen model did not show a changed snapshot within 100 ms
after `j`, so the post-key cursor position and delayed redraw behavior remain
unknown. This is an observation boundary, not an inference that `j` is ignored.

## First cancellation boundary

The first Ctrl+C leaves the raw checklist, restores canonical input and echo,
and keeps the process alive. The next stable plain-text output is the
first-install continuation:

- `Configuring 6 tool(s):`
- Browser Automation
- Computer Use (macOS/Windows/Linux)
- Image Generation
- Text-to-Speech
- Vision / Image Analysis
- Web Search & Scraping
- `Browser Automation - Choose a provider`

This is the first newly opened provider boundary. The probe stops before any
provider choice or key prompt and uses forced child/process-group teardown
only as harness cleanup; later Hermes cancellation status is unknown. The
normalized config remains unchanged at 2003 bytes, no `.env` file is created,
and terminal flags at the boundary are canonical/echo true.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0076-hermes-tool-configuration-navigation.json)
- [Direct-PTY probe](../../../scripts/probe_hermes_tool_configuration_navigation.py)
- [Prior Tool Configuration boundary](OBS-0075-hermes-standalone-tool-configuration-2026-08-02.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
