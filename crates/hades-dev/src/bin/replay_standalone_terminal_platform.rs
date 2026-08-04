//! `hades-dev replay-standalone-terminal-platform` — Rust port of
//! `scripts/replay_standalone_terminal_platform.py` (HAD-164).
//!
//! Replays Hades' standalone setup terminal-backend and platform
//! cancellation boundary in an isolated direct PTY: two cases drive
//! `hades setup` through the wizard, provider skip, terminal-backend
//! picker, numbered fallback (case 1) or platform picker and tool
//! configuration (case 2), asserting raw-mode ownership, bounded config
//! persistence, alternate-screen behavior, and clean terminal restore.
//!
//! Marker waits use the rendered screen (`wait_for_rendered`): the
//! standalone setup runs inside the main TUI loop whose animated startup
//! logo fragments typed-text markers in the raw byte stream.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::Duration;

use hades_dev::replay::{
    ExitStatus, RetainedSlave, TerminalFlags, marker_present, send, terminal_flags, try_wait,
    wait_for, wait_for_exit, wait_for_rendered,
};
use serde_json::{Value, json};

const COLUMNS: usize = 120;
const ROWS: usize = 40;
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
const PLATFORM_MARKERS: [&str; 4] = ["Mattermost", "Signal", "WhatsApp", "(not configured)"];
const TOOL_CONFIGURATION_MARKERS: [&str; 4] = [
    "No platforms selected. Run 'hermes setup gateway' later to configure.",
    "Hermes Tool Configuration",
    "Enable or disable tools per platform.",
    "Tools that need API keys will be configured when enabled.",
];
const SETUP_STATE_FILE: &str = "hades-setup-boundary.conf";
const SETUP_STATE_MARKERS: [&str; 5] = [
    "schema=1",
    "setup_mode=full",
    "terminal_backend=local",
    "platform_selection=none",
    "provider=unconfigured",
];
const STRIP_ENV: [&str; 5] = [
    "HADES_PROVIDER_BASE_URL",
    "HADES_PROVIDER_API_KEY",
    "HADES_MODEL",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
];
const CREDENTIAL_MARKERS: [&str; 3] = ["api_key", "oauth", "token"];

fn flags_json(flags: &TerminalFlags) -> Value {
    json!({"canonical": flags.canonical, "echo": flags.echo})
}

fn contains_credential_like_field(text: &str) -> bool {
    let lowered = text.to_lowercase();
    CREDENTIAL_MARKERS.iter().any(|marker| lowered.contains(marker))
}

/// Bounded shape of the setup config, like `config_shape`.
fn config_shape(path: &Path) -> Result<Value, String> {
    if !path.is_file() {
        return Ok(json!({"exists": false, "bytes": 0}));
    }
    let text = fs::read_to_string(path)
        .map_err(|error| format!("could not read config {}: {error}", path.display()))?;
    Ok(json!({
        "exists": true,
        "bytes": text.len(),
        "contains_non_secret_baseline": text.contains("mode: full") && text.contains("provider: unconfigured"),
        "contains_credential_like_field": contains_credential_like_field(&text),
    }))
}

/// Bounded shape of the persisted setup state file, like
/// `setup_state_shape`.
fn setup_state_shape(home: &Path) -> Result<Value, String> {
    let path = home.join(SETUP_STATE_FILE);
    if !path.is_file() {
        return Ok(json!({"exists": false, "bytes": 0, "temporary_files": []}));
    }
    let text = fs::read_to_string(&path)
        .map_err(|error| format!("could not read setup state {}: {error}", path.display()))?;
    let mut temporary_files: Vec<String> = fs::read_dir(home)
        .map_err(|error| format!("could not list home {}: {error}", home.display()))?
        .filter_map(|entry| entry.ok())
        .filter_map(|entry| entry.file_name().into_string().ok())
        .filter(|name| name.starts_with(&format!(".{SETUP_STATE_FILE}.")))
        .collect();
    temporary_files.sort();
    Ok(json!({
        "exists": true,
        "bytes": text.len(),
        "contains_expected_structure": SETUP_STATE_MARKERS.iter().all(|marker| text.contains(marker)),
        "contains_credential_like_field": contains_credential_like_field(&text),
        "temporary_files": temporary_files,
    }))
}

