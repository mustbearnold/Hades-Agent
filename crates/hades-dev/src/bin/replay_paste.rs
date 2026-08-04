//! `hades-dev replay-paste` — Rust port of
//! `scripts/replay_paste.py` (HAD-138).
//!
//! Replays the Hades bracketed-paste contract (OBS-0013) through the
//! shared composer-family machinery in `hades_dev::composer`.

use std::process::ExitCode;

fn main() -> ExitCode {
    hades_dev::composer::run_wrapper(
        "replay-paste",
        "tests/fixtures/parity/OBS-0013-hades-bracketed-paste.json",
        "had013-paste",
        &[],
    )
}
