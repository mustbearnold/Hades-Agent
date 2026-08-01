# Setup-required contract: OBS-0008

- Subject: Hades 120x40 provider-missing setup path
- Reference: OBS-0001 steps 8 and 9
- Product surface: hades-core, hades-app, and hades-tui
- Contract fixture: `tests/fixtures/parity/OBS-0008-setup-required.json`
- Executable oracle: focused reducer/snapshot tests and `differential-replay`
- Task: HAD-009

## Contract

When `/help` is submitted in the provider-missing bootstrap path, Hades keeps
`/help` in the composer and opens a `Setup Required` overlay. The overlay shows
the observed message that a model provider is needed and exposes `/model`,
`/setup`, and Ctrl+C actions.

The first Ctrl+C clears the retained `/help` input while keeping the setup
overlay visible. The second Ctrl+C exits with status 0. Provider setup, model
selection, retry behavior, and real provider integration remain deliberately
outside this slice.

## Normalization boundary

The snapshot test asserts the exact stable message and action landmarks. The
PTY replay checks the overlay markers, waits for the redraw caused by input
clearing, and proves clean exit. It does not claim colors, cursor placement,
provider configuration, or an implemented setup wizard.

## Linked artifacts

- [Contract fixture](../../../tests/fixtures/parity/OBS-0008-setup-required.json)
- [Core state and reducer](../../../crates/hades-core/src/lib.rs)
- [Application transition](../../../crates/hades-app/src/lib.rs)
- [Renderer and snapshot test](../../../crates/hades-tui/src/lib.rs)
- [Differential replay](../../../scripts/differential_replay.py)
- [Reference observation](OBS-0001-hermes-main-2026-08-01.md)
