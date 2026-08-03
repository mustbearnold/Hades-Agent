//! `hades-dev replay-unconfigured-startup` — Rust port of
//! `scripts/replay_unconfigured_startup.py` (HAD-128).
//!
//! Replays Hades' no-provider startup boundary through a direct PTY:
//! unconfigured markers, model line, absent ready footer and prompt
//! placeholder, raw mode, alternate-screen sequences, and Ctrl+C exit.

use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::Duration;

use hades_dev::replay::{
    ExitStatus, RetainedSlave, clean_output, marker_present, spawn_with_env, terminal_flags,
    wait_for, wait_for_exit,
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

fn run_case(
    binary: &Path,
    name: &str,
    arguments: &[&str],
    timeout: Duration,
) -> Result<Value, String> {
    let mut child =
        spawn_with_env(binary, arguments, &[], &STRIP_ENV).map_err(|e| e.to_string())?;
    let mut output = Vec::new();
    let mut reaped = false;
    let slave_path = child.slave_path.clone();

    let result = (|| -> Result<Value, String> {
        wait_for(
            &child.child,
            &mut output,
            &format!("{name}: startup"),
            |text| STARTUP_MARKERS.iter().all(|marker| marker_present(text, marker)),
            timeout,
        )?;

        let startup_text = clean_output(&output);
        if marker_present(&startup_text, "─ ready │") {
            return Err(format!("{name}: unconfigured startup rendered a ready footer"));
        }
        if startup_text.contains("<prompt-placeholder>") {
            return Err(format!("{name}: unconfigured startup rendered a prompt placeholder"));
        }
        if marker_present(&startup_text, "mock model")
            || marker_present(&startup_text, "mock-model")
        {
            return Err(format!("{name}: unconfigured startup rendered the configured mock model"));
        }

        let slave = RetainedSlave::retain(&slave_path).map_err(|e| e.to_string())?;
        let startup_flags = terminal_flags(&slave).map_err(|e| e.to_string())?;
        if startup_flags.canonical || startup_flags.echo {
            return Err(format!("{name}: startup did not enter raw mode: {startup_flags:?}"));
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|e| e.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 0 }) {
            return Err(format!("{name}: unexpected exit status: {exit_status:?}"));
        }

        let raw_output: &[u8] = &output;
        if !find_sequence(raw_output, b"\x1b[?1049h") {
            return Err(format!("{name}: alternate-screen enter sequence was not observed"));
        }
        if !find_sequence(raw_output, b"\x1b[?1049l") {
            return Err(format!("{name}: alternate-screen leave sequence was not observed"));
        }

        let cleanup_flags = terminal_flags(&slave).map_err(|e| e.to_string())?;
        if !cleanup_flags.canonical || !cleanup_flags.echo {
            return Err(format!("{name}: terminal was not restored: {cleanup_flags:?}"));
        }

        Ok(json!({
            "case": name,
            "arguments": arguments,
            "startup": {
                "landmarks": STARTUP_MARKERS,
                "model_provider": "glm-5.2 · Hades",
                "status": "starting agent",
                "ready_footer": false,
                "prompt_placeholder": false,
                "provider_endpoint": "absent",
                "raw_mode": {
                    "canonical": startup_flags.canonical,
                    "echo": startup_flags.echo,
                },
            },
            "exit": exit_status.as_json(),
            "cleanup": {
                "input": "Ctrl+C",
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
        "probe": "hades-unconfigured-startup",
        "binary": "<hades-binary>",
        "dimensions": {"columns": 120, "rows": 40},
        "cases": [],
    });
    if !binary.is_file() {
        report["passed"] = json!(false);
        report["error"] = json!("Hades binary not found");
        return write_report(&report, report_path.as_deref(), 2);
    }

    match (
        run_case(&binary, "default-tui", &[], timeout),
        run_case(&binary, "explicit-tui", &["tui"], timeout),
    ) {
        (Ok(default_case), Ok(explicit_case)) => {
            report["cases"] = json!([default_case, explicit_case]);
            report["passed"] = json!(true);
            write_report(&report, report_path.as_deref(), 0)
        }
        (Err(error), _) | (_, Err(error)) => {
            report["passed"] = json!(false);
            report["error"] = json!(error);
            write_report(&report, report_path.as_deref(), 1)
        }
    }
}
