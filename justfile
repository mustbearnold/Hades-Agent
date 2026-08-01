set shell := ["bash", "-euo", "pipefail", "-c"]

check:
    bash scripts/verify.sh

verify: check

run *args:
    cargo run --locked --package hades-cli -- {{args}}

install-user:
    cargo build --locked --release --package hades-cli
    bash scripts/install_user_launcher.sh

snapshot:
    cargo run --locked --package hades-cli -- --snapshot

probe-lifecycle:
    cargo build --locked --package hades-cli
    python3 scripts/probe_tui_lifecycle.py --binary target/debug/hades

replay-cli-launch:
    cargo build --locked --package hades-cli
    python3 scripts/replay_cli_launch.py --binary target/debug/hades --report .hades/runtime/cli-launch-replay.json

replay-differential:
    cargo build --locked --package hades-cli
    python3 scripts/differential_replay.py --binary target/debug/hades --report .hades/runtime/differential-replay.json

replay-composer:
    cargo build --locked --package hades-cli
    python3 scripts/replay_composer.py --binary target/debug/hades --report .hades/runtime/composer-replay.json

replay-completion:
    cargo build --locked --package hades-cli
    python3 scripts/replay_completion.py --binary target/debug/hades --report .hades/runtime/completion-replay.json

replay-unknown-command:
    cargo build --locked --package hades-cli
    python3 scripts/replay_composer.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0037-hades-unknown-slash-command.json --report .hades/runtime/unknown-command-replay.json

replay-model-picker:
    cargo build --locked --package hades-cli
    python3 scripts/replay_model_picker.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0039-hades-model-picker-model-stage.json --report .hades/runtime/model-picker-replay.json

replay-setup-wizard:
    cargo build --locked --package hades-cli
    python3 scripts/replay_setup_wizard.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0041-hades-setup-wizard-cancel.json --report .hades/runtime/setup-wizard-replay.json

replay-paste:
    cargo build --locked --package hades-cli
    python3 scripts/replay_paste.py --binary target/debug/hades --report .hades/runtime/paste-replay.json

replay-editor:
    cargo build --locked --package hades-cli
    python3 scripts/replay_editor.py --binary target/debug/hades --report .hades/runtime/editor-replay.json

replay-editor-outcomes:
    cargo build --locked --package hades-cli
    python3 scripts/replay_editor_outcomes.py --binary target/debug/hades --report .hades/runtime/editor-outcomes-replay.json

replay-modified-enter:
    cargo build --locked --package hades-cli
    python3 scripts/replay_modified_enter.py --binary target/debug/hades --report .hades/runtime/modified-enter-replay.json

replay-clipboard:
    cargo build --locked --package hades-cli
    python3 scripts/replay_clipboard.py --binary target/debug/hades --report .hades/runtime/clipboard-replay.json

replay-clipboard-text:
    cargo build --locked --package hades-cli
    python3 scripts/replay_clipboard_text.py --binary target/debug/hades --report .hades/runtime/clipboard-text-replay.json

replay-osc52-clipboard:
    cargo build --locked --package hades-cli
    python3 scripts/replay_osc52_clipboard.py --binary target/debug/hades --report .hades/runtime/osc52-clipboard-replay.json

replay-osc52-response-boundaries:
    cargo build --locked --package hades-cli
    python3 scripts/replay_osc52_clipboard.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0027-hades-osc52-response-boundaries.json --report .hades/runtime/osc52-response-boundaries-replay.json

probe-osc52-st-termination:
    python3 scripts/probe_hermes_osc52_st_termination.py --report .hades/runtime/hermes-osc52-st-termination-probe.json

probe-osc52-multiplexer:
    python3 scripts/probe_hermes_osc52_multiplexer.py --report .hades/runtime/hermes-osc52-multiplexer-probe.json

probe-osc52-timing-limits:
    python3 scripts/probe_hermes_osc52_timing_limits.py --report .hades/runtime/hermes-osc52-timing-limits-probe.json

probe-terminal-palette:
    python3 scripts/probe_hermes_terminal_palette.py --report .hades/runtime/hermes-terminal-palette-probe.json --timeout 30

probe-slash-commands:
    python3 scripts/probe_hermes_slash_commands.py --report .hades/runtime/hermes-slash-commands-probe.json --timeout 30

probe-model-picker:
    python3 scripts/probe_hermes_model_picker.py --report .hades/runtime/hermes-model-picker-probe.json --timeout 30

probe-setup-wizard:
    python3 scripts/probe_hermes_setup_wizard.py --report .hades/runtime/hermes-setup-wizard-probe.json --timeout 30

probe-full-setup:
    python3 scripts/probe_hermes_full_setup.py --report .hades/runtime/hermes-full-setup-probe.json --timeout 30

replay-terminal-palette:
    cargo build --locked --package hades-cli
    python3 scripts/replay_terminal_palette.py --binary target/debug/hades --report .hades/runtime/hades-terminal-palette-replay.json

replay-osc52-timing-limits:
    cargo build --locked --package hades-cli
    python3 scripts/replay_osc52_timing_limits.py --binary target/debug/hades --report .hades/runtime/hades-osc52-timing-limits-replay.json

replay-osc52-st-termination:
    cargo build --locked --package hades-cli
    python3 scripts/replay_osc52_clipboard.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0029-hades-osc52-st-termination.json --report .hades/runtime/hades-osc52-st-termination-replay.json

replay-osc52-multiplexer:
    cargo build --locked --package hades-cli
    python3 scripts/replay_osc52_clipboard.py --binary target/debug/hades --contract tests/fixtures/parity/OBS-0031-hades-osc52-multiplexer-passthrough.json --report .hades/runtime/hades-osc52-multiplexer-replay.json

replay-history:
    cargo build --locked --package hades-cli
    python3 scripts/replay_history.py --binary target/debug/hades --report .hades/runtime/history-replay.json

validate-reference:
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
    python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0040-hermes-setup-wizard-cancel.json
    python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0041-hades-setup-wizard-cancel.json
    python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0042-hermes-full-setup-continuation.json

agent command *args:
    python3 scripts/agent/control_plane.py {{command}} {{args}}
