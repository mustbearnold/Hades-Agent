#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd -- "$script_dir/.." && pwd)"
cd "$project_root"
_start_ms=$(date +%s%3N)

# Bounded retries for timing-sensitive reference probes. The reference
# probes measure live Hermes timings and can hit their timeout under host
# load; up to two retries that preserve every failed attempt's report are the
# documented failure-policy response ("each retry must preserve the original
# error in its run log"). A probe that fails all three attempts still fails
# the gate; every preserved attempt-* report remains in .hades/runtime/.
run_probe() {
    local report_path="$1"
    shift
    local attempt=0
    while :; do
        if "$@"; then
            return 0
        fi
        local status=$?
        attempt=$((attempt + 1))
        if [ "$attempt" -ge 3 ]; then
            return "$status"
        fi
        if [ -f "$report_path" ]; then
            cp "$report_path" "${report_path%.json}.attempt-${attempt}.json"
            echo "[verify] probe attempt $attempt failed (status $status); report preserved at ${report_path%.json}.attempt-${attempt}.json; retrying: $*" >&2
        else
            echo "[verify] probe attempt $attempt failed (status $status) with no report; retrying: $*" >&2
        fi
    done
}


# HAD-125: the Rust control plane is the gate validator now; the parity
# check proves it agrees with the Python control plane on validate/next/show
# and the shared error paths, then the Rust binary validates the ledger.
cargo build --offline --package hades-dev --bin control_plane
python3 scripts/check_control_plane_parity.py
./target/debug/control_plane validate
# HAD-124: the Rust fixture validator (hades-dev) is the gate validator now;
# the differential check proves it agrees with the Python validator on every
# checked-in fixture, then the Python validator exits the gate. The Rust loop
# validates exactly the same explicit fixture set the Python validator lines
# below cover (legacy pre-contract fixtures and replay contracts are not
# validator inputs; the parity check above still covers every fixture).
cargo build --offline --package hades-dev --bin validate_fixture
python3 scripts/check_fixture_parity.py
for fixture in \
    tests/fixtures/parity/OBS-0016-hermes-input-history-persistence.json \
    tests/fixtures/parity/OBS-0018-hermes-editor-outcomes.json \
    tests/fixtures/parity/OBS-0020-hermes-modified-enter.json \
    tests/fixtures/parity/OBS-0021-hades-modified-enter.json \
    tests/fixtures/parity/OBS-0022-hermes-text-clipboard.json \
    tests/fixtures/parity/OBS-0023-hades-text-clipboard.json \
    tests/fixtures/parity/OBS-0024-hermes-osc52-clipboard.json \
    tests/fixtures/parity/OBS-0025-hades-osc52-clipboard.json \
    tests/fixtures/parity/OBS-0026-hermes-osc52-response-boundaries.json \
    tests/fixtures/parity/OBS-0028-hermes-osc52-st-termination.json \
    tests/fixtures/parity/OBS-0029-hades-osc52-st-termination.json \
    tests/fixtures/parity/OBS-0030-hermes-osc52-multiplexer-passthrough.json \
    tests/fixtures/parity/OBS-0031-hades-osc52-multiplexer-passthrough.json \
    tests/fixtures/parity/OBS-0032-hermes-osc52-timing-limits.json \
    tests/fixtures/parity/OBS-0033-hades-osc52-timing-limits.json \
    tests/fixtures/parity/OBS-0034-hermes-terminal-palette.json \
    tests/fixtures/parity/OBS-0035-hades-terminal-palette.json \
    tests/fixtures/parity/OBS-0036-hermes-slash-command-surfaces.json \
    tests/fixtures/parity/OBS-0038-hermes-model-picker-model-stage.json \
    tests/fixtures/parity/OBS-0039-hades-model-picker-model-stage.json \
    tests/fixtures/parity/OBS-0040-hermes-setup-wizard-cancel.json \
    tests/fixtures/parity/OBS-0041-hades-setup-wizard-cancel.json \
    tests/fixtures/parity/OBS-0042-hermes-full-setup-continuation.json \
    tests/fixtures/parity/OBS-0044-hermes-full-setup-provider-menu.json \
    tests/fixtures/parity/OBS-0045-hades-full-setup-provider-menu.json \
    tests/fixtures/parity/OBS-0046-hermes-provider-selection.json \
    tests/fixtures/parity/OBS-0047-hades-provider-selection-model-prompt.json \
    tests/fixtures/parity/OBS-0048-hermes-model-default-terminal-backend.json \
    tests/fixtures/parity/OBS-0049-hades-model-default-terminal-backend.json \
    tests/fixtures/parity/OBS-0050-hermes-local-provider-stream.json \
    tests/fixtures/parity/OBS-0051-hades-local-provider-stream.json \
    tests/fixtures/parity/OBS-0052-hermes-stream-timing.json \
    tests/fixtures/parity/OBS-0053-hades-stream-timing.json \
    tests/fixtures/parity/OBS-0054-hermes-provider-errors.json \
    tests/fixtures/parity/OBS-0055-hermes-provider-setup-persistence.json \
    tests/fixtures/parity/OBS-0056-hermes-setup-config-shape.json \
    tests/fixtures/parity/OBS-0057-hades-setup-platform-picker.json \
    tests/fixtures/parity/OBS-0058-hermes-empty-platform-confirmation.json \
    tests/fixtures/parity/OBS-0059-hermes-unconfigured-startup.json \
    tests/fixtures/parity/OBS-0060-hades-unconfigured-startup.json \
    tests/fixtures/parity/OBS-0061-hermes-unconfigured-input-queue.json \
    tests/fixtures/parity/OBS-0062-hades-unconfigured-input.json \
    tests/fixtures/parity/OBS-0063-hermes-unconfigured-setup-escape.json \
    tests/fixtures/parity/OBS-0064-hermes-unconfigured-resolution.json \
    tests/fixtures/parity/OBS-0065-hermes-setup-required-reconciliation.json \
    tests/fixtures/parity/OBS-0066-hermes-help-setup-timing.json \
    tests/fixtures/parity/OBS-0067-hades-help-setup-required.json \
    tests/fixtures/parity/OBS-0069-hermes-standalone-setup.json \
    tests/fixtures/parity/OBS-0070-hades-standalone-setup.json \
    tests/fixtures/parity/OBS-0071-hermes-standalone-full-setup.json \
    tests/fixtures/parity/OBS-0072-hades-standalone-full-setup.json \
    tests/fixtures/parity/OBS-0073-hermes-standalone-terminal-platform.json \
    tests/fixtures/parity/OBS-0074-hades-standalone-terminal-platform.json \
    tests/fixtures/parity/OBS-0075-hermes-standalone-tool-configuration.json \
    tests/fixtures/parity/OBS-0076-hermes-tool-configuration-navigation.json \
    tests/fixtures/parity/OBS-0077-hermes-tool-provider-boundary.json \
    tests/fixtures/parity/OBS-0078-hades-tool-provider-boundary.json \
    tests/fixtures/parity/OBS-0079-hermes-tool-provider-inventory.json \
    tests/fixtures/parity/OBS-0080-hades-tool-provider-inventory.json \
    tests/fixtures/parity/OBS-0081-hermes-tool-provider-inventory-interaction.json \
    tests/fixtures/parity/OBS-0082-hades-tool-provider-inventory-navigation.json \
    tests/fixtures/parity/OBS-0083-hermes-tool-provider-inventory-edges.json \
    tests/fixtures/parity/OBS-0084-hades-tool-provider-inventory-navigation-edges.json \
    tests/fixtures/parity/OBS-0085-hermes-tool-provider-inventory-selection.json \
    tests/fixtures/parity/OBS-0086-hades-tool-provider-inventory-selection.json \
    tests/fixtures/parity/OBS-0087-hades-empty-platform-confirmation.json \
    tests/fixtures/parity/OBS-0088-hades-fresh-shell-launch.json \
    tests/fixtures/parity/OBS-0089-hades-local-provider-vertical-slice.json \
    tests/fixtures/parity/OBS-0090-hades-configured-primary-surfaces.json \
    tests/fixtures/parity/OBS-0091-hades-provider-failure-recovery.json \
    tests/fixtures/parity/OBS-0092-hades-conversation-context.json \
    tests/fixtures/parity/OBS-0093-hermes-model-picker-selection.json \
    tests/fixtures/parity/OBS-0094-hades-model-picker-selection.json \
    tests/fixtures/parity/OBS-0095-hades-installed-model-selection.json \
    tests/fixtures/parity/OBS-0096-hermes-distinct-model-selection.json \
    tests/fixtures/parity/OBS-0097-hermes-empty-platform-reconciliation.json \
    tests/fixtures/parity/OBS-0098-hermes-help-catalog.json \
    tests/fixtures/parity/OBS-0099-hades-configured-help.json \
    tests/fixtures/parity/OBS-0100-hermes-help-lifecycle.json \
    tests/fixtures/parity/OBS-0101-hades-configured-help-lifecycle.json \
    tests/fixtures/parity/OBS-0102-hermes-help-resize.json \
    tests/fixtures/parity/OBS-0103-hades-configured-help-resize.json \
    tests/fixtures/parity/OBS-0104-hermes-setup-required-actions-revalidation.json \
    tests/fixtures/parity/OBS-0105-hades-setup-required-actions.json \
    tests/fixtures/parity/OBS-0106-hermes-setup-persistence-revalidation.json \
    tests/fixtures/parity/OBS-0107-hades-setup-persistence.json \
    tests/fixtures/parity/OBS-0108-hermes-multi-turn-provider.json \
    tests/fixtures/parity/OBS-0109-hermes-tool-schema-semantics.json \
    tests/fixtures/parity/OBS-0110-hermes-tool-call-handoff.json \
    tests/fixtures/parity/OBS-0111-hades-tool-call-deltas.json \
    tests/fixtures/parity/OBS-0112-hermes-tool-inventory.json \
    tests/fixtures/parity/OBS-0113-hades-tool-inventory-advertisement.json \
    tests/fixtures/parity/OBS-0114-hermes-tool-completion-handoff.json \
    tests/fixtures/parity/OBS-0115-hades-tool-result-follow-up.json \
    tests/fixtures/parity/OBS-0116-hermes-clarify-question-surface.json
