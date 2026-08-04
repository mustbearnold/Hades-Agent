//! `hades-dev replay-setup-wizard` — Rust port of
//! `scripts/replay_setup_wizard.py` (HAD-140).
//!
//! Replays the bounded Hades setup-wizard contract (OBS-0041 cancel path)
//! in an isolated tmux PTY via `hades_dev::setup`.

use std::process::ExitCode;

fn main() -> ExitCode {
    hades_dev::setup::run_wrapper("replay-setup-wizard", "had042-setup")
}
