//! `hades-dev replay-standalone-setup` — Rust port of
//! `scripts/replay_standalone_setup.py` (HAD-162).
//!
//! Replays the Hades standalone setup entry and bounded cancellation
//! boundary in an isolated direct PTY: the `setup` subcommand renders the
//! wizard surface in raw mode, Escape drops to the numbered fallback and
//! restores canonical/echo flags, Ctrl+C exits with code 1 and restores
//! the terminal, and no provider behavior (and no config.yaml) appears.
//!
//! Marker waits are raw (`wait_for`), mirroring the Python original: the
//! wizard renders its title box and then the form layout OVERWRITES the
//! title rows, so the settled rendered screen never contains the title
//! markers — a rendered-screen wait can never succeed here. The wizard
//! surface has no animated logo, so the raw byte stream keeps markers
//! contiguous.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::Duration;

use hades_dev::replay::{
    ExitStatus, ReplayChild, RetainedSlave, clean_output, marker_present, spawn_with_env,
    terminal_flags, wait_for, wait_for_exit,
};
use serde_json::{Value, json};

const COLUMNS: u16 = 120;
const ROWS: u16 = 40;
const INITIAL_MARKERS: [&str; 8] = [
    "Hermes Agent Setup Wizard",
    "Let's configure your Hermes Agent installation.",
    "Press Ctrl+C at any time to exit.",
    "How would you like to set up Hermes?",
    "Quick Setup (Nous Portal)",
    "Full setup",
    "Blank Slate",
    "ESC cancel",
];
const FALLBACK_MARKERS: [&str; 7] = [
    "How would you like to set up Hermes?",
    "Quick Setup (Nous Portal)",
    "Full setup",
    "Blank Slate",
    "Enter for default (1)",
    "Ctrl+C to exit",
    "Select [1-3] (1):",
];
/// Provider/credential vars the Python replay pops from the child env.
const STRIP_ENV: [&str; 5] = [
    "HADES_PROVIDER_BASE_URL",
    "HADES_PROVIDER_API_KEY",
    "HADES_MODEL",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
];

/// Spawn `binary setup` on a fresh 120x40 PTY with an isolated home,
/// mirroring `spawn_setup` (the Python child also sets the window size
/// and TERM/COLUMNS/LINES, which `spawn_with_env` already applies).
fn spawn_setup(binary: &Path, home: &Path) -> Result<ReplayChild, String> {
    let home_str = home.to_str().ok_or_else(|| "non-utf8 home".to_owned())?;
    let extra: [(&str, &str); 2] = [("HOME", home_str), ("HERMES_HOME", home_str)];
    spawn_with_env(binary, &["setup"], &extra, &STRIP_ENV).map_err(|error| error.to_string())
}

fn run_case(binary: &Path, timeout: Duration) -> Result<Value, String> {
    let home =
        std::env::temp_dir().join(format!("hades-standalone-setup-home-{}", std::process::id()));
    let _ = fs::create_dir_all(&home);
    let mut child = spawn_setup(binary, &home)?;
    let mut output = Vec::new();
    let slave = RetainedSlave::retain(&child.slave_path).map_err(|error| error.to_string())?;
    let mut reaped = false;

    let case_result: Result<Value, String> = (|| {
        wait_for(
            &child.child,
            &mut output,
            "standalone setup initial surface",
            |text| INITIAL_MARKERS.iter().all(|marker| marker_present(text, marker)),
            timeout,
        )?;
        let initial_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if initial_flags.canonical || initial_flags.echo {
            return Err(format!("initial setup surface did not enter raw mode: {initial_flags:?}"));
        }

        hades_dev::replay::send(&child.child.master, b"\x1b").map_err(|error| error.to_string())?;
        wait_for(
            &child.child,
            &mut output,
            "standalone setup numbered fallback",
            |text| FALLBACK_MARKERS.iter().all(|marker| marker_present(text, marker)),
            timeout,
        )?;
        let fallback_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if !fallback_flags.canonical || !fallback_flags.echo {
            return Err(format!(
                "numbered fallback did not restore terminal flags: {fallback_flags:?}"
            ));
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        // The numbered fallback restores canonical mode with ISIG, so
        // Python's pty.fork child receives SIGINT from the tty line
        // discipline. The harness spawn gives the child no controlling
        // terminal, so deliver the SIGINT directly — same handler, same
        // exit path, identical report.
        let pid = rustix::process::Pid::from_child(&child.child.child);
        let _ = rustix::process::kill_process(pid, rustix::process::Signal::INT);
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 1 }) {
            return Err(format!(
                "unexpected standalone setup cancellation status: {exit_status:?}"
            ));
        }

        let raw_output = output.clone();
        let cleanup_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if !cleanup_flags.canonical || !cleanup_flags.echo {
            return Err(format!(
                "terminal was not restored after setup cancellation: {cleanup_flags:?}"
            ));
        }
        let cleaned = clean_output(&output);
        if cleaned.contains("Provider error") || cleaned.contains("HADES_PROVIDER_BASE_URL") {
            return Err("standalone setup unexpectedly started provider behavior".to_owned());
        }

        Ok(json!({
            "case": "standalone-setup-escape-fallback",
            "arguments": ["setup"],
            "dimensions": {"columns": COLUMNS, "rows": ROWS},
            "startup": {
                "markers": INITIAL_MARKERS,
                "raw_mode": {"canonical": initial_flags.canonical, "echo": initial_flags.echo},
            },
            "fallback": {
                "markers": FALLBACK_MARKERS,
                "terminal_flags": {
                    "canonical": fallback_flags.canonical,
                    "echo": fallback_flags.echo,
                },
            },
            "input": ["Escape", "Ctrl+C"],
            "config_created": home.join("config.yaml").exists(),
            "provider_started": false,
            "exit": exit_status.as_json(),
            "cleanup": {
                "alternate_screen_entered": raw_output
                    .windows(b"\x1b[?1049h".len())
                    .any(|window| window == b"\x1b[?1049h"),
                "alternate_screen_left": raw_output
                    .windows(b"\x1b[?1049l".len())
                    .any(|window| window == b"\x1b[?1049l"),
                "terminal_flags": {
                    "canonical": cleanup_flags.canonical,
                    "echo": cleanup_flags.echo,
                },
            },
            "status": "passed",
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child.child);
    }
    let _ = fs::remove_dir_all(&home);
    case_result
}

fn write_report(report: &Value, path: Option<&Path>, status: u8) -> ExitCode {
    let text = serde_json::to_string_pretty(report).expect("serialize report");
    if let Some(path) = path {
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        use std::io::Write;
        if let Ok(mut file) = fs::File::create(path) {
            let _ = file.write_all(text.as_bytes());
            let _ = file.write_all(b"\n");
        }
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
        "probe": "hades-standalone-setup",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "cases": [],
    });

    if !binary.is_file() {
        report["passed"] = json!(false);
        report["error"] = json!("Hades binary not found");
        return write_report(&report, report_path.as_deref(), 2);
    }

    match run_case(&binary, timeout) {
        Ok(case) => {
            report["cases"] = json!([case]);
            report["passed"] = json!(true);
            write_report(&report, report_path.as_deref(), 0)
        }
        Err(error) => {
            report["passed"] = json!(false);
            report["error"] = json!(error);
            write_report(&report, report_path.as_deref(), 1)
        }
    }
}
