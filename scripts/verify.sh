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
cargo fmt --all -- --check
cargo check --workspace --all-targets --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --all-targets --locked
cargo build --locked --package hades-cli
python3 scripts/probe_tui_lifecycle.py --binary target/debug/hades
python3 scripts/differential_replay.py --binary target/debug/hades --report .hades/runtime/differential-replay.json
python3 scripts/replay_composer.py --binary target/debug/hades --report .hades/runtime/composer-replay.json
python3 scripts/replay_completion.py --binary target/debug/hades --report .hades/runtime/completion-replay.json
python3 scripts/replay_paste.py --binary target/debug/hades --report .hades/runtime/paste-replay.json
python3 scripts/replay_editor.py --binary target/debug/hades --report .hades/runtime/editor-replay.json
python3 scripts/replay_editor_outcomes.py --binary target/debug/hades --report .hades/runtime/editor-outcomes-replay.json
python3 scripts/replay_modified_enter.py --binary target/debug/hades --report .hades/runtime/modified-enter-replay.json
python3 scripts/replay_clipboard.py --binary target/debug/hades --report .hades/runtime/clipboard-replay.json
python3 scripts/replay_clipboard_text.py --binary target/debug/hades --report .hades/runtime/clipboard-text-replay.json
python3 scripts/replay_osc52_clipboard.py --binary target/debug/hades --report .hades/runtime/osc52-clipboard-replay.json
python3 scripts/replay_history.py --binary target/debug/hades --report .hades/runtime/history-replay.json
git diff --check

echo "verification: PASS"
