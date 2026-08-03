#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd -- "$script_dir/.." && pwd)"
cd "$project_root"

python3 scripts/agent/control_plane.py validate
python3 scripts/validate_reference_fixture.py
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0016-hermes-input-history-persistence.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0018-hermes-editor-outcomes.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0020-hermes-modified-enter.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0021-hades-modified-enter.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0022-hermes-text-clipboard.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0023-hades-text-clipboard.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0024-hermes-osc52-clipboard.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0025-hades-osc52-clipboard.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0026-hermes-osc52-response-boundaries.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0028-hermes-osc52-st-termination.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0029-hades-osc52-st-termination.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0030-hermes-osc52-multiplexer-passthrough.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0031-hades-osc52-multiplexer-passthrough.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0032-hermes-osc52-timing-limits.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0033-hades-osc52-timing-limits.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0034-hermes-terminal-palette.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0035-hades-terminal-palette.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0036-hermes-slash-command-surfaces.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0098-hermes-help-catalog.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0099-hades-configured-help.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0100-hermes-help-lifecycle.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0101-hades-configured-help-lifecycle.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0102-hermes-help-resize.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0103-hades-configured-help-resize.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0038-hermes-model-picker-model-stage.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0039-hades-model-picker-model-stage.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0093-hermes-model-picker-selection.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0094-hades-model-picker-selection.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0096-hermes-distinct-model-selection.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0040-hermes-setup-wizard-cancel.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0041-hades-setup-wizard-cancel.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0042-hermes-full-setup-continuation.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0044-hermes-full-setup-provider-menu.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0045-hades-full-setup-provider-menu.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0069-hermes-standalone-setup.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0070-hades-standalone-setup.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0071-hermes-standalone-full-setup.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0072-hades-standalone-full-setup.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0073-hermes-standalone-terminal-platform.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0074-hades-standalone-terminal-platform.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0075-hermes-standalone-tool-configuration.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0076-hermes-tool-configuration-navigation.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0077-hermes-tool-provider-boundary.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0078-hades-tool-provider-boundary.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0079-hermes-tool-provider-inventory.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0080-hades-tool-provider-inventory.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0081-hermes-tool-provider-inventory-interaction.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0083-hermes-tool-provider-inventory-edges.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0082-hades-tool-provider-inventory-navigation.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0084-hades-tool-provider-inventory-navigation-edges.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0085-hermes-tool-provider-inventory-selection.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0086-hades-tool-provider-inventory-selection.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0087-hades-empty-platform-confirmation.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0088-hades-fresh-shell-launch.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0089-hades-local-provider-vertical-slice.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0090-hades-configured-primary-surfaces.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0091-hades-provider-failure-recovery.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0092-hades-conversation-context.json
cargo fmt --all -- --check
cargo check --workspace --all-targets --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --all-targets --locked
cargo build --locked --package hades-cli
python3 scripts/probe_tui_lifecycle.py --binary target/debug/hades
python3 scripts/replay_cli_launch.py --binary target/debug/hades --report .hades/runtime/cli-launch-replay.json
python3 scripts/replay_unconfigured_startup.py --binary target/debug/hades --report .hades/runtime/had064-unconfigured-startup-replay.json
python3 scripts/replay_unconfigured_input.py --binary target/debug/hades --report .hades/runtime/had066-unconfigured-input-replay.json --timeout 5
python3 scripts/replay_unconfigured_help.py --binary target/debug/hades --report .hades/runtime/hades-help-setup-required-replay.json --timeout 12
python3 scripts/replay_setup_required_actions.py --binary target/debug/hades --report .hades/runtime/setup-required-actions-replay.json --timeout 20
python3 scripts/replay_standalone_setup.py --binary target/debug/hades --report .hades/runtime/hades-standalone-setup-replay.json --timeout 5
python3 scripts/replay_standalone_full_setup.py --binary target/debug/hades --report .hades/runtime/hades-standalone-full-setup-replay.json --timeout 5
python3 scripts/replay_standalone_terminal_platform.py --binary target/debug/hades --report .hades/runtime/hades-standalone-terminal-platform-replay.json --timeout 5
python3 scripts/replay_standalone_empty_platform_confirmation.py --binary target/debug/hades --report .hades/runtime/hades-empty-platform-confirmation-replay.json --timeout 5
python3 scripts/replay_standalone_tool_provider_boundary.py --binary target/debug/hades --report .hades/runtime/hades-tool-provider-boundary-replay.json --timeout 5
python3 scripts/replay_standalone_tool_provider_inventory.py --binary target/debug/hades --report .hades/runtime/hades-tool-provider-inventory-replay.json --timeout 5
python3 scripts/replay_standalone_tool_provider_inventory_navigation.py --binary target/debug/hades --report .hades/runtime/hades-tool-provider-inventory-navigation-edges-replay.json --timeout 5
python3 scripts/replay_standalone_tool_provider_inventory_selection.py --binary target/debug/hades --report .hades/runtime/hades-tool-provider-inventory-selection-replay.json --timeout 5
python3 scripts/replay_vertical_slice.py --binary target/debug/hades --report .hades/runtime/vertical-slice-replay.json --timeout 8
python3 scripts/replay_configured_surfaces.py --binary target/debug/hades --report .hades/runtime/configured-surfaces-replay.json --timeout 8
python3 scripts/replay_configured_help.py --binary target/debug/hades --report .hades/runtime/configured-help-replay.json --timeout 60
python3 scripts/replay_configured_help_lifecycle.py --binary target/debug/hades --report .hades/runtime/configured-help-lifecycle-replay.json --timeout 60
python3 scripts/replay_configured_help_resize.py --binary target/debug/hades --report .hades/runtime/configured-help-resize-replay.json --timeout 60
python3 scripts/replay_provider_recovery.py --binary target/debug/hades --report .hades/runtime/provider-recovery-replay.json --timeout 8
python3 scripts/replay_conversation_context.py --binary target/debug/hades --report .hades/runtime/conversation-context-replay.json --timeout 8
python3 scripts/replay_model_selection.py --binary target/debug/hades --report .hades/runtime/model-selection-replay.json --timeout 10
cargo build --locked --release --package hades-cli
bash scripts/install_user_launcher.sh
python3 scripts/replay_fresh_shell_launch.py --report .hades/runtime/fresh-shell-launch-replay.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0095-hades-installed-model-selection.json
python3 scripts/replay_installed_model_selection.py --report .hades/runtime/installed-model-selection-replay.json --timeout 10
python3 scripts/replay_unconfigured_help.py --binary "$HOME/.local/bin/hades" --report .hades/runtime/installed-help-setup-required-hades.json --timeout 12
python3 scripts/replay_unconfigured_help.py --binary "$HOME/.local/bin/Hades" --report .hades/runtime/installed-help-setup-required-Hades.json --timeout 12
python3 scripts/replay_standalone_setup.py --binary "$HOME/.local/bin/hades" --report .hades/runtime/installed-standalone-setup-hades.json --timeout 5
python3 scripts/replay_standalone_full_setup.py --binary "$HOME/.local/bin/hades" --report .hades/runtime/installed-standalone-full-setup-hades.json --timeout 5
python3 scripts/replay_standalone_terminal_platform.py --binary "$HOME/.local/bin/hades" --report .hades/runtime/installed-standalone-terminal-platform-hades.json --timeout 5
python3 scripts/differential_replay.py --binary target/debug/hades --report .hades/runtime/differential-replay.json
python3 scripts/replay_composer.py --binary target/debug/hades --report .hades/runtime/composer-replay.json
python3 scripts/replay_completion.py --binary target/debug/hades --report .hades/runtime/completion-replay.json
python3 scripts/replay_composer.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0037-hades-unknown-slash-command.json --report .hades/runtime/unknown-command-replay.json
python3 scripts/replay_model_picker.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0039-hades-model-picker-model-stage.json --report .hades/runtime/model-picker-replay.json
python3 scripts/replay_setup_wizard.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0041-hades-setup-wizard-cancel.json --report .hades/runtime/setup-wizard-replay.json
python3 scripts/replay_setup_provider_menu.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0045-hades-full-setup-provider-menu.json --report .hades/runtime/setup-provider-replay.json
python3 scripts/replay_setup_provider_model_prompt.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0047-hades-provider-selection-model-prompt.json --report .hades/runtime/setup-provider-model-prompt-replay.json
python3 scripts/replay_setup_terminal_backend.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0049-hades-model-default-terminal-backend.json --report .hades/runtime/setup-terminal-backend-replay.json
python3 scripts/replay_setup_terminal_backend.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0057-hades-setup-platform-picker.json --report .hades/runtime/setup-platform-picker-replay.json
python3 scripts/replay_paste.py --binary target/debug/hades --report .hades/runtime/paste-replay.json
python3 scripts/replay_editor.py --binary target/debug/hades --report .hades/runtime/editor-replay.json
python3 scripts/replay_editor_outcomes.py --binary target/debug/hades --report .hades/runtime/editor-outcomes-replay.json
python3 scripts/replay_modified_enter.py --binary target/debug/hades --report .hades/runtime/modified-enter-replay.json
python3 scripts/replay_clipboard.py --binary target/debug/hades --report .hades/runtime/clipboard-replay.json
python3 scripts/replay_clipboard_text.py --binary target/debug/hades --report .hades/runtime/clipboard-text-replay.json
python3 scripts/replay_osc52_clipboard.py --binary target/debug/hades --report .hades/runtime/osc52-clipboard-replay.json
python3 scripts/replay_osc52_clipboard.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0027-hades-osc52-response-boundaries.json --report .hades/runtime/osc52-response-boundaries-replay.json
python3 scripts/probe_hermes_osc52_st_termination.py --report .hades/runtime/hermes-osc52-st-termination-probe.json
python3 scripts/probe_hermes_osc52_multiplexer.py --report .hades/runtime/hermes-osc52-multiplexer-probe.json --timeout 30
python3 scripts/probe_hermes_osc52_timing_limits.py --report .hades/runtime/hermes-osc52-timing-limits-probe.json
python3 scripts/probe_hermes_terminal_palette.py --report .hades/runtime/hermes-terminal-palette-probe.json --timeout 30
python3 scripts/probe_hermes_slash_commands.py --report .hades/runtime/hermes-slash-commands-probe.json --timeout 30
python3 scripts/probe_hermes_help_catalog.py --report .hades/runtime/hermes-help-catalog-probe.json --timeout 60
python3 scripts/probe_hermes_help_lifecycle.py --report .hades/runtime/hermes-help-lifecycle-probe.json --timeout 60
python3 scripts/probe_hermes_help_resize.py --report .hades/runtime/hermes-help-resize-probe.json --timeout 60
python3 scripts/probe_hermes_model_picker.py --report .hades/runtime/hermes-model-picker-probe.json --timeout 30
python3 scripts/probe_hermes_model_picker_selection.py --report .hades/runtime/hermes-model-picker-selection-probe.json --timeout 30
python3 scripts/probe_hermes_distinct_model_selection.py --report .hades/runtime/hermes-distinct-model-selection-probe.json --timeout 60
python3 scripts/probe_hermes_setup_wizard.py --report .hades/runtime/hermes-setup-wizard-probe.json --timeout 60
python3 scripts/probe_hermes_full_setup.py --report .hades/runtime/hermes-full-setup-probe.json --timeout 30
python3 scripts/probe_hermes_full_setup_provider.py --report .hades/runtime/hermes-full-setup-provider-probe.json --timeout 30
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0046-hermes-provider-selection.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0047-hades-provider-selection-model-prompt.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0048-hermes-model-default-terminal-backend.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0049-hades-model-default-terminal-backend.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0050-hermes-local-provider-stream.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0051-hades-local-provider-stream.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0052-hermes-stream-timing.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0053-hades-stream-timing.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0054-hermes-provider-errors.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0055-hermes-provider-setup-persistence.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0056-hermes-setup-config-shape.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0057-hades-setup-platform-picker.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0058-hermes-empty-platform-confirmation.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0097-hermes-empty-platform-reconciliation.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0059-hermes-unconfigured-startup.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0061-hermes-unconfigured-input-queue.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0060-hades-unconfigured-startup.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0062-hades-unconfigured-input.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0063-hermes-unconfigured-setup-escape.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0064-hermes-unconfigured-resolution.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0065-hermes-setup-required-reconciliation.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0066-hermes-help-setup-timing.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0067-hades-help-setup-required.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0104-hermes-setup-required-actions-revalidation.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0105-hades-setup-required-actions.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0106-hermes-setup-persistence-revalidation.json
python3 scripts/probe_hermes_full_setup_provider_selection.py --report .hades/runtime/hermes-full-setup-provider-selection-probe.json --timeout 30
python3 scripts/probe_hermes_full_setup_model_default.py --report .hades/runtime/hermes-full-setup-model-default-probe.json --timeout 30
python3 scripts/probe_hermes_local_provider_stream.py --report .hades/runtime/hermes-local-provider-stream-probe.json --timeout 30
python3 scripts/probe_hermes_stream_timing.py --report .hades/runtime/hermes-stream-timing-probe.json --timeout 30
python3 scripts/probe_hermes_provider_errors.py --report .hades/runtime/hermes-provider-errors-probe.json --timeout 30
python3 scripts/probe_hermes_provider_setup_persistence.py --report .hades/runtime/hermes-provider-setup-persistence-probe.json --timeout 30
python3 scripts/probe_hermes_setup_config_shape.py --report .hades/runtime/hermes-setup-config-shape-probe.json --timeout 30
python3 scripts/probe_hermes_empty_platform_confirmation.py --report .hades/runtime/hermes-empty-platform-confirmation-probe.json --timeout 30
python3 scripts/probe_hermes_unconfigured_startup.py --report .hades/runtime/hermes-unconfigured-startup-probe.json --timeout 30
python3 scripts/probe_hermes_unconfigured_input_queue.py --report .hades/runtime/hermes-unconfigured-input-queue-probe.json --timeout 30
python3 scripts/probe_hermes_unconfigured_setup_escape.py --report .hades/runtime/hermes-unconfigured-setup-escape-probe.json --timeout 30
python3 scripts/probe_hermes_unconfigured_resolution.py --report .hades/runtime/hermes-unconfigured-resolution-probe.json --timeout 30 --observation-window 15
python3 scripts/probe_hermes_setup_required_reconciliation.py --report .hades/runtime/hermes-setup-required-reconciliation-probe.json --timeout 30 --observation-window 15
python3 scripts/probe_hermes_help_setup_timing.py --report .hades/runtime/hermes-help-setup-timing-probe.json --timeout 30 --observation-window 15
python3 scripts/probe_hermes_setup_required_actions.py --report .hades/runtime/hermes-setup-required-actions-probe.json --timeout 30 --observation-window 3
python3 scripts/probe_hermes_standalone_setup.py --report .hades/runtime/hermes-standalone-setup-probe.json --timeout 30
python3 scripts/probe_hermes_standalone_full_setup.py --report .hades/runtime/hermes-standalone-full-setup-probe.json --timeout 60
python3 scripts/probe_hermes_standalone_terminal_platform.py --report .hades/runtime/hermes-standalone-terminal-platform-probe.json --timeout 60
python3 scripts/probe_hermes_standalone_tool_configuration.py --report .hades/runtime/hermes-standalone-tool-configuration-probe.json --timeout 30
python3 scripts/probe_hermes_tool_configuration_navigation.py --report .hades/runtime/hermes-tool-configuration-navigation-probe.json --timeout 30
python3 scripts/probe_hermes_tool_provider_boundary.py --report .hades/runtime/hermes-tool-provider-boundary-probe.json --timeout 30
python3 scripts/probe_hermes_tool_provider_inventory.py --report .hades/runtime/hermes-tool-provider-inventory-probe.json --timeout 30 --observation-window 1
python3 scripts/probe_hermes_tool_provider_inventory_interaction.py --report .hades/runtime/hermes-tool-provider-inventory-interaction-probe.json --timeout 60
python3 scripts/probe_hermes_tool_provider_inventory_edges.py --report .hades/runtime/hermes-tool-provider-inventory-edges-probe.json --timeout 60
python3 scripts/probe_hermes_tool_provider_inventory_selection.py --report .hades/runtime/hermes-tool-provider-inventory-selection-probe.json --timeout 30
python3 scripts/replay_terminal_palette.py --binary target/debug/hades --report .hades/runtime/hades-terminal-palette-replay.json
python3 scripts/replay_osc52_timing_limits.py --binary target/debug/hades --report .hades/runtime/hades-osc52-timing-limits-replay.json
python3 scripts/replay_osc52_clipboard.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0029-hades-osc52-st-termination.json --report .hades/runtime/hades-osc52-st-termination-replay.json
python3 scripts/replay_osc52_clipboard.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0031-hades-osc52-multiplexer-passthrough.json --report .hades/runtime/hades-osc52-multiplexer-replay.json
python3 scripts/replay_history.py --binary target/debug/hades --report .hades/runtime/history-replay.json
python3 scripts/replay_local_provider.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0051-hades-local-provider-stream.json --report .hades/runtime/local-provider-replay.json
python3 scripts/replay_local_provider_timing.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0053-hades-stream-timing.json --report .hades/runtime/local-provider-timing-replay.json
git diff --check

echo "verification: PASS"
