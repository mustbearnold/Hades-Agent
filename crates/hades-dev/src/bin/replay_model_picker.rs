//! `hades-dev replay-model-picker` — Rust port of
//! `scripts/replay_model_picker.py` (HAD-146).
//!
//! Replays the bounded Hades model-picker contract (OBS-0039) in an
//! isolated tmux PTY via `hades_dev::setup` (fixed loopback provider base
//! URL, small key set including Escape, sanitized `<hades-binary>` report
//! field).

use std::process::ExitCode;

fn main() -> ExitCode {
    hades_dev::setup::run_wrapper("replay-model-picker", "had040-model")
}
