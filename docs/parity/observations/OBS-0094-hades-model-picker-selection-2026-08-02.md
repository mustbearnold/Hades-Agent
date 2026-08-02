# Hades implementation observation: OBS-0094

- Subject: session-scoped model-picker selection and effective request use
- Reference boundary: OBS-0093 (OBS-0093-hermes-model-picker-selection-2026-08-02.md)
- Hades source baseline: 2140a915e6971dd2db2b45590db89da9c91e4621
- Terminal: fresh 120x40 direct PTY processes
- Capture: local setup sidecar, deterministic loopback HTTP/SSE server, and two-process readback
- Fixture: tests/fixtures/parity/OBS-0094-hades-model-picker-selection.json
- Replay: scripts/replay_model_selection.py
- Task: HAD-099

## Verified behavior

The replay first writes a Hades-owned local sidecar configured with
vertical-model. In a fresh TUI process, /model reaches the provider and model
stages, filtering to the visible palette-model row and pressing Enter closes
the picker with the visible status marker model → palette-model. Selection
itself sends no provider request.

The next explicit prompt sends one loopback OpenAI-compatible request using
palette-model, with stream=true, one system message, one user message, and no
authorization header. The delayed local SSE fixture proves the first delta is
visible before completion and the final answer returns the app to Ready.

The process exits with code 0, leaves the alternate screen, and restores
canonical input and echo. A fresh process reuses the exact same sidecar and
sends vertical-model again without selection input. The sidecar remains
byte-for-byte unchanged and Hermes config.yaml is not created.

## Boundary

The selected model is intentionally typed session state, not persisted provider
configuration. This is the narrowest safe implementation supported by the
isolated effective-use trace; it preserves the observed transient Hermes
selection surface without claiming that Hermes persists or applies the same
selection.

Hades does not reproduce Hermes repeated metadata requests, retries, failures,
unsafe behavior, or stuck surfaces. Provider catalogs, external providers,
OAuth, tools, session persistence, and selection races remain separate work.

## Linked artifacts

- Sanitized fixture: tests/fixtures/parity/OBS-0094-hades-model-picker-selection.json
- Direct PTY replay: scripts/replay_model_selection.py
- Hermes selection boundary: OBS-0093-hermes-model-picker-selection-2026-08-02.md
- Task ledger: .hades/tasks.json
