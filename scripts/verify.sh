#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd -- "$script_dir/.." && pwd)"
cd "$project_root"

python3 scripts/agent/control_plane.py validate
cargo fmt --all -- --check
cargo check --workspace --all-targets --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --all-targets --locked
cargo build --locked --package hades-cli
python3 scripts/probe_tui_lifecycle.py --binary target/debug/hades
python3 scripts/differential_replay.py --binary target/debug/hades --report .hades/runtime/differential-replay.json
git diff --check

echo "verification: PASS"
