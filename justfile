set shell := ["bash", "-euo", "pipefail", "-c"]

check:
    bash scripts/verify.sh

verify: check

run *args:
    cargo run --locked --package hades-cli -- {{args}}

snapshot:
    cargo run --locked --package hades-cli -- --snapshot

probe-lifecycle:
    cargo build --locked --package hades-cli
    python3 scripts/probe_tui_lifecycle.py --binary target/debug/hades

replay-differential:
    cargo build --locked --package hades-cli
    python3 scripts/differential_replay.py --binary target/debug/hades --report .hades/runtime/differential-replay.json

replay-composer:
    cargo build --locked --package hades-cli
    python3 scripts/replay_composer.py --binary target/debug/hades --report .hades/runtime/composer-replay.json

replay-completion:
    cargo build --locked --package hades-cli
    python3 scripts/replay_completion.py --binary target/debug/hades --report .hades/runtime/completion-replay.json

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

replay-history:
    cargo build --locked --package hades-cli
    python3 scripts/replay_history.py --binary target/debug/hades --report .hades/runtime/history-replay.json

validate-reference:
    python3 scripts/validate_reference_fixture.py
    python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0016-hermes-input-history-persistence.json
    python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0018-hermes-editor-outcomes.json
    python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0020-hermes-modified-enter.json
    python3 scripts/validate_reference_fixture.py tests/fixtures/parity/OBS-0021-hades-modified-enter.json

agent command *args:
    python3 scripts/agent/control_plane.py {{command}} {{args}}
