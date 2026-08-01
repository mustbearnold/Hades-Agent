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
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0038-hermes-model-picker-model-stage.json
python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0039-hades-model-picker-model-stage.json
cargo fmt --all -- --check
cargo check --workspace --all-targets --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --all-targets --locked
cargo build --locked --package hades-cli
python3 scripts/probe_tui_lifecycle.py --binary target/debug/hades
python3 scripts/differential_replay.py --binary target/debug/hades --report .hades/runtime/differential-replay.json
python3 scripts/replay_composer.py --binary target/debug/hades --report .hades/runtime/composer-replay.json
python3 scripts/replay_completion.py --binary target/debug/hades --report .hades/runtime/completion-replay.json
python3 scripts/replay_composer.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0037-hades-unknown-slash-command.json --report .hades/runtime/unknown-command-replay.json
python3 scripts/replay_model_picker.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0039-hades-model-picker-model-stage.json --report .hades/runtime/model-picker-replay.json
python3 scripts/replay_paste.py --binary target/debug/hades --report .hades/runtime/paste-replay.json
python3 scripts/replay_editor.py --binary target/debug/hades --report .hades/runtime/editor-replay.json
python3 scripts/replay_editor_outcomes.py --binary target/debug/hades --report .hades/runtime/editor-outcomes-replay.json
python3 scripts/replay_modified_enter.py --binary target/debug/hades --report .hades/runtime/modified-enter-replay.json
python3 scripts/replay_clipboard.py --binary target/debug/hades --report .hades/runtime/clipboard-replay.json
python3 scripts/replay_clipboard_text.py --binary target/debug/hades --report .hades/runtime/clipboard-text-replay.json
python3 scripts/replay_osc52_clipboard.py --binary target/debug/hades --report .hades/runtime/osc52-clipboard-replay.json
python3 scripts/replay_osc52_clipboard.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0027-hades-osc52-response-boundaries.json --report .hades/runtime/osc52-response-boundaries-replay.json
python3 scripts/probe_hermes_osc52_st_termination.py --report .hades/runtime/hermes-osc52-st-termination-probe.json
python3 scripts/probe_hermes_osc52_multiplexer.py --report .hades/runtime/hermes-osc52-multiplexer-probe.json
python3 scripts/probe_hermes_osc52_timing_limits.py --report .hades/runtime/hermes-osc52-timing-limits-probe.json
python3 scripts/probe_hermes_terminal_palette.py --report .hades/runtime/hermes-terminal-palette-probe.json --timeout 30
python3 scripts/probe_hermes_slash_commands.py --report .hades/runtime/hermes-slash-commands-probe.json --timeout 30
python3 scripts/probe_hermes_model_picker.py --report .hades/runtime/hermes-model-picker-probe.json --timeout 30
python3 scripts/replay_terminal_palette.py --binary target/debug/hades --report .hades/runtime/hades-terminal-palette-replay.json
python3 scripts/replay_osc52_timing_limits.py --binary target/debug/hades --report .hades/runtime/hades-osc52-timing-limits-replay.json
python3 scripts/replay_osc52_clipboard.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0029-hades-osc52-st-termination.json --report .hades/runtime/hades-osc52-st-termination-replay.json
python3 scripts/replay_osc52_clipboard.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0031-hades-osc52-multiplexer-passthrough.json --report .hades/runtime/hades-osc52-multiplexer-replay.json
python3 scripts/replay_history.py --binary target/debug/hades --report .hades/runtime/history-replay.json
git diff --check

echo "verification: PASS"
