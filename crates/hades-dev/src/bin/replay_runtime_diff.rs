//! Diagnostic driver for the replay-runtime parity check: prints cleaned
//! output, marker matches, and exit-status shapes (from real subprocesses)
//! as JSON.

use std::io::Write;
use std::path::Path;
use std::time::Duration;

use hades_dev::replay::{ExitStatus, clean_output, marker_present, spawn, wait_for_exit};
use serde_json::json;

fn main() {
    let raw = b"\x1b[31mred\x1b[0m\r\ntext\x1b]0;title\x07tail";

    let mut markers = serde_json::Map::new();
    let sample = "HadesAgent v0.1.0  Underworld  AvailableTools";
    for marker in ["Hades Agent", "a b", "Underworld", "Available Tools"] {
        markers.insert(marker.to_owned(), json!(marker_present(sample, marker)));
    }

    // Exit-status shapes from real subprocess exits.
    let mut statuses = serde_json::Map::new();
    for (label, code) in [("exit0", "exit 0"), ("exit7", "exit 7"), ("exit3", "exit 3")] {
        let mut child = spawn(Path::new("sh"), &["-c", code]).expect("spawn");
        let mut output = Vec::new();
        let status =
            wait_for_exit(&child.child, &mut output, Duration::from_secs(5)).expect("exit");
        let shape = ExitStatus::describe(status).as_json();
        statuses.insert(label.to_owned(), shape);
        hades_dev::pty::stop(&mut child.child.child);
    }

    let report = json!({
        "clean_output": clean_output(raw),
        "markers": markers,
        "statuses": statuses,
    });
    let mut stdout = std::io::stdout();
    stdout.write_all(serde_json::to_string_pretty(&report).unwrap().as_bytes()).expect("write");
    stdout.flush().expect("flush");
}
