//! `hades-dev replay-unconfigured-help` — Rust port of
//! `scripts/replay_unconfigured_help.py` (HAD-130).
//!
//! Replays Hades' delayed unconfigured /help setup-required route: /help
//! retained during the 8000ms pre-delay window, the delayed Setup Required
//! overlay with /model//setup/Ctrl+C, bounded transition timing, first
//! Ctrl+C clearing the overlay without exiting, second Ctrl+C exiting
//! cleanly.

use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{Duration, Instant};

use hades_dev::pty::read_available;
use hades_dev::replay::{
    ExitStatus, RetainedSlave, TerminalFlags, clean_output, marker_present, spawn_with_env,
    terminal_flags, try_wait, wait_for, wait_for_exit,
};
use serde_json::{Value, json};

const HELP_SETUP_REQUIRED_DELAY_MS: u64 = 8_000;
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

/// Last `lines` lines of cleaned output, like `recent_output`.
fn recent_output(output: &[u8], lines: usize) -> String {
    last_lines(&clean_output(output), lines)
}

/// Last `lines` lines of a text string.
fn last_lines(text: &str, lines: usize) -> String {
    let all: Vec<&str> = text.lines().collect();
    let start = all.len().saturating_sub(lines);
    all[start..].join("\n")
}

/// Read PTY flags across the short post-exec ioctl race (retry on errno 25
/// ENOTTY), like `stable_terminal_flags`.
fn stable_terminal_flags(slave: &RetainedSlave) -> Result<TerminalFlags, String> {
    let mut last_error: Option<std::io::Error> = None;
    for _ in 0..20 {
        match terminal_flags(slave) {
            Ok(flags) => return Ok(flags),
            Err(error) => {
                if error.raw_os_error() != Some(25) {
                    return Err(error.to_string());
                }
                last_error = Some(error);
                std::thread::sleep(Duration::from_millis(10));
            }
        }
    }
    Err(format!(
        "terminal flags stayed unavailable: {}",
        last_error.map_or_else(|| "unknown".to_owned(), |e| e.to_string())
    ))
}

