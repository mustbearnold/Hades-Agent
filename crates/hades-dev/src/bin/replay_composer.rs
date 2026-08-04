//! `hades-dev replay-composer` — Rust port of
//! `scripts/replay_composer.py` (HAD-133).
//!
//! Replays the implemented Hades composer contract in isolated 120x40 tmux
//! sessions (OBS-0011 editing/history/multiline, OBS-0037 unknown slash
//! command). The machinery lives in `hades_dev::composer`; this binary is
//! the composer replay's own invocation.

use std::process::ExitCode;

fn main() -> ExitCode {
    hades_dev::composer::run_wrapper(
        "replay-composer",
        "tests/fixtures/parity/OBS-0011-hades-composer-editing.json",
        "had011-composer",
        &[],
    )
}
