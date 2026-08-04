# Hades implementation observation: OBS-0090

- Subject: configured composer, slash completion, overlays, history, and clipboard
- Hades source: workspace implementation under test
- Terminal: fresh 120x40 direct PTY processes
- Capture: local setup sidecar, deterministic loopback HTTP/SSE server, and synthetic xclip
- Task: HAD-095
- Replay: scripts/replay_configured_surfaces.py

OBS-0090 closes the first vertical-slice usability gap after HAD-094. It does
not add a second collection of isolated unit claims; it walks the configured
Hades process through the surfaces a person needs immediately after launch.

## Verified behavior

The replay first runs the explicit Hades local setup command, then launches a
fresh process without provider environment overrides. `/he` renders the
completion surface and Tab applies the first completion without submitting a
request. `/model` opens the two-stage model picker and Ctrl+X opens the sessions
overlay; both close through Escape without opening the local provider.

Two prompts are streamed through the deterministic loopback server. Each
request completes before the next interaction, history navigation does not
submit a request, and the history file is present after clean exit. A second
fresh process recalls the newest prompt, appends a sentinel, and submits it;
the request body proves the persisted composer state rather than relying on a
sparse redraw fragment.

The final fresh process receives Ctrl+V through an isolated synthetic xclip
command. The clipboard payload is inserted without a request, then Enter
submits exactly that payload. All three PTY processes leave the alternate
screen and restore canonical input and echo with exit status 0. The replay also
asserts four total loopback requests, stream=true, the selected model, and an
unchanged Hermes config boundary.

## Boundary

This is a configured Hades local-provider journey. It does not claim exact
Hermes provider persistence, remote OSC52 precedence, session switching or
resumption, provider errors, OAuth, external networking, or tool execution.
Hermes defects and unsafe implicit installers remain defects to fix, not
behavior to reproduce; Rust performance and safer capabilities remain
unbounded by this evidence.

## Linked artifacts

- [configured-surface replay](../../../scripts/replay_configured_surfaces.py)
- [configured-surface fixture](../../../tests/fixtures/parity/OBS-0090-hades-configured-primary-surfaces.json)
- [local-provider vertical slice](OBS-0089-hades-local-provider-vertical-slice-2026-08-02.md)
- [task ledger](../../../.hades/tasks.json)
