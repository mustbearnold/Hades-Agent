# Reference observation: OBS-0096

- Subject: Hermes distinct-model selection effectiveness and persistence
- Reference: Hermes Agent 0.19.1 / `e444d165807f489b5c1ab8e4a612c8d09c2e67a2`
- Provenance: official [NousResearch/hermes-agent repository](https://github.com/NousResearch/hermes-agent), pinned to the source commit above
- Terminal: fresh 120x40 direct PTY with a rendered screen model
- Capture: synthetic custom loopback provider exposing `palette-model` and `alternate-model`
- Fixture: `tests/fixtures/parity/OBS-0096-hermes-distinct-model-selection.json`
- Probe: `scripts/probe_hermes_distinct_model_selection.py`
- Task: HAD-101

## Observed boundary

The bounded interaction opened `/model`, filtered the synthetic
`palette-loopback` provider, entered the model stage, filtered to
`alternate-model`, and pressed Enter. Hermes rendered the status marker
`model → alternate-model` without opening a chat request during selection.

After the selection, the probe entered one synthetic prompt and observed a
streamed OpenAI-compatible request whose normalized model marker was
`alternate-model`. The deterministic loopback response rendered
`Distinct model answer.`. The request trace records method/path, content type,
body size, stream flag, message roles, synthetic prompt presence, and the
presence of the synthetic authorization header without storing payload or
credential values.

The initial synthetic config differed from the selected-process config
(`config_changed_from_initial: true`), and a fresh process read the selected
config byte-equally. That is not treated as a selection-specific config
mutation because this probe does not include a no-selection control. The fresh
provider stage still rendered `Current: palette-model`, not
`Current: alternate-model`; the distinct selection is therefore classified as
effective for the submitted request but not persisted as the current model.

The process and fresh-process readback both exited through bounded Escape and
Ctrl+C cleanup with terminal ownership restored. Provider inventory/detail
requests stayed on the loopback server. No real credentials, external network,
host clipboard, or private runtime contents entered the fixture.

## Safety and parity boundary

The loopback trace may contain repeated metadata calls or an additional chat
request depending on Hermes timing. Those are retained as diagnostics and are
not requirements for Hades. Hades must not reproduce retries, non-stream
follow-ups, unsafe behavior, or stuck/error surfaces from this reference path.

The Hades implementation remains session-scoped: the selected model may affect
the next explicit request, but saved provider configuration and cross-process
model persistence require separate product work and evidence. Rust performance
or reliability is not capped to match any reference inefficiency.

## Linked artifacts

- Sanitized fixture: `tests/fixtures/parity/OBS-0096-hermes-distinct-model-selection.json`
- Direct-PTY probe: `scripts/probe_hermes_distinct_model_selection.py`
- Earlier Hermes selection boundary: [OBS-0093](OBS-0093-hermes-model-picker-selection-2026-08-02.md)
- Hades session-scoped implementation: [OBS-0094](OBS-0094-hades-model-picker-selection-2026-08-02.md)
- Parity matrix: `docs/parity/MATRIX.md`
- Task ledger: `.hades/tasks.json`
