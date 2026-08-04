//! `hades-dev replay-completion` — Rust port of
//! `scripts/replay_completion.py` (HAD-136).
//!
//! Replays the Hades slash-completion contract (OBS-0012) through the
//! shared composer-family machinery in `hades_dev::composer`.

use std::process::ExitCode;

fn main() -> ExitCode {
    hades_dev::composer::run_wrapper(
        "replay-completion",
        "tests/fixtures/parity/OBS-0012-hades-slash-completion.json",
        "had012-completion",
        &[],
    )
}
