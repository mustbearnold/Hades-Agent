# Hades implementation observation: OBS-0089

- Subject: setup, local provider/model, prompt, and streamed answer
- Hades source: workspace implementation under test
- Terminal: fresh 120x40 direct PTY plus deterministic loopback HTTP/SSE fixture
- Capture: setup command, sidecar readback, fresh TUI process, request shape, delayed deltas, and cleanup
- Task: HAD-094
- Replay: scripts/replay_vertical_slice.py

This is the first deliberately product-facing vertical slice. It keeps the
existing Hermes parity setup and model overlays bounded and adds a separate,
explicit Hades local setup command so a user can reach a real answer without
credentials or an external service.

## Verified behavior

The replay runs:

    hades setup --local http://127.0.0.1:<port>/v1 vertical-model
    hades

Setup validates the loopback endpoint and atomically writes only the
Hades-owned hades-local-provider.conf sidecar. Hermes config.yaml remains
untouched, and no API key is written. A fresh Hades process with provider
environment variables removed reaches the ready composer by loading the
sidecar. Submitting vertical prompt sends one POST to /v1/chat/completions with
vertical-model, system/user messages, and stream=true.

The deterministic server deliberately pauses after the first assistant delta.
Hades renders First streamed delta. while the response is still incomplete,
then renders Final streamed answer. and returns to the visible ready state
after the [DONE] boundary. Ctrl+C exits with status 0 and restores canonical
input, echo, and the alternate screen.

## Boundary

This is an explicit Hades loopback extension, not a claim that Hermes persists
provider setup in this sidecar format. External providers, credentials, OAuth,
retries, tools, non-loopback networking, and Hermes setup continuation remain
separate tasks. Hermes failure cases are not copied into the implementation.

## Linked artifacts

- [vertical-slice replay](../../../scripts/replay_vertical_slice.py)
- [vertical-slice fixture](../../../tests/fixtures/parity/OBS-0089-hades-local-provider-vertical-slice.json)
- [CLI setup/config seam](../../../crates/hades-cli/src/main.rs)
- [task ledger](../../../.hades/tasks.json)