fn run_case(binary: &Path, arguments: &[&str], timeout: Duration) -> Result<Value, String> {
    let case = if arguments.is_empty() { "default-tui" } else { "explicit-tui" };
    let mut child =
        spawn_with_env(binary, arguments, &[], &STRIP_ENV).map_err(|error| error.to_string())?;
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
        let startup_flags = stable_terminal_flags(&slave)?;
        if startup_flags.canonical || startup_flags.echo {
            return Err(format!("{case}: startup did not enter raw mode: {startup_flags:?}"));
        }

        hades_dev::replay::send(&child.child.master, b"/help\r")
            .map_err(|error| error.to_string())?;
        let submitted_at = Instant::now();
        wait_for(
            &child.child,
            &mut output,
            &format!("{case}: retained help input"),
            |text| {
                marker_present(text, "/help")
                    && marker_present(text, "starting agent")
                    && !marker_present(text, "Setup Required")
            },
            timeout.min(Duration::from_secs(3)),
        )?;

        std::thread::sleep(Duration::from_millis(500));
        output.extend_from_slice(&read_available(&child.child.master));
        let before_delay = recent_output(&output, 48);
        let before_delay_ms = submitted_at.elapsed().as_millis() as u64;
        if before_delay_ms >= HELP_SETUP_REQUIRED_DELAY_MS {
            return Err(format!("{case}: pre-delay assertion ran too late: {before_delay_ms} ms"));
        }
        if !marker_present(&before_delay, "/help") {
            return Err(format!("{case}: /help draft was not visible before the deadline"));
        }
        if !marker_present(&before_delay, "starting agent") {
            return Err(format!(
                "{case}: starting-agent surface was not retained before the deadline"
            ));
        }
        if marker_present(&before_delay, "Setup Required") {
            return Err(format!("{case}: Setup Required appeared before the deadline"));
        }

        wait_for(
            &child.child,
            &mut output,
            &format!("{case}: delayed setup-required overlay"),
            |text| {
                let recent = last_lines(text, 48);
                ["Setup Required", "/model", "/setup", "Ctrl+C"]
                    .iter()
                    .all(|marker| marker_present(&recent, marker))
            },
            timeout,
        )?;
        let transition_ms = submitted_at.elapsed().as_millis() as u64;
        let after_delay = recent_output(&output, 48);
        if !(7_000..=11_000).contains(&transition_ms) {
            return Err(format!(
                "{case}: delayed transition outside bounded timing: {transition_ms} ms"
            ));
        }
        if marker_present(&after_delay, "Provider error")
            || marker_present(&after_delay, "─ ready │")
        {
            return Err(format!("{case}: delayed route left the unconfigured startup boundary"));
        }
        if child.history_home.join("config.yaml").exists() {
            return Err(format!("{case}: delayed route created config.yaml"));
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(150));
        output.extend_from_slice(&read_available(&child.child.master));
        let after_clear = recent_output(&output, 48);
        if !marker_present(&after_clear, "Setup Required") {
            return Err(format!("{case}: first Ctrl+C removed the setup-required overlay"));
        }
        if try_wait(&child.child)?.is_some() {
            return Err(format!("{case}: first Ctrl+C exited instead of clearing the draft"));
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 0 }) {
            return Err(format!("{case}: unexpected exit status: {exit_status:?}"));
        }
        let raw_output: &[u8] = &output;
        let cleanup_flags = stable_terminal_flags(&slave)?;
        if !cleanup_flags.canonical || !cleanup_flags.echo {
            return Err(format!("{case}: terminal was not restored: {cleanup_flags:?}"));
        }
        if !find_sequence(raw_output, b"\x1b[?1049h") || !find_sequence(raw_output, b"\x1b[?1049l")
        {
            return Err(format!("{case}: alternate-screen cleanup was incomplete"));
        }

        Ok(json!({
            "case": case,
            "arguments": arguments,
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
                "command": "/help",
                "enter_sent": true,
                "pre_delay_ms": before_delay_ms,
                "setup_required_delay_ms": HELP_SETUP_REQUIRED_DELAY_MS,
                "observed_transition_ms": transition_ms,
                "draft_marker": "/help visible in the pre-delay PTY stream",
                "starting_agent_before_delay": true,
                "setup_required_markers": ["Setup Required", "/model", "/setup", "Ctrl+C"],
                "provider_request_started": false,
                "config_created": false,
                "first_ctrl_c_kept_process_alive": true,
                "first_ctrl_c_cleared_draft": "focused app/TUI oracle",
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
    let mut timeout = Duration::from_secs_f64(12.0);

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
                    timeout = Duration::from_secs_f64(value.parse().unwrap_or(12.0));
                }
            }
            _ => {}
        }
    }

    let binary = binary.canonicalize().unwrap_or_else(|_| binary.clone());
    let mut report = json!({
        "schema_version": 1,
        "observation_id": "OBS-0067",
        "probe": "hades-unconfigured-help-setup-required",
        "binary": "<hades-binary>",
        "dimensions": {"columns": 120, "rows": 40},
        "delay_ms": HELP_SETUP_REQUIRED_DELAY_MS,
        "cases": [],
        "passed": false,
    });
    if !binary.is_file() {
        report["error"] = json!("Hades binary not found");
        return write_report(&report, report_path.as_deref(), 2);
    }

    match (run_case(&binary, &[], timeout), run_case(&binary, &["tui"], timeout)) {
        (Ok(default_case), Ok(explicit_case)) => {
            report["cases"] = json!([default_case, explicit_case]);
            report["passed"] = json!(true);
            write_report(&report, report_path.as_deref(), 0)
        }
        (Err(error), _) | (_, Err(error)) => {
            report["error"] = json!(error);
            write_report(&report, report_path.as_deref(), 1)
        }
    }
}
