//! `hades-dev replay-setup-terminal-backend` — Rust port of
//! `scripts/replay_setup_terminal_backend.py` (HAD-143).
//!
//! Replays the bounded model-default terminal-backend (OBS-0049) and
//! setup platform-picker (OBS-0057) contracts in isolated tmux PTYs via
//! `hades_dev::setup`.

use std::process::ExitCode;

fn main() -> ExitCode {
    hades_dev::setup::run_wrapper("replay-setup-terminal-backend", "had051-terminal-backend")
}