fn count_sequence(output: &[u8], sequence: &[u8]) -> usize {
    output.windows(sequence.len()).filter(|window| *window == sequence).count()
}

/// fd 0 of the child: the PTY slave, already dup2'd by the spawn
/// machinery before `pre_exec` runs. Wrapped so TIOCSCTTY can be issued
/// without touching `std::io::stdin()` (not async-signal-safe).
struct ChildStdinFd;

impl std::os::fd::AsFd for ChildStdinFd {
    fn as_fd(&self) -> std::os::fd::BorrowedFd<'_> {
        // Safety: fd 0 is the slave side of the PTY in the child.
        unsafe { std::os::fd::BorrowedFd::borrow_raw(0) }
    }
}

fn spawn_setup(binary: &Path, home: &Path) -> Result<hades_dev::replay::ReplayChild, String> {
    use std::os::unix::process::CommandExt;

    let home_str = home.to_str().ok_or_else(|| "non-utf8 home".to_owned())?;
    let mut command = std::process::Command::new(binary);
    command.arg("setup");
    command.env("TERM", "xterm-256color");
    command.env("COLUMNS", "120");
    command.env("LINES", "40");
    command.env("HOME", home_str);
    command.env("HERMES_HOME", home_str);
    for key in STRIP_ENV {
        command.env_remove(key);
    }
    // The Python harness's `pty.fork` makes the child a session leader
    // with the PTY as its controlling terminal, so a canonical-mode
    // Ctrl+C raises SIGINT inside the child (the numbered-fallback exit
    // contract depends on that signal). The shared `spawn_pty` spawns via
    // `Command` without either, so replicate both here: `setsid()` then
    // TIOCSCTTY on fd 0. Both calls are async-signal-safe.
    unsafe {
        command.pre_exec(|| {
            rustix::process::setsid().map_err(|_| std::io::Error::other("setsid failed"))?;
            rustix::process::ioctl_tiocsctty(ChildStdinFd)
                .map_err(|_| std::io::Error::other("TIOCSCTTY failed"))?;
            Ok(())
        });
    }
    let child =
        hades_dev::pty::spawn_pty(&mut command, 120, 40).map_err(|error| error.to_string())?;
    let slave_path = child.slave_path.clone();
    Ok(hades_dev::replay::ReplayChild { child, slave_path, history_home: home.to_path_buf() })
}

