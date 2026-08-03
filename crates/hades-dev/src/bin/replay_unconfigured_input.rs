//! `hades-dev replay-unconfigured-input` — Rust port of
//! `scripts/replay_unconfigured_input.py` (HAD-129).
//!
//! Replays queued input during unconfigured startup: draft visibility with
//! the composer marker, first Ctrl+C clearing the draft while keeping the
//! process alive, second Ctrl+C exiting cleanly, and the empty-startup
//! exit case.

use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::Duration;

use hades_dev::pty::read_available;
use hades_dev::replay::{
    ExitStatus, RetainedSlave, clean_output, marker_present, spawn_with_env, terminal_flags,
    try_wait, wait_for, wait_for_exit,
};
use serde_json::{Value, json};

const STARTUP_MARKERS: [&str; 6] = [
    "Hades Agent",
    "Underworld",
    "Available Tools",
    "Available Skills",
    "glm-5.2 · Hades",
    "starting agent",
];
const STRIP_ENV: [&str; 5] = [
    "HADES_PROVIDER_BASE_URL",
    "HADES_PROVIDER_API_KEY",
    "HADES_MODEL",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
];
const INPUT_TEXT: &str = "queued hello";

fn run_input_case(binary: &Path, timeout: Duration) -> Result<Value, String> {
    let case = "unconfigured-input";
    let mut child =
        spawn_with_env(binary, &[], &[], &STRIP_ENV).map_err(|error| error.to_string())?;
    let mut output = Vec::new();
    let mut reaped = false;
    let slave_path = child.slave_path.clone();

    let result = (|| -> Result<Value, String> {
        wait_for(
            &child.child,
            &mut output,
            &format!("{case}: startup"),
            |text| STARTUP_MARKERS.iter().all(|marker| marker_present(text, marker)),
            timeout,
        )?;

        let slave = RetainedSlave::retain(&slave_path).map_err(|error| error.to_string())?;
        let startup_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if startup_flags.canonical || startup_flags.echo {
            return Err("unconfigured input startup did not enter raw mode".to_owned());
        }

        hades_dev::replay::send(&child.child.master, format!("{INPUT_TEXT}\r").as_bytes())
            .map_err(|error| error.to_string())?;
        wait_for(
            &child.child,
            &mut output,
            &format!("{case}: draft"),
            |text| text.contains(INPUT_TEXT),
            timeout,
        )?;

        std::thread::sleep(Duration::from_millis(150));
        output.extend_from_slice(&read_available(&child.child.master));
        let raw_with_draft = clean_output(&output);
        let draft_tail = tail_chars(&raw_with_draft, 1200);
        if !marker_present(&draft_tail, "❯ queued hello") {
            return Err("unconfigured input did not render the Hermes composer marker".to_owned());
        }
        if !marker_present(&raw_with_draft, "starting agent")
            || marker_present(&draft_tail, "─ ready │")
        {
            return Err("unconfigured input changed the startup boundary".to_owned());
        }
        if marker_present(&draft_tail, "Provider error") {
            return Err("unconfigured input rendered a provider error".to_owned());
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(150));
        output.extend_from_slice(&read_available(&child.child.master));
        let raw_after_clear = clean_output(&output);
        let after_clear_tail = tail_chars(&raw_after_clear, 1200);
        if !marker_present(&after_clear_tail, "starting agent") {
            return Err("first Ctrl+C left the unconfigured startup surface".to_owned());
        }
        if try_wait(&child.child)?.is_some() {
            return Err("first Ctrl+C exited instead of clearing the unconfigured draft".to_owned());
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 0 }) {
            return Err(format!("unexpected exit status: {exit_status:?}"));
        }
        let raw_output: &[u8] = &output;
        let cleanup_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if !cleanup_flags.canonical || !cleanup_flags.echo {
            return Err(format!("terminal was not restored: {cleanup_flags:?}"));
        }
        if !find_sequence(raw_output, b"\x1b[?1049h") || !find_sequence(raw_output, b"\x1b[?1049l")
        {
            return Err("alternate-screen cleanup was incomplete".to_owned());
        }
        Ok(json!({
            "case": case,
            "arguments": [],
            "status": "passed",
            "startup": {
                "markers": STARTUP_MARKERS,
                "raw_mode": {
                    "canonical": startup_flags.canonical,
                    "echo": startup_flags.echo,
                },
                "provider_endpoint": "absent",
            },
            "input": {
                "text": INPUT_TEXT,
                "enter_sent": true,
                "draft_marker": "❯ queued hello",
                "starting_agent_persisted": true,
                "ready_footer": false,
                "provider_error": false,
                "provider_request_started": false,
                "first_ctrl_c_kept_process_alive": true,
                "draft_clear_oracle": "focused app/TUI tests",
            },
            "cleanup": {
                "ctrl_c_presses": 2,
                "exit": exit_status.as_json(),
                "alternate_screen_left": true,
                "terminal_flags": {
                    "canonical": cleanup_flags.canonical,
                    "echo": cleanup_flags.echo,
                },
            },
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child.child);
    }
    let _ = std::fs::remove_dir_all(&child.history_home);
    result
}

fn run_empty_case(binary: &Path, timeout: Duration) -> Result<Value, String> {
    let case = "unconfigured-empty-exit";
    let mut child =
        spawn_with_env(binary, &["tui"], &[], &STRIP_ENV).map_err(|error| error.to_string())?;
    let mut output = Vec::new();
    let mut reaped = false;
    let slave_path = child.slave_path.clone();

    let result = (|| -> Result<Value, String> {
        wait_for(
            &child.child,
            &mut output,
            &format!("{case}: startup"),
            |text| marker_present(text, "Hades Agent") && marker_present(text, "starting agent"),
            timeout,
        )?;

        let slave = RetainedSlave::retain(&slave_path).map_err(|error| error.to_string())?;
        let startup_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 0 }) {
            return Err(format!("empty startup had unexpected exit status: {exit_status:?}"));
        }
        let raw_output: &[u8] = &output;
        let cleanup_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if !cleanup_flags.canonical || !cleanup_flags.echo {
            return Err(format!("empty startup did not restore terminal: {cleanup_flags:?}"));
        }
        if !find_sequence(raw_output, b"\x1b[?1049l") {
            return Err("empty startup did not leave the alternate screen".to_owned());
        }
        Ok(json!({
            "case": case,
            "arguments": ["tui"],
            "status": "passed",
            "startup": {
                "status": "starting agent",
                "raw_mode": {
                    "canonical": startup_flags.canonical,
                    "echo": startup_flags.echo,
                },
            },
            "cleanup": {
                "ctrl_c_presses": 1,
                "exit": exit_status.as_json(),
                "alternate_screen_left": true,
                "terminal_flags": {
                    "canonical": cleanup_flags.canonical,
                    "echo": cleanup_flags.echo,
                },
            },
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child.child);
    }
    let _ = std::fs::remove_dir_all(&child.history_home);
    result
}

fn tail_chars(text: &str, count: usize) -> String {
    let chars: Vec<char> = text.chars().collect();
    let start = chars.len().saturating_sub(count);
    chars[start..].iter().collect()
}

fn find_sequence(haystack: &[u8], needle: &[u8]) -> bool {
    haystack.windows(needle.len()).any(|window| window == needle)
}

fn write_report(report: &Value, path: Option<&Path>, status: u8) -> ExitCode {
    let text = serde_json::to_string_pretty(report).expect("serialize report");
    if let Some(path) = path {
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let mut file = std::fs::File::create(path).expect("create report");
        use std::io::Write;
        let _ = file.write_all(text.as_bytes());
        let _ = file.write_all(b"\n");
    }
    println!("{text}");
    if status == 0 { ExitCode::SUCCESS } else { ExitCode::from(status) }
}

fn main() -> ExitCode {
    let mut args = std::env::args().skip(1);
    let mut binary = PathBuf::from("target/debug/hades");
    let mut report_path: Option<PathBuf> = None;
    let mut timeout = Duration::from_secs_f64(5.0);

    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--binary" => {
                if let Some(value) = args.next() {
                    binary = PathBuf::from(value);
                }
            }
            "--report" => {
                if let Some(value) = args.next() {
                    report_path = Some(PathBuf::from(value));
                }
            }
            "--timeout" => {
                if let Some(value) = args.next() {
                    timeout = Duration::from_secs_f64(value.parse().unwrap_or(5.0));
                }
            }
            _ => {}
        }
    }

    let binary = binary.canonicalize().unwrap_or_else(|_| binary.clone());
    let mut report = json!({
        "schema_version": 1,
        "probe": "hades-unconfigured-input",
        "binary": "<hades-binary>",
        "dimensions": {"columns": 120, "rows": 40},
        "cases": [],
        "passed": false,
    });
    if !binary.is_file() {
        report["error"] = json!("Hades binary not found");
        return write_report(&report, report_path.as_deref(), 2);
    }

    match (run_input_case(&binary, timeout), run_empty_case(&binary, timeout)) {
        (Ok(input_case), Ok(empty_case)) => {
            report["cases"] = json!([input_case, empty_case]);
            report["passed"] = json!(true);
            write_report(&report, report_path.as_deref(), 0)
        }
        (Err(error), _) | (_, Err(error)) => {
            report["error"] = json!(error);
            write_report(&report, report_path.as_deref(), 1)
        }
    }
}
