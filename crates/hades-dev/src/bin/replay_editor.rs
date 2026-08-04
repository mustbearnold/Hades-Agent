//! `hades-dev replay-editor` — Rust port of
//! `scripts/replay_editor.py` (HAD-139).
//!
//! Replays the Hades editor-handoff contract (OBS-0014) through the
//! shared composer-family machinery in `hades_dev::composer`, with the
//! deterministic `EDITOR=/bin/true` the Python replay injects (an editor
//! that exits 0 immediately, submitting the unchanged draft).

use std::process::ExitCode;

fn main() -> ExitCode {
    hades_dev::composer::run_wrapper(
        "replay-editor",
        "tests/fixtures/parity/OBS-0014-hades-editor-handoff.json",
        "had014-editor",
        &[("EDITOR", "/bin/true")],
    )
}
