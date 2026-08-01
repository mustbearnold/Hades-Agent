# Hades implementation observation: OBS-0045

- Subject: bounded Hades Full setup provider menu
- Reference contract: [OBS-0044](OBS-0044-hermes-full-setup-provider-menu-2026-08-01.md)
- Hades source: workspace implementation under test
- Terminal: fresh 120x40 tmux-backed PTY
- Capture: normalized screen markers from an isolated replay
- Task: HAD-046
- Fixture: `tests/fixtures/parity/OBS-0045-hades-full-setup-provider-menu.json`
- Replay: `scripts/replay_setup_provider_menu.py`

HAD-046 carries the observed Hermes Full setup boundary into Hades without
pretending that provider configuration is implemented. The typed setup state
now accepts the Full setup row, renders the sanitized Configuration Location
and Inference Provider sections, and exposes only reversible provider-menu
navigation.

## Verified behavior

The 120x40 replay proves the observed two-step `/setup` entry sequence, Down
navigation to Full setup, and Enter transition into the bounded provider menu.
The rendered surface includes sanitized config/secrets/data/install paths,
the current model and active provider, the visible loopback row, the custom
endpoint row, the saved-custom-provider removal row, and the observed
navigation/cancellation hint.

Down moves the cursor to `Custom endpoint (enter URL manually)` while leaving
the active marker on `palette-loopback (loopback) — palette-model`. The replay
never presses Enter in the provider menu, never enters a secret, and exits
cleanly on Ctrl+C without Busy or a model request.

## Boundaries

The complete provider inventory, grouped-provider navigation, custom endpoint
entry, API keys, OAuth, model discovery, model selection, persistence after a
provider action, network behavior, and later Full setup sections remain
unimplemented or unknown. This is a bounded parity seam, not a claim about
complete Hermes setup behavior.

## Linked artifacts

- [Sanitized fixture](../../../tests/fixtures/parity/OBS-0045-hades-full-setup-provider-menu.json)
- [Replay](../../../scripts/replay_setup_provider_menu.py)
- [Hermes reference observation](OBS-0044-hermes-full-setup-provider-menu-2026-08-01.md)
- [Parity matrix](../MATRIX.md)
- [Task ledger](../../../.hades/tasks.json)
