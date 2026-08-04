//! `hades-dev replay-standalone-full-setup` — Rust port of
//! `scripts/replay_standalone_full_setup.py` (HAD-163).
//!
//! Replays the Hades standalone Full setup continuation and cancellation
//! chain in an isolated direct PTY: `j` + Enter selects Full setup, the
//! bounded non-secret baseline config lands (mode: full, provider
//! unconfigured, no credential-like fields), Ctrl+C skips the provider
//! step, a second Ctrl+C opens the terminal-backend numbered fallback
//! (restoring canonical/echo flags), and a third Ctrl+C cancels with exit
//! code 1 and full terminal restoration. No provider behavior ever starts.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::Duration;

use hades_dev::replay::{
    ExitStatus, ReplayChild, RetainedSlave, clean_output, marker_present, spawn_with_env,
    terminal_flags, wait_for, wait_for_exit, wait_for_rendered,
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
const CONTINUATION_MARKERS: [&str; 7] = [
    "Configuration Location",
    "Config file:",
    "Secrets file:",
    "Data folder:",
    "Install dir:",
    "Inference Provider",
    "Choose how to connect to your main chat model.",
];
const TERMINAL_BACKEND_MARKERS: [&str; 2] = ["Select terminal backend:", "Keep current (local)"];
const FALLBACK_MARKERS: [&str; 4] =
    ["Select terminal backend:", "Enter for default (8)", "Ctrl+C to exit", "Select [1-8] (8):"];
/// Provider/credential vars the Python replay pops from the child env.
const STRIP_ENV: [&str; 5] = [
    "HADES_PROVIDER_BASE_URL",
    "HADES_PROVIDER_API_KEY",
    "HADES_MODEL",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
];

/// Reconstruct the on-screen text (what a real terminal shows), mirroring
/// `rendered_screen` from the Python replay.
fn rendered_text(output: &[u8]) -> String {
    let mut screen = hades_dev::screen::Screen::new(COLUMNS as usize, ROWS as usize);
    screen.feed(output);
    screen.lines().join("\n")
}

/// Spawn `binary setup` on a fresh 120x40 PTY with an isolated home,
/// mirroring `spawn_setup` (the Python child also sets the window size
/// and TERM/COLUMNS/LINES, which `spawn_with_env` already applies).
fn spawn_setup(binary: &Path, home: &Path) -> Result<ReplayChild, String> {
    let home_str = home.to_str().ok_or_else(|| "non-utf8 home".to_owned())?;
    let extra: [(&str, &str); 2] = [("HOME", home_str), ("HERMES_HOME", home_str)];
    spawn_with_env(binary, &["setup"], &extra, &STRIP_ENV).map_err(|error| error.to_string())
}

fn run_case(binary: &Path, timeout: Duration) -> Result<Value, String> {
    let home = std::env::temp_dir()
        .join(format!("hades-standalone-full-setup-home-{}", std::process::id()));
    let _ = fs::create_dir_all(&home);
    let mut child = spawn_setup(binary, &home)?;
    let mut output = Vec::new();
    let slave = RetainedSlave::retain(&child.slave_path).map_err(|error| error.to_string())?;
    let mut reaped = false;

    let case_result: Result<Value, String> = (|| {
        // The initial surface draws its box on the main screen BEFORE the
        // wizard enters the alternate screen (1049h), so two of the
        // initial markers ("Hermes Agent Setup Wizard", "Let's configure
        // your Hermes Agent installation.") exist only in the raw stream
        // and never in a rendered view — the raw wait mirrors the Python
        // replay. Every post-input wait below uses the rendered screen.
        wait_for(
            &child.child,
            &mut output,
            "standalone Full setup initial surface",
            |text| INITIAL_MARKERS.iter().all(|marker| marker_present(text, marker)),
            timeout,
        )?;
        let initial_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if initial_flags.canonical || initial_flags.echo {
            return Err(format!("initial setup surface did not enter raw mode: {initial_flags:?}"));
        }

        hades_dev::replay::send(&child.child.master, b"j").map_err(|error| error.to_string())?;
        hades_dev::replay::send(&child.child.master, b"\r").map_err(|error| error.to_string())?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "standalone Full setup continuation",
            |text| CONTINUATION_MARKERS.iter().all(|marker| marker_present(text, marker)),
            timeout,
        )?;
        let continuation_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        let config_path = home.join("config.yaml");
        if !config_path.is_file() {
            return Err("Full setup did not create the bounded baseline config".to_owned());
        }
        let config_text = fs::read_to_string(&config_path).map_err(|error| error.to_string())?;
        if !config_text.contains("mode: full") || !config_text.contains("provider: unconfigured") {
            return Err(
                "baseline config did not contain the bounded non-secret setup marker".to_owned()
            );
        }
        for secret_marker in ["api_key", "oauth", "token"] {
            if config_text.to_lowercase().contains(secret_marker) {
                return Err(
                    "baseline config unexpectedly contained a credential-like field".to_owned()
                );
            }
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "standalone Full setup Terminal Backend",
            |text| TERMINAL_BACKEND_MARKERS.iter().all(|marker| marker_present(text, marker)),
            timeout,
        )?;
        let terminal_backend_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if !marker_present(&rendered_text(&output), "Terminal Backend") {
            return Err("Terminal Backend title was not visible in the rendered screen".to_owned());
        }
        if terminal_backend_flags.canonical || terminal_backend_flags.echo {
            return Err(format!(
                "Terminal Backend unexpectedly left raw mode after provider skip: {terminal_backend_flags:?}"
            ));
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "standalone Full setup numbered fallback",
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
        // The numbered fallback waits on a signal_hook SIGINT flag
        // (`wait_for_setup_signal`), and the Python harness's `pty.fork`
        // child is a session leader with the PTY as controlling terminal,
        // so the tty driver's ISIG delivers that SIGINT on ^C. The Rust
        // `spawn_pty` opens the slave with NOCTTY and never calls setsid,
        // so the child has no controlling terminal and ISIG has no
        // foreground process group to signal — mirror the observable
        // outcome by delivering SIGINT to the child directly.
        let pid = rustix::process::Pid::from_child(&child.child.child);
        rustix::process::kill_process(pid, rustix::process::Signal::INT)
            .map_err(|error| format!("could not deliver SIGINT: {error}"))?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 1 }) {
            return Err(format!("unexpected Full setup cancellation status: {exit_status:?}"));
        }

        let raw_output = output.clone();
        let cleanup_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if !cleanup_flags.canonical || !cleanup_flags.echo {
            return Err(format!(
                "terminal was not restored after Full setup cancellation: {cleanup_flags:?}"
            ));
        }
        let cleaned = clean_output(&output);
        if cleaned.contains("Provider error") || cleaned.contains("HADES_PROVIDER_BASE_URL") {
            return Err("standalone Full setup unexpectedly started provider behavior".to_owned());
        }

        Ok(json!({
            "case": "standalone-full-setup-continuation",
            "arguments": ["setup"],
            "dimensions": {"columns": COLUMNS, "rows": ROWS},
            "startup": {
                "markers": INITIAL_MARKERS,
                "raw_mode": {"canonical": initial_flags.canonical, "echo": initial_flags.echo},
            },
            "continuation": {
                "markers": CONTINUATION_MARKERS,
                "terminal_flags": {
                    "canonical": continuation_flags.canonical,
                    "echo": continuation_flags.echo,
                },
                "config_created": true,
                "config_non_secret_marker": true,
            },
            "terminal_backend": {
                "markers": TERMINAL_BACKEND_MARKERS,
                "terminal_flags": {
                    "canonical": terminal_backend_flags.canonical,
                    "echo": terminal_backend_flags.echo,
                },
            },
            "fallback": {
                "markers": FALLBACK_MARKERS,
                "terminal_flags": {
                    "canonical": fallback_flags.canonical,
                    "echo": fallback_flags.echo,
                },
            },
            "input": [
                "j",
                "Enter",
                "Ctrl+C (skip provider)",
                "Ctrl+C (open terminal-backend fallback)",
                "Ctrl+C (cancel)",
            ],
            "provider_started": false,
            "credentials_entered": false,
            "oauth_started": false,
            "config_created": config_path.exists(),
            "exit": exit_status.as_json(),
            "cleanup": {
                "alternate_screen_entered": raw_output
                    .windows(8)
                    .any(|window| window == b"\x1b[?1049h"),
                "alternate_screen_left": raw_output
                    .windows(8)
                    .any(|window| window == b"\x1b[?1049l"),
                "terminal_flags": {
                    "canonical": cleanup_flags.canonical,
                    "echo": cleanup_flags.echo,
                },
                "ctrl_c_presses": 3,
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
        "probe": "hades-standalone-full-setup",
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
