# 006 — Setup and configuration

Status: active
Owner: project owner

## Purpose

The setup path takes an unconfigured Hades to a working configured state:
provider base URL and model selection, persisted in a machine-local config
(`$HERMES_HOME/hades-local-provider.conf`) that never enters the repository.
The unconfigured surface shows the delayed "Setup Required" overlay with
safe action boundaries.

## Requirements

- R1. The unconfigured surface renders "Setup Required" after the observed
  delay (8 s reference), with `/model` and `/setup` actions and a Ctrl+C
  escape; no provider request starts and no config file is created.
- R2. Follow-up action commands (`/model`, `/setup`) on the Setup Required
  overlay stay on the overlay — they never become composer drafts and never
  create `config.yaml`.
- R3. The setup wizard flow (setup → provider menu → provider model prompt →
  terminal backend) is captured; Escape cancels at each stage.
- R4. `hades setup --local <endpoint> [model]` writes
  `$HERMES_HOME/hades-local-provider.conf` (key=value: base_url/model, no API
  key).
- R5. Model selection is session-scoped: the palette model applies within a
  process, a fresh process falls back to the default; the persisted sidecar
  stays unchanged and Hermes `config.yaml` is never created.
- R6. The standalone (installed-launcher) setup replays prove the same
  boundaries through `~/.local/bin/hades`/`Hades` and the terminal-platform
  boundary (local backend accept → setup state persisted; first Ctrl+C
  leaves the alternate screen with the process alive, second exits).

## Acceptance criteria

- [ ] A1. Given an unconfigured launch, when `/help` is submitted, then the
      delayed Setup Required overlay renders with all observed markers.
- [ ] A2. Given the overlay, when `/model` or `/setup` is typed, then the
      overlay remains and no config is created.
- [ ] A3. Given `hades setup --local`, when run, then the config file exists
      with base_url/model and the TUI reaches ready.
- [ ] A4. Given a configured launch, when the model picker is used, then the
      selection applies to the process and a fresh process falls back.

## Out of scope

- OAuth, remote providers, credential storage (explicit unknowns).

## Open questions

- None recorded beyond the observed contracts (OBS-0039..OBS-0041,
  OBS-0095..OBS-0096, OBS-0104..OBS-0105).

## Links

Code: `crates/hades-cli` (setup), `crates/hades-app` · Tests:
`scripts/replay_setup_*.py`, `scripts/replay_setup_required_actions.py`,
`scripts/replay_standalone_*.py`, `scripts/replay_model_selection.py` · ADRs: ADR-0001