fn run_case(
    binary: &Path,
    timeout: Duration,
    ordinal: usize,
    accept_backend: bool,
) -> Result<Value, String> {
    let home = std::env::temp_dir()
        .join(format!("hades-standalone-terminal-platform-home-{}-{ordinal}", std::process::id()));
    let _ = fs::create_dir_all(&home);
    let mut child = spawn_setup(binary, &home)?;
    let mut output = Vec::new();
    let slave_path = child.slave_path.clone();
    let slave = RetainedSlave::retain(&slave_path).map_err(|error| error.to_string())?;
    let mut reaped = false;

    let result = (|| -> Result<Value, String> {
        // The initial surface is the setup BANNER, printed once with plain
        // `writeln!` before the alternate screen is entered; the choice
        // Paragraph then overwrites the banner's top rows, so the banner
        // markers exist only in the accumulated raw stream (the Python twin
        // waits on raw text here too). The standalone setup loop has no
        // animated logo, so raw matching cannot fragment.
        wait_for(
            &child.child,
            &mut output,
            "standalone terminal/platform initial surface",
            |text| INITIAL_MARKERS.iter().all(|marker| marker_present(text, marker)),
            timeout,
        )?;
        let initial_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if initial_flags.canonical || initial_flags.echo {
            return Err(format!(
                "initial setup surface did not enter raw mode: {:?}",
                flags_json(&initial_flags)
            ));
        }
        let config_before = config_shape(&home.join("config.yaml"))?;

        send(&child.child.master, b"j\r").map_err(|error| error.to_string())?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "standalone Full setup continuation",
            |rendered| CONTINUATION_MARKERS.iter().all(|marker| marker_present(rendered, marker)),
            timeout,
        )?;
        let continuation_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        let config_at_continuation = config_shape(&home.join("config.yaml"))?;
        let setup_state_at_continuation = setup_state_shape(&home)?;
        if setup_state_at_continuation["exists"].as_bool() == Some(true) {
            return Err(
                "Full setup persisted backend/platform state before backend acceptance".to_owned()
            );
        }

        send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "standalone terminal backend",
            |rendered| {
                TERMINAL_BACKEND_MARKERS.iter().all(|marker| marker_present(rendered, marker))
            },
            timeout,
        )?;
        let terminal_backend_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if terminal_backend_flags.canonical || terminal_backend_flags.echo {
            return Err(format!(
                "provider cancellation unexpectedly restored terminal flags: {:?}",
                flags_json(&terminal_backend_flags)
            ));
        }

        if !accept_backend {
            send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
            wait_for_rendered(
                &child.child,
                &mut output,
                "standalone numbered fallback after backend cancellation",
                |rendered| FALLBACK_MARKERS.iter().all(|marker| marker_present(rendered, marker)),
                timeout,
            )?;
            let fallback_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
            if !fallback_flags.canonical || !fallback_flags.echo {
                return Err(format!(
                    "backend cancellation did not restore terminal flags: {:?}",
                    flags_json(&fallback_flags)
                ));
            }
            let state_after_backend_cancel = setup_state_shape(&home)?;
            if state_after_backend_cancel["exists"].as_bool() == Some(true) {
                return Err("backend cancellation unexpectedly persisted setup state".to_owned());
            }

            send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
            let status = wait_for_exit(&child.child, &mut output, timeout)?;
            reaped = true;
            let exit_status = ExitStatus::describe(status).as_json();
            if exit_status != json!({"kind": "exit", "code": 1}) {
                return Err(format!("unexpected backend-cancellation status: {exit_status}"));
            }
            let cleanup_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
            if !cleanup_flags.canonical || !cleanup_flags.echo {
                return Err(format!(
                    "terminal was not restored after cleanup: {:?}",
                    flags_json(&cleanup_flags)
                ));
            }
            let config_after = config_shape(&home.join("config.yaml"))?;
            if config_after != config_at_continuation {
                return Err("backend cancellation changed the bounded setup config".to_owned());
            }
            let cleaned = hades_dev::replay::clean_output(&output);
            if cleaned.contains("Provider error") || cleaned.contains("HADES_PROVIDER_BASE_URL") {
                return Err(
                    "backend cancellation unexpectedly started provider behavior".to_owned()
                );
            }

            return Ok(json!({
                "case": "standalone-terminal-backend-cancel",
                "arguments": ["setup"],
                "dimensions": {"columns": COLUMNS, "rows": ROWS},
                "startup": {
                    "markers": INITIAL_MARKERS,
                    "terminal_flags": flags_json(&initial_flags),
                },
                "continuation": {
                    "markers": CONTINUATION_MARKERS,
                    "terminal_flags": flags_json(&continuation_flags),
                    "config": config_at_continuation,
                    "setup_state": setup_state_at_continuation,
                },
                "terminal_backend": {
                    "markers": TERMINAL_BACKEND_MARKERS,
                    "terminal_flags": flags_json(&terminal_backend_flags),
                },
                "fallback_after_backend_cancel": {
                    "markers": FALLBACK_MARKERS,
                    "terminal_flags": flags_json(&fallback_flags),
                    "setup_state": state_after_backend_cancel,
                },
                "cancellation": {
                    "input": [
                        "j",
                        "Enter",
                        "Ctrl+C (skip provider)",
                        "Ctrl+C (cancel Keep current local backend)",
                        "Ctrl+C (cancel numbered fallback)",
                    ],
                    "backend_cancel_added_no_state": true,
                    "exit": exit_status,
                    "alternate_screen_entered": count_sequence(&output, b"\x1b[?1049h") > 0,
                    "alternate_screen_left": count_sequence(&output, b"\x1b[?1049l") > 0,
                    "terminal_flags": flags_json(&cleanup_flags),
                    "credentials_entered": false,
                    "oauth_started": false,
                    "network_requested": false,
                },
                "persistence": {
                    "config_before": config_before,
                    "config_after": config_after,
                    "config_unchanged_after_backend_cancel": config_after == config_at_continuation,
                    "setup_state_created": false,
                    "secrets_file_created": false,
                },
                "provider_started": false,
                "status": "passed",
            }));
        }

        send(&child.child.master, b"\r").map_err(|error| error.to_string())?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "standalone platform picker",
            |rendered| PLATFORM_MARKERS.iter().all(|marker| marker_present(rendered, marker)),
            timeout,
        )?;
        let platform_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        let setup_state_at_platform = setup_state_shape(&home)?;
        if setup_state_at_platform["exists"].as_bool() != Some(true) {
            return Err("accepted local backend did not persist Hades setup state".to_owned());
        }
        if setup_state_at_platform["contains_expected_structure"].as_bool() != Some(true) {
            return Err("persisted Hades setup state missed a bounded structural marker".to_owned());
        }
        if setup_state_at_platform["contains_credential_like_field"].as_bool() == Some(true) {
            return Err("persisted Hades setup state contained a credential-like field".to_owned());
        }
        if !setup_state_at_platform["temporary_files"]
            .as_array()
            .is_some_and(|files| files.is_empty())
        {
            return Err("atomic setup-state write left a temporary file".to_owned());
        }
        let leaves_before_cancel = count_sequence(&output, b"\x1b[?1049l");

        send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        // The tool-configuration surface is entered via plain `writeln!`
        // prints, then the child re-enables raw mode after a 25 ms sleep;
        // the terminal flags are read right after the markers appear, so
        // this wait must wake on data like the Python `select`-based
        // `wait_for` (the 20 ms poll of the rendered waits can straddle
        // the mode switch and flip the recorded flags).
        hades_dev::pty::wait_for(
            &child.child.master,
            &mut output,
            "standalone tool configuration boundary",
            |text| TOOL_CONFIGURATION_MARKERS.iter().all(|marker| marker_present(text, marker)),
            timeout,
        )?;
        let first_cancel_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if try_wait(&child.child)?.is_some() {
            return Err("first platform Ctrl+C unexpectedly exited the setup process".to_owned());
        }
        let leaves_after_first_cancel = count_sequence(&output, b"\x1b[?1049l");
        if leaves_after_first_cancel <= leaves_before_cancel {
            return Err("first platform Ctrl+C did not leave the alternate screen".to_owned());
        }

        send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status).as_json();
        if exit_status != json!({"kind": "exit", "code": 130}) {
            return Err(format!("unexpected second Ctrl+C status: {exit_status}"));
        }
        let cleanup_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if !cleanup_flags.canonical || !cleanup_flags.echo {
            return Err(format!(
                "terminal was not restored after cleanup: {:?}",
                flags_json(&cleanup_flags)
            ));
        }

        let config_after = config_shape(&home.join("config.yaml"))?;
        if config_after != config_at_continuation {
            return Err("platform cancellation changed the bounded setup config".to_owned());
        }
        let setup_state_after_platform_cancel = setup_state_shape(&home)?;
        if setup_state_after_platform_cancel != setup_state_at_platform {
            return Err("platform cancellation changed the persisted Hades setup state".to_owned());
        }
        if home.join(".env").exists() {
            return Err("platform cancellation created a secrets file".to_owned());
        }
        let cleaned = hades_dev::replay::clean_output(&output);
        if cleaned.contains("Provider error") || cleaned.contains("HADES_PROVIDER_BASE_URL") {
            return Err(
                "standalone platform boundary unexpectedly started provider behavior".to_owned()
            );
        }

        Ok(json!({
            "case": "standalone-terminal-platform-boundary",
            "arguments": ["setup"],
            "dimensions": {"columns": COLUMNS, "rows": ROWS},
            "startup": {
                "markers": INITIAL_MARKERS,
                "terminal_flags": flags_json(&initial_flags),
            },
            "continuation": {
                "markers": CONTINUATION_MARKERS,
                "terminal_flags": flags_json(&continuation_flags),
                "config": config_at_continuation,
                "setup_state": setup_state_at_continuation,
            },
            "terminal_backend": {
                "markers": TERMINAL_BACKEND_MARKERS,
                "terminal_flags": flags_json(&terminal_backend_flags),
            },
            "platform_picker": {
                "markers": PLATFORM_MARKERS,
                "terminal_flags": flags_json(&platform_flags),
            },
            "tool_configuration_after_platform_cancel": {
                "markers": TOOL_CONFIGURATION_MARKERS,
                "terminal_flags": flags_json(&first_cancel_flags),
                "process_still_alive": true,
            },
            "cancellation": {
                "input": [
                    "j",
                    "Enter",
                    "Ctrl+C (skip provider)",
                    "Enter (accept Keep current local backend)",
                    "Ctrl+C (leave platform picker)",
                    "Ctrl+C (SIGINT cleanup)",
                ],
                "first_ctrl_c_alternate_screen_left": leaves_after_first_cancel > leaves_before_cancel,
                "second_ctrl_c_exit": exit_status,
                "alternate_screen_entered": count_sequence(&output, b"\x1b[?1049h") > 0,
                "alternate_screen_left": count_sequence(&output, b"\x1b[?1049l") > 0,
                "terminal_flags": flags_json(&cleanup_flags),
                "credentials_entered": false,
                "oauth_started": false,
                "network_requested": false,
            },
            "persistence": {
                "config_before": config_before,
                "config_after": config_after,
                "config_unchanged_after_platform_cancel": config_after == config_at_continuation,
                "setup_state_at_platform": setup_state_at_platform,
                "setup_state_after_platform_cancel": setup_state_after_platform_cancel,
                "setup_state_unchanged_after_platform_cancel": setup_state_after_platform_cancel == setup_state_at_platform,
                "secrets_file_created": false,
            },
            "provider_started": false,
            "status": "passed",
        }))
    })();

    if !reaped {
        let pid = child.child.child.id();
        let _ = std::process::Command::new("kill").args(["-KILL", &pid.to_string()]).status();
        let _ = child.child.child.wait();
    }
    let _ = fs::remove_dir_all(&home);
    result
}

fn emit_report(report: &Value, path: Option<&Path>, status: u8) -> ExitCode {
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
        "probe": "hades-standalone-terminal-platform",
        "binary": "<hades-binary>",
        "dimensions": {"columns": COLUMNS, "rows": ROWS},
        "cases": [],
    });
    if !binary.is_file() {
        report["passed"] = json!(false);
        report["error"] = json!("Hades binary not found");
        return emit_report(&report, report_path.as_deref(), 2);
    }

    let first = match run_case(&binary, timeout, 1, false) {
        Ok(case) => case,
        Err(error) => {
            report["passed"] = json!(false);
            report["error"] = json!(error);
            return emit_report(&report, report_path.as_deref(), 1);
        }
    };
    let second = match run_case(&binary, timeout, 2, true) {
        Ok(case) => case,
        Err(error) => {
            report["passed"] = json!(false);
            report["error"] = json!(error);
            return emit_report(&report, report_path.as_deref(), 1);
        }
    };
    report["cases"] = json!([first, second]);
    report["passed"] = json!(true);
    emit_report(&report, report_path.as_deref(), 0)
}