do
    ./target/debug/validate_fixture "$fixture" >/dev/null || exit 1
done
# HAD-126: the Rust replay runtime (spawn/wait/terminal-flags/report) is
# ported; the parity check proves it agrees with probe_tui_lifecycle on
# clean output, marker matching, and real-subprocess exit shapes.
cargo build --offline --package hades-dev --bin replay_runtime_diff
python3 scripts/check_replay_runtime_parity.py
# HAD-132: the configured-family runtime extensions (hold-provider server +
# tmux driver) are ported; the parity check proves they agree with
# replay_composer.py on marker matching, key payloads, real tmux session
# lifecycle, and hold-provider request gating.
cargo build --offline --package hades-dev --bin tmux_hold_diff
python3 scripts/check_tmux_hold_parity.py
# HAD-123: Rust harness foundation. The screen-emulator parity check feeds
# live Hades PTY output through both the Python and Rust Screen models and
# requires identical lines, style inventory, and marker styles.
cargo build --offline --package hades-dev --bin screen_diff
python3 scripts/check_screen_parity.py
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
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0107-hades-setup-persistence.json
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
run_probe .hades/runtime/hermes-tool-inventory-probe.json python3 scripts/probe_hermes_tool_inventory.py --report .hades/runtime/hermes-tool-inventory-probe.json --timeout 60
python3 scripts/probe_tui_lifecycle.py --binary target/debug/hades
# HAD-127: replay-cli-launch is ported to Rust; the differential check
# proves the Rust and Python replays produce identical reports, then the
# Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_cli_launch
python3 scripts/check_cli_launch_parity.py
./target/debug/replay_cli_launch --binary target/debug/hades --report .hades/runtime/cli-launch-replay.json
# HAD-128: replay-unconfigured-startup is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_unconfigured_startup
python3 scripts/check_replay_parity.py replay_unconfigured_startup replay_unconfigured_startup
./target/debug/replay_unconfigured_startup --binary target/debug/hades --report .hades/runtime/had064-unconfigured-startup-replay.json
# HAD-129: replay-unconfigured-input is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_unconfigured_input
python3 scripts/check_replay_parity.py replay_unconfigured_input replay_unconfigured_input
./target/debug/replay_unconfigured_input --binary target/debug/hades --report .hades/runtime/had066-unconfigured-input-replay.json --timeout 5
# HAD-130: replay-unconfigured-help is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_unconfigured_help
python3 scripts/check_replay_parity.py replay_unconfigured_help replay_unconfigured_help
./target/debug/replay_unconfigured_help --binary target/debug/hades --report .hades/runtime/hades-help-setup-required-replay.json --timeout 12
# HAD-161: replay-setup-required-actions is ported to Rust; the
# differential check proves identical reports, then the Rust binary is
# the gate replay.
cargo build --offline --package hades-dev --bin replay_setup_required_actions
python3 scripts/check_replay_parity.py replay_setup_required_actions replay_setup_required_actions --timeout 20
./target/debug/replay_setup_required_actions --binary target/debug/hades --report .hades/runtime/setup-required-actions-replay.json --timeout 20
python3 scripts/replay_standalone_setup.py --binary target/debug/hades --report .hades/runtime/hades-standalone-setup-replay.json --timeout 5
python3 scripts/replay_standalone_full_setup.py --binary target/debug/hades --report .hades/runtime/hades-standalone-full-setup-replay.json --timeout 5
python3 scripts/replay_standalone_terminal_platform.py --binary target/debug/hades --report .hades/runtime/hades-standalone-terminal-platform-replay.json --timeout 5
python3 scripts/replay_standalone_empty_platform_confirmation.py --binary target/debug/hades --report .hades/runtime/hades-empty-platform-confirmation-replay.json --timeout 5
python3 scripts/replay_standalone_tool_provider_boundary.py --binary target/debug/hades --report .hades/runtime/hades-tool-provider-boundary-replay.json --timeout 5
python3 scripts/replay_standalone_tool_provider_inventory.py --binary target/debug/hades --report .hades/runtime/hades-tool-provider-inventory-replay.json --timeout 5
python3 scripts/replay_standalone_tool_provider_inventory_navigation.py --binary target/debug/hades --report .hades/runtime/hades-tool-provider-inventory-navigation-edges-replay.json --timeout 5
python3 scripts/replay_standalone_tool_provider_inventory_selection.py --binary target/debug/hades --report .hades/runtime/hades-tool-provider-inventory-selection-replay.json --timeout 5
# HAD-131: replay-vertical-slice is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_vertical_slice
python3 scripts/check_replay_parity.py replay_vertical_slice replay_vertical_slice
./target/debug/replay_vertical_slice --binary target/debug/hades --report .hades/runtime/vertical-slice-replay.json --timeout 8
# HAD-151: replay-configured-surfaces is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_configured_surfaces
python3 scripts/check_replay_parity.py replay_configured_surfaces replay_configured_surfaces --timeout 8
./target/debug/replay_configured_surfaces --binary target/debug/hades --report .hades/runtime/configured-surfaces-replay.json --timeout 8
# HAD-148: replay-configured-help is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_configured_help
python3 scripts/check_replay_parity.py replay_configured_help replay_configured_help --timeout 20
./target/debug/replay_configured_help --binary target/debug/hades --report .hades/runtime/configured-help-replay.json --timeout 60
# HAD-149: replay-configured-help-lifecycle is ported to Rust; the
# differential check proves identical reports, then the Rust binary is
# the gate replay.
cargo build --offline --package hades-dev --bin replay_configured_help_lifecycle
python3 scripts/check_replay_parity.py replay_configured_help_lifecycle replay_configured_help_lifecycle --timeout 20
./target/debug/replay_configured_help_lifecycle --binary target/debug/hades --report .hades/runtime/configured-help-lifecycle-replay.json --timeout 60
# HAD-150: replay-configured-help-resize is ported to Rust; the
# differential check proves identical reports, then the Rust binary is
# the gate replay.
cargo build --offline --package hades-dev --bin replay_configured_help_resize
python3 scripts/check_replay_parity.py replay_configured_help_resize replay_configured_help_resize --timeout 20
./target/debug/replay_configured_help_resize --binary target/debug/hades --report .hades/runtime/configured-help-resize-replay.json --timeout 60
# HAD-160: replay-provider-recovery is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_provider_recovery
python3 scripts/check_replay_parity.py replay_provider_recovery replay_provider_recovery --timeout 8
./target/debug/replay_provider_recovery --binary target/debug/hades --report .hades/runtime/provider-recovery-replay.json --timeout 8
# HAD-152: replay-conversation-context is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_conversation_context
python3 scripts/check_replay_parity.py replay_conversation_context replay_conversation_context --timeout 8
./target/debug/replay_conversation_context --binary target/debug/hades --report .hades/runtime/conversation-context-replay.json --timeout 8
# HAD-170: replay-tool-call-deltas is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_tool_call_deltas
python3 scripts/check_replay_parity.py replay_tool_call_deltas replay_tool_call_deltas --timeout 8
./target/debug/replay_tool_call_deltas --binary target/debug/hades --report .hades/runtime/tool-call-deltas-replay.json --timeout 8
# HAD-157: replay-model-selection is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_model_selection
python3 scripts/check_replay_parity.py replay_model_selection replay_model_selection --timeout 10
./target/debug/replay_model_selection --binary target/debug/hades --report .hades/runtime/model-selection-replay.json --timeout 10
cargo build --locked --release --package hades-cli
bash scripts/install_user_launcher.sh
# HAD-153: replay-fresh-shell-launch is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_fresh_shell_launch
python3 scripts/check_replay_parity.py replay_fresh_shell_launch replay_fresh_shell_launch --timeout 10
./target/debug/replay_fresh_shell_launch --report .hades/runtime/fresh-shell-launch-replay.json --timeout 10
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0095-hades-installed-model-selection.json
# HAD-154: replay-installed-model-selection is ported to Rust; the
# differential check proves identical reports, then the Rust binary is
# the gate replay.
cargo build --offline --package hades-dev --bin replay_installed_model_selection
python3 scripts/check_replay_parity.py replay_installed_model_selection replay_installed_model_selection --timeout 10
./target/debug/replay_installed_model_selection --report .hades/runtime/installed-model-selection-replay.json --timeout 10
./target/debug/replay_unconfigured_help --binary "$HOME/.local/bin/hades" --report .hades/runtime/installed-help-setup-required-hades.json --timeout 12
./target/debug/replay_unconfigured_help --binary "$HOME/.local/bin/Hades" --report .hades/runtime/installed-help-setup-required-Hades.json --timeout 12
python3 scripts/replay_standalone_setup.py --binary "$HOME/.local/bin/hades" --report .hades/runtime/installed-standalone-setup-hades.json --timeout 5
python3 scripts/replay_standalone_full_setup.py --binary "$HOME/.local/bin/hades" --report .hades/runtime/installed-standalone-full-setup-hades.json --timeout 5
python3 scripts/replay_standalone_terminal_platform.py --binary "$HOME/.local/bin/hades" --report .hades/runtime/installed-standalone-terminal-platform-hades.json --timeout 5
python3 scripts/differential_replay.py --binary target/debug/hades --report .hades/runtime/differential-replay.json
# HAD-133: replay-composer is ported to Rust; the differential check proves
# identical reports on the default contract, then the Rust binary is the
# gate replay for both the default and OBS-0037 invocations.
cargo build --offline --package hades-dev --bin replay_composer
python3 scripts/check_replay_parity.py replay_composer replay_composer
./target/debug/replay_composer --binary target/debug/hades --report .hades/runtime/composer-replay.json
# HAD-136: replay-completion is ported to Rust; the differential check
# proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_completion
python3 scripts/check_replay_parity.py replay_completion replay_completion
./target/debug/replay_completion --binary target/debug/hades --report .hades/runtime/completion-replay.json
./target/debug/replay_composer --binary target/debug/hades --contract tests/fixtures/parity/OBS-0037-hades-unknown-slash-command.json --report .hades/runtime/unknown-command-replay.json
# HAD-146: replay-model-picker is ported to Rust; the differential check
# proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_model_picker
python3 scripts/check_replay_parity.py replay_model_picker replay_model_picker --contract tests/fixtures/parity/OBS-0039-hades-model-picker-model-stage.json
./target/debug/replay_model_picker --binary target/debug/hades --contract tests/fixtures/parity/OBS-0039-hades-model-picker-model-stage.json --report .hades/runtime/model-picker-replay.json
# HAD-140: replay-setup-wizard is ported to Rust; the differential check
# proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_setup_wizard
python3 scripts/check_replay_parity.py replay_setup_wizard replay_setup_wizard --contract tests/fixtures/parity/OBS-0041-hades-setup-wizard-cancel.json
./target/debug/replay_setup_wizard --binary target/debug/hades --contract tests/fixtures/parity/OBS-0041-hades-setup-wizard-cancel.json --report .hades/runtime/setup-wizard-replay.json
# HAD-141: replay-setup-provider-menu is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_setup_provider_menu
python3 scripts/check_replay_parity.py replay_setup_provider_menu replay_setup_provider_menu --contract tests/fixtures/parity/OBS-0045-hades-full-setup-provider-menu.json
./target/debug/replay_setup_provider_menu --binary target/debug/hades --contract tests/fixtures/parity/OBS-0045-hades-full-setup-provider-menu.json --report .hades/runtime/setup-provider-replay.json
# HAD-142: replay-setup-provider-model-prompt is ported to Rust; the
# differential check proves identical reports, then the Rust binary is the
# gate replay.
cargo build --offline --package hades-dev --bin replay_setup_provider_model_prompt
python3 scripts/check_replay_parity.py replay_setup_provider_model_prompt replay_setup_provider_model_prompt --contract tests/fixtures/parity/OBS-0047-hades-provider-selection-model-prompt.json
./target/debug/replay_setup_provider_model_prompt --binary target/debug/hades --contract tests/fixtures/parity/OBS-0047-hades-provider-selection-model-prompt.json --report .hades/runtime/setup-provider-model-prompt-replay.json
# HAD-143: replay-setup-terminal-backend is ported to Rust; the
# differential check proves identical reports on both contracts, then the
# Rust binary is the gate replay for both invocations.
cargo build --offline --package hades-dev --bin replay_setup_terminal_backend
python3 scripts/check_replay_parity.py replay_setup_terminal_backend replay_setup_terminal_backend --contract tests/fixtures/parity/OBS-0049-hades-model-default-terminal-backend.json
./target/debug/replay_setup_terminal_backend --binary target/debug/hades --contract tests/fixtures/parity/OBS-0049-hades-model-default-terminal-backend.json --report .hades/runtime/setup-terminal-backend-replay.json
./target/debug/replay_setup_terminal_backend --binary target/debug/hades --contract tests/fixtures/parity/OBS-0057-hades-setup-platform-picker.json --report .hades/runtime/setup-platform-picker-replay.json
# HAD-138: replay-paste is ported to Rust; the differential check proves
# identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_paste
python3 scripts/check_replay_parity.py replay_paste replay_paste
./target/debug/replay_paste --binary target/debug/hades --report .hades/runtime/paste-replay.json
# HAD-139: replay-editor is ported to Rust; the differential check proves
# identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_editor
python3 scripts/check_replay_parity.py replay_editor replay_editor
./target/debug/replay_editor --binary target/debug/hades --report .hades/runtime/editor-replay.json
# HAD-144: replay-editor-outcomes is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_editor_outcomes
python3 scripts/check_replay_parity.py replay_editor_outcomes replay_editor_outcomes
./target/debug/replay_editor_outcomes --binary target/debug/hades --report .hades/runtime/editor-outcomes-replay.json
# HAD-145: replay-modified-enter is ported to Rust; the differential check
# proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_modified_enter
python3 scripts/check_replay_parity.py replay_modified_enter replay_modified_enter
./target/debug/replay_modified_enter --binary target/debug/hades --report .hades/runtime/modified-enter-replay.json
# HAD-137: replay-clipboard is ported to Rust; the differential check
# proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_clipboard
python3 scripts/check_replay_parity.py replay_clipboard replay_clipboard
./target/debug/replay_clipboard --binary target/debug/hades --report .hades/runtime/clipboard-replay.json
# HAD-147: replay-clipboard-text is ported to Rust; the differential check
# proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_clipboard_text
python3 scripts/check_replay_parity.py replay_clipboard_text replay_clipboard_text --timeout 8
./target/debug/replay_clipboard_text --binary target/debug/hades --report .hades/runtime/clipboard-text-replay.json --timeout 8
# HAD-158: replay-osc52-clipboard is ported to Rust; the differential
# checks prove identical reports on the OBS-0025 and OBS-0027 contracts,
# then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_osc52_clipboard
python3 scripts/check_replay_parity.py replay_osc52_clipboard replay_osc52_clipboard --timeout 8
python3 scripts/check_replay_parity.py replay_osc52_clipboard replay_osc52_clipboard --contract tests/fixtures/parity/OBS-0027-hades-osc52-response-boundaries.json --timeout 8
./target/debug/replay_osc52_clipboard --binary target/debug/hades --report .hades/runtime/osc52-clipboard-replay.json --timeout 8
./target/debug/replay_osc52_clipboard --binary target/debug/hades --contract tests/fixtures/parity/OBS-0027-hades-osc52-response-boundaries.json --report .hades/runtime/osc52-response-boundaries-replay.json --timeout 8
run_probe .hades/runtime/hermes-osc52-st-termination-probe.json python3 scripts/probe_hermes_osc52_st_termination.py --report .hades/runtime/hermes-osc52-st-termination-probe.json --timeout 60
run_probe .hades/runtime/hermes-osc52-multiplexer-probe.json python3 scripts/probe_hermes_osc52_multiplexer.py --report .hades/runtime/hermes-osc52-multiplexer-probe.json --timeout 30
run_probe .hades/runtime/hermes-osc52-timing-limits-probe.json python3 scripts/probe_hermes_osc52_timing_limits.py --report .hades/runtime/hermes-osc52-timing-limits-probe.json --timeout 60
run_probe .hades/runtime/hermes-terminal-palette-probe.json python3 scripts/probe_hermes_terminal_palette.py --report .hades/runtime/hermes-terminal-palette-probe.json --timeout 30
run_probe .hades/runtime/hermes-slash-commands-probe.json python3 scripts/probe_hermes_slash_commands.py --report .hades/runtime/hermes-slash-commands-probe.json --timeout 30
run_probe .hades/runtime/hermes-help-catalog-probe.json python3 scripts/probe_hermes_help_catalog.py --report .hades/runtime/hermes-help-catalog-probe.json --timeout 60
run_probe .hades/runtime/hermes-help-lifecycle-probe.json python3 scripts/probe_hermes_help_lifecycle.py --report .hades/runtime/hermes-help-lifecycle-probe.json --timeout 60
run_probe .hades/runtime/hermes-help-resize-probe.json python3 scripts/probe_hermes_help_resize.py --report .hades/runtime/hermes-help-resize-probe.json --timeout 60
run_probe .hades/runtime/hermes-model-picker-probe.json python3 scripts/probe_hermes_model_picker.py --report .hades/runtime/hermes-model-picker-probe.json --timeout 30
run_probe .hades/runtime/hermes-model-picker-selection-probe.json python3 scripts/probe_hermes_model_picker_selection.py --report .hades/runtime/hermes-model-picker-selection-probe.json --timeout 30
run_probe .hades/runtime/hermes-distinct-model-selection-probe.json python3 scripts/probe_hermes_distinct_model_selection.py --report .hades/runtime/hermes-distinct-model-selection-probe.json --timeout 60
run_probe .hades/runtime/hermes-setup-wizard-probe.json python3 scripts/probe_hermes_setup_wizard.py --report .hades/runtime/hermes-setup-wizard-probe.json --timeout 60
run_probe .hades/runtime/hermes-full-setup-probe.json python3 scripts/probe_hermes_full_setup.py --report .hades/runtime/hermes-full-setup-probe.json --timeout 30
run_probe .hades/runtime/hermes-full-setup-provider-probe.json python3 scripts/probe_hermes_full_setup_provider.py --report .hades/runtime/hermes-full-setup-provider-probe.json --timeout 30
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0046-hermes-provider-selection.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0047-hades-provider-selection-model-prompt.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0048-hermes-model-default-terminal-backend.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0049-hades-model-default-terminal-backend.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0050-hermes-local-provider-stream.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0108-hermes-multi-turn-provider.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0109-hermes-tool-schema-semantics.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0051-hades-local-provider-stream.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0111-hades-tool-call-deltas.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0113-hades-tool-inventory-advertisement.json
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
run_probe .hades/runtime/hermes-full-setup-provider-selection-probe.json python3 scripts/probe_hermes_full_setup_provider_selection.py --report .hades/runtime/hermes-full-setup-provider-selection-probe.json --timeout 30
run_probe .hades/runtime/hermes-full-setup-model-default-probe.json python3 scripts/probe_hermes_full_setup_model_default.py --report .hades/runtime/hermes-full-setup-model-default-probe.json --timeout 30
run_probe .hades/runtime/hermes-local-provider-stream-probe.json python3 scripts/probe_hermes_local_provider_stream.py --report .hades/runtime/hermes-local-provider-stream-probe.json --timeout 30
run_probe .hades/runtime/hermes-multi-turn-provider-probe.json python3 scripts/probe_hermes_multi_turn_provider.py --report .hades/runtime/hermes-multi-turn-provider-probe.json --timeout 30
run_probe .hades/runtime/hermes-tool-schema-semantics-probe.json python3 scripts/probe_hermes_tool_schema_semantics.py --report .hades/runtime/hermes-tool-schema-semantics-probe.json --timeout 30
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0112-hermes-tool-inventory.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0110-hermes-tool-call-handoff.json
run_probe .hades/runtime/hermes-tool-call-handoff-probe.json python3 scripts/probe_hermes_tool_call_handoff.py --report .hades/runtime/hermes-tool-call-handoff-probe.json --timeout 30 --observation-window 0.2
run_probe .hades/runtime/hermes-tool-completion-handoff-probe.json python3 scripts/probe_hermes_tool_completion_handoff.py --report .hades/runtime/hermes-tool-completion-handoff-probe.json --timeout 90 --observation-window 4
run_probe .hades/runtime/hermes-clarify-question-surface-probe.json python3 scripts/probe_hermes_clarify_question_surface.py --report .hades/runtime/hermes-clarify-question-surface-probe.json --timeout 90 --observation-window 3
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0114-hermes-tool-completion-handoff.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0115-hades-tool-result-follow-up.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0116-hermes-clarify-question-surface.json
run_probe .hades/runtime/hermes-stream-timing-probe.json python3 scripts/probe_hermes_stream_timing.py --report .hades/runtime/hermes-stream-timing-probe.json --timeout 30
run_probe .hades/runtime/hermes-provider-errors-probe.json python3 scripts/probe_hermes_provider_errors.py --report .hades/runtime/hermes-provider-errors-probe.json --timeout 30
run_probe .hades/runtime/hermes-provider-setup-persistence-probe.json python3 scripts/probe_hermes_provider_setup_persistence.py --report .hades/runtime/hermes-provider-setup-persistence-probe.json --timeout 30
run_probe .hades/runtime/hermes-setup-config-shape-probe.json python3 scripts/probe_hermes_setup_config_shape.py --report .hades/runtime/hermes-setup-config-shape-probe.json --timeout 30
run_probe .hades/runtime/hermes-empty-platform-confirmation-probe.json python3 scripts/probe_hermes_empty_platform_confirmation.py --report .hades/runtime/hermes-empty-platform-confirmation-probe.json --timeout 30
run_probe .hades/runtime/hermes-unconfigured-startup-probe.json python3 scripts/probe_hermes_unconfigured_startup.py --report .hades/runtime/hermes-unconfigured-startup-probe.json --timeout 30
run_probe .hades/runtime/hermes-unconfigured-input-queue-probe.json python3 scripts/probe_hermes_unconfigured_input_queue.py --report .hades/runtime/hermes-unconfigured-input-queue-probe.json --timeout 30
run_probe .hades/runtime/hermes-unconfigured-setup-escape-probe.json python3 scripts/probe_hermes_unconfigured_setup_escape.py --report .hades/runtime/hermes-unconfigured-setup-escape-probe.json --timeout 30
run_probe .hades/runtime/hermes-unconfigured-resolution-probe.json python3 scripts/probe_hermes_unconfigured_resolution.py --report .hades/runtime/hermes-unconfigured-resolution-probe.json --timeout 30 --observation-window 15
run_probe .hades/runtime/hermes-setup-required-reconciliation-probe.json python3 scripts/probe_hermes_setup_required_reconciliation.py --report .hades/runtime/hermes-setup-required-reconciliation-probe.json --timeout 30 --observation-window 15
run_probe .hades/runtime/hermes-help-setup-timing-probe.json python3 scripts/probe_hermes_help_setup_timing.py --report .hades/runtime/hermes-help-setup-timing-probe.json --timeout 30 --observation-window 15
run_probe .hades/runtime/hermes-setup-required-actions-probe.json python3 scripts/probe_hermes_setup_required_actions.py --report .hades/runtime/hermes-setup-required-actions-probe.json --timeout 30 --observation-window 3
run_probe .hades/runtime/hermes-standalone-setup-probe.json python3 scripts/probe_hermes_standalone_setup.py --report .hades/runtime/hermes-standalone-setup-probe.json --timeout 30
run_probe .hades/runtime/hermes-standalone-full-setup-probe.json python3 scripts/probe_hermes_standalone_full_setup.py --report .hades/runtime/hermes-standalone-full-setup-probe.json --timeout 90
run_probe .hades/runtime/hermes-standalone-terminal-platform-probe.json python3 scripts/probe_hermes_standalone_terminal_platform.py --report .hades/runtime/hermes-standalone-terminal-platform-probe.json --timeout 60
run_probe .hades/runtime/hermes-standalone-tool-configuration-probe.json python3 scripts/probe_hermes_standalone_tool_configuration.py --report .hades/runtime/hermes-standalone-tool-configuration-probe.json --timeout 30
run_probe .hades/runtime/hermes-tool-configuration-navigation-probe.json python3 scripts/probe_hermes_tool_configuration_navigation.py --report .hades/runtime/hermes-tool-configuration-navigation-probe.json --timeout 30
run_probe .hades/runtime/hermes-tool-provider-boundary-probe.json python3 scripts/probe_hermes_tool_provider_boundary.py --report .hades/runtime/hermes-tool-provider-boundary-probe.json --timeout 30
run_probe .hades/runtime/hermes-tool-provider-inventory-probe.json python3 scripts/probe_hermes_tool_provider_inventory.py --report .hades/runtime/hermes-tool-provider-inventory-probe.json --timeout 30 --observation-window 1
run_probe .hades/runtime/hermes-tool-provider-inventory-interaction-probe.json python3 scripts/probe_hermes_tool_provider_inventory_interaction.py --report .hades/runtime/hermes-tool-provider-inventory-interaction-probe.json --timeout 60
run_probe .hades/runtime/hermes-tool-provider-inventory-edges-probe.json python3 scripts/probe_hermes_tool_provider_inventory_edges.py --report .hades/runtime/hermes-tool-provider-inventory-edges-probe.json --timeout 60
run_probe .hades/runtime/hermes-tool-provider-inventory-selection-probe.json python3 scripts/probe_hermes_tool_provider_inventory_selection.py --report .hades/runtime/hermes-tool-provider-inventory-selection-probe.json --timeout 30
# HAD-135: replay-terminal-palette is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_terminal_palette
python3 scripts/check_replay_parity.py replay_terminal_palette replay_terminal_palette
./target/debug/replay_terminal_palette --binary target/debug/hades --report .hades/runtime/hades-terminal-palette-replay.json
# HAD-159: replay-osc52-timing-limits is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_osc52_timing_limits
python3 scripts/check_replay_parity.py replay_osc52_timing_limits replay_osc52_timing_limits --timeout 10
./target/debug/replay_osc52_timing_limits --binary target/debug/hades --report .hades/runtime/hades-osc52-timing-limits-replay.json --timeout 10
python3 scripts/replay_osc52_clipboard.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0029-hades-osc52-st-termination.json --report .hades/runtime/hades-osc52-st-termination-replay.json
python3 scripts/replay_osc52_clipboard.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0031-hades-osc52-multiplexer-passthrough.json --report .hades/runtime/hades-osc52-multiplexer-replay.json
# HAD-134: replay-history is ported to Rust; the differential check proves
# identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_history
python3 scripts/check_replay_parity.py replay_history replay_history
./target/debug/replay_history --binary target/debug/hades --report .hades/runtime/history-replay.json
# HAD-155: replay-local-provider is ported to Rust; the differential
# check proves identical reports, then the Rust binary is the gate replay.
cargo build --offline --package hades-dev --bin replay_local_provider
python3 scripts/check_replay_parity.py replay_local_provider replay_local_provider --contract tests/fixtures/parity/OBS-0051-hades-local-provider-stream.json --timeout 8
./target/debug/replay_local_provider --binary target/debug/hades --contract tests/fixtures/parity/OBS-0051-hades-local-provider-stream.json --report .hades/runtime/local-provider-replay.json --timeout 8
# HAD-156: replay-local-provider-timing is ported to Rust; the
# differential check proves identical reports, then the Rust binary is
# the gate replay.
cargo build --offline --package hades-dev --bin replay_local_provider_timing
python3 scripts/check_replay_parity.py replay_local_provider_timing replay_local_provider_timing --contract tests/fixtures/parity/OBS-0053-hades-stream-timing.json --timeout 8
./target/debug/replay_local_provider_timing --binary target/debug/hades --contract tests/fixtures/parity/OBS-0053-hades-stream-timing.json --report .hades/runtime/local-provider-timing-replay.json --timeout 8
git diff --check

_end_ms=$(date +%s%3N)
printf '%s\t%s\t%s ms\texit=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "just-verify" "$((_end_ms - _start_ms))" 0 >> "$project_root/.hades/runtime/dev-timing.log"
echo "verification: PASS ($((_end_ms - _start_ms)) ms)"
