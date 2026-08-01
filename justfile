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

validate-reference:
    python3 scripts/validate_reference_fixture.py

agent command *args:
    python3 scripts/agent/control_plane.py {{command}} {{args}}
