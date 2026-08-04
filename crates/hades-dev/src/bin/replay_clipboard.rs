//! `hades-dev replay-clipboard` — Rust port of
//! `scripts/replay_clipboard.py` (HAD-137).
//!
//! Replays the Hades empty-clipboard contract (OBS-0015) through the
//! shared composer-family machinery in `hades_dev::composer`.

use std::process::ExitCode;

fn main() -> ExitCode {
    hades_dev::composer::run_wrapper(
        "replay-clipboard",
        "tests/fixtures/parity/OBS-0015-hades-empty-clipboard.json",
        "had015-clipboard",
        &[],
    )
}
