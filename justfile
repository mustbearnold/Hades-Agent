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

agent command *args:
    python3 scripts/agent/control_plane.py {{command}} {{args}}
