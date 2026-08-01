set shell := ["bash", "-euo", "pipefail", "-c"]

check:
    bash scripts/verify.sh

verify: check

run *args:
    cargo run --locked --package hades-cli -- {{args}}

snapshot:
    cargo run --locked --package hades-cli -- --snapshot

agent command *args:
    python3 scripts/agent/control_plane.py {{command}} {{args}}
