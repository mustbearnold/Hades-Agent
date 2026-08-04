//! `hades-dev replay-setup-provider-menu` — Rust port of
//! `scripts/replay_setup_provider_menu.py` (HAD-141).
//!
//! Replays the bounded Hades Full setup provider-menu contract (OBS-0045)
//! in an isolated tmux PTY via `hades_dev::setup`.

use std::process::ExitCode;

fn main() -> ExitCode {
    // The Python replay emits this exact command name (a quirk of
    // replay_setup_provider_menu.py); the report must match byte-for-byte.
    hades_dev::setup::run_wrapper("replay-setup-provider", "had046-provider")
}
