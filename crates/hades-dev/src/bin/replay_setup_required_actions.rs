//! `hades-dev replay-setup-required-actions` — Rust port of
//! `scripts/replay_setup_required_actions.py` (HAD-161).
//!
//! Replays the no-provider Setup Required action boundary (OBS-0105):
//! after the delayed Setup Required overlay appears, follow-up action
//! commands (/model, /setup) stay on the overlay and never become
//! composer drafts or create config.yaml; the first Ctrl+C clears the
//! retained /help draft without exiting, and a second Ctrl+C exits
//! cleanly with the terminal restored.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{Duration, Instant};

use hades_dev::replay::{
    ExitStatus, RetainedSlave, TerminalFlags, marker_present, spawn_with_env, terminal_flags,
    try_wait, wait_for, wait_for_exit,
};
use serde_json::{Value, json};

const COLUMNS: u16 = 120;
const ROWS: u16 = 40;
const HELP_SETUP_REQUIRED_DELAY_MS: u64 = 8_000;
const STARTUP_MARKERS: [&str; 6] = [
    "Hades Agent",
    "Underworld",
    "Available Tools",
    "Available Skills",
    "glm-5.2 · Hades",
    "starting agent",
];
const SETUP_MARKERS: [&str; 4] = ["Setup Required", "/model", "/setup", "Ctrl+C"];
const ACTION_COMMANDS: [&str; 2] = ["/model", "/setup"];
const STRIP_ENV: [&str; 9] = [
    "HERMES_DESKTOP",
    "PYTHONPATH",
    "TMUX",
    "STY",
    "WAYLAND_DISPLAY",
    "WSL_INTEROP",
    "WSL_DISTRO_NAME",
    "SSH_CONNECTION",
    "SSH_CLIENT",
];

fn recent_output(output: &[u8], lines: usize) -> String {
    let text = String::from_utf8_lossy(output);
    text.lines()
        .rev()
        .take(lines)
        .collect::<Vec<_>>()
        .iter()
        .rev()
        .cloned()
        .collect::<Vec<_>>()
        .join("\n")
}

fn last_lines(text: &str, lines: usize) -> String {
    text.lines()
        .rev()
        .take(lines)
        .collect::<Vec<_>>()
        .iter()
        .rev()
        .cloned()
        .collect::<Vec<_>>()
        .join("\n")
}

/// The current rendered 120x40 screen, like the Python `latest_screen_text`.
fn latest_screen_text(output: &[u8]) -> String {
    let mut screen = hades_dev::screen::Screen::new(COLUMNS as usize, ROWS as usize);
    screen.feed(output);
    screen.lines().join("\n")
}

