//! `hades-dev replay-setup-provider-model-prompt` — Rust port of
//! `scripts/replay_setup_provider_model_prompt.py` (HAD-142).
//!
//! Replays the bounded provider-selection model-prompt contract (OBS-0047)
//! in an isolated tmux PTY via `hades_dev::setup`.

use std::process::ExitCode;

fn main() -> ExitCode {
    hades_dev::setup::run_wrapper("replay-setup-provider-model-prompt", "had048-model-prompt")
}