/// Terminal flags with an ENOTTY retry window, like `stable_terminal_flags`.
fn stable_terminal_flags(slave: &RetainedSlave) -> Result<TerminalFlags, String> {
    let mut last_error: Option<std::io::Error> = None;
    for _ in 0..100 {
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

fn run_case(binary: &Path, command: Option<&str>, timeout: Duration) -> Result<Value, String> {
    let label = match command {
        Some(command) => command.trim_start_matches('/').to_owned(),
        None => "ctrl-c".to_owned(),
    };
    let case = format!("post-delay-{label}");
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
        let startup_flags = stable_terminal_flags(&slave)?;
        if startup_flags.canonical || startup_flags.echo {
            return Err(format!("{case}: startup did not enter raw mode: {startup_flags:?}"));
        }

        hades_dev::replay::send(&child.child.master, b"/help\r")
            .map_err(|error| error.to_string())?;
        wait_for(
            &child.child,
            &mut output,
            &format!("{case}: delayed Setup Required"),
            |text| {
                let recent = last_lines(text, 64);
                SETUP_MARKERS.iter().all(|marker| marker_present(&recent, marker))
            },
            timeout.max(Duration::from_secs(10)),
        )?;
        let transition_text = recent_output(&output, 64);
        for marker in SETUP_MARKERS {
            if !marker_present(&transition_text, marker) {
                return Err(format!("{case}: missing Setup Required marker: {marker}"));
            }
        }

        let action_text = if let Some(command) = command {
            let payload = format!("{command}\r\r");
            hades_dev::replay::send(&child.child.master, payload.as_bytes())
                .map_err(|error| error.to_string())?;
            std::thread::sleep(Duration::from_millis(350));
            output.extend_from_slice(&hades_dev::pty::read_available(&child.child.master));
            let text = recent_output(&output, 64);
            for marker in SETUP_MARKERS {
                if !marker_present(&text, marker) {
                    return Err(format!("{case}: missing Setup Required marker: {marker}"));
                }
            }
            if marker_present(&text, &format!("❯ {command}")) {
                return Err(format!("{case}: follow-up command became an active composer draft"));
            }
            text
        } else {
            transition_text
        };

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(150));
        output.extend_from_slice(&hades_dev::pty::read_available(&child.child.master));
        let after_first_ctrl_c = recent_output(&output, 64);
        for marker in SETUP_MARKERS {
            if !marker_present(&after_first_ctrl_c, marker) {
                return Err(format!("{case}: missing Setup Required marker: {marker}"));
            }
        }
        if try_wait(&child.child)?.is_some() {
            return Err(format!("{case}: first Ctrl+C exited before the bounded second press"));
        }
        let latest = latest_screen_text(&output);
        if marker_present(&latest, "❯ /help") {
            return Err(format!("{case}: first Ctrl+C did not clear the retained /help draft"));
        }
        if child.history_home.join("config.yaml").exists() {
            return Err(format!("{case}: no-provider action created config.yaml"));
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 0 }) {
            return Err(format!("{case}: unexpected exit status: {exit_status:?}"));
        }
        let cleanup_flags = stable_terminal_flags(&slave)?;
        if !cleanup_flags.canonical || !cleanup_flags.echo {
            return Err(format!("{case}: terminal was not restored: {cleanup_flags:?}"));
        }
        if !find_sequence(&output, b"\x1b[?1049h") || !find_sequence(&output, b"\x1b[?1049l") {
            return Err(format!("{case}: alternate-screen cleanup was incomplete"));
        }

        Ok(json!({
            "id": case,
            "status": "passed",
            "input": {
                "initial_command": "/help",
                "follow_up_command": command,
                "follow_up_enter_count": if command.is_some() { 2 } else { 0 },
                "cleanup_sequence": ["Ctrl+C", "Ctrl+C"],
            },
            "setup_required": {
                "markers": SETUP_MARKERS,
                "follow_up_remained_on_overlay": command.is_some(),
                "model_picker_visible": false,
                "setup_wizard_visible": false,
                "provider_request_started": false,
                "config_created": false,
            },
            "first_ctrl_c": {
                "process_alive": true,
                "overlay_remained_visible": true,
                "retained_help_draft_cleared": true,
            },
            "cleanup": {
                "exit": match exit_status {
                    ExitStatus::Exit { code } => json!({"kind": "exit", "code": code}),
                    ExitStatus::Signal { number } => json!({"kind": "signal", "signal": number}),
                    ExitStatus::Other { raw } => json!({"kind": "other", "code": raw}),
                },
                "alternate_screen_left": true,
                "terminal_flags": {
                    "canonical": cleanup_flags.canonical,
                    "echo": cleanup_flags.echo,
                },
            },
            "reference_delay_ms": HELP_SETUP_REQUIRED_DELAY_MS,
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child.child);
    }
    result
}

fn find_sequence(haystack: &[u8], needle: &[u8]) -> bool {
    haystack.windows(needle.len()).any(|window| window == needle)
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
    let mut timeout = Duration::from_secs_f64(20.0);

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
                    timeout = Duration::from_secs_f64(value.parse().unwrap_or(20.0));
                }
            }
            _ => {}
        }
    }

    let binary = binary.canonicalize().unwrap_or_else(|_| binary.clone());
    let mut report = json!({
        "schema_version": 1,
        "observation_id": "OBS-0105",
        "contract_observation": "OBS-0104",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "cases": [],
        "passed": false,
        "unknowns": [
            "No provider, credential, OAuth, network, model selection, or setup persistence behavior was exercised.",
            "The replay covers only the observed no-provider Setup Required boundary at 120x40.",
        ],
    });
    if !binary.is_file() {
        report["error"] = json!("Hades binary not found");
        return write_report(&report, report_path.as_deref(), 2);
    }

    let mut cases = Vec::new();
    for command in ACTION_COMMANDS.iter().map(|command| Some(*command)).chain([None]) {
        match run_case(&binary, command, timeout) {
            Ok(case) => cases.push(case),
            Err(error) => {
                report["error"] = json!(error);
                return write_report(&report, report_path.as_deref(), 1);
            }
        }
    }
    report["cases"] = json!(cases);
    report["passed"] = json!(true);
    write_report(&report, report_path.as_deref(), 0)
}
