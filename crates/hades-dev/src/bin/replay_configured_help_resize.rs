//! `hades-dev replay-configured-help-resize` — Rust port of
//! `scripts/replay_configured_help_resize.py` (HAD-150).
//!
//! Replays the configured /help panel geometry at three PTY sizes
//! (120x40, 100x30, 160x50) against the OBS-0102 contract: the bordered
//! panel floats above the composer (owner-directed layout), the composer
//! draft survives the resize, and a clean Ctrl+C exit restores the
//! terminal.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{Duration, Instant};

use hades_dev::pty::{read_available, resize_pty};
use hades_dev::replay::{
    ExitStatus, RetainedSlave, marker_present, spawn_with_env, terminal_flags, try_wait, wait_for,
    wait_for_exit,
};
use hades_dev::screen::Screen;
use serde_json::{Value, json};

const COLUMNS: u16 = 120;
const ROWS: u16 = 40;
const HELP_COMMAND: &str = "/help Show available commands";
const MAIN_SURFACE_MARKERS: [&str; 4] =
    ["Hades Agent", "Available Tools", "Available Skills", "/help for commands"];
const RESIZE_CASES: [(u16, u16); 3] = [(120, 40), (100, 30), (160, 50)];

fn screen_lines(raw: &[u8], columns: usize, rows: usize) -> Vec<String> {
    let mut screen = Screen::new(columns, rows);
    screen.feed(raw);
    screen.lines().into_iter().map(|line| line.trim_end().to_owned()).collect()
}

/// Reconstruct the resized help-panel geometry, mirroring the Python
/// `panel_state`: x/y/width/height of the bordered command row plus the
/// composer row index.
fn panel_state(raw: &[u8], columns: usize, rows: usize) -> Option<Value> {
    let lines = screen_lines(raw, columns, rows);
    let command_index = lines.iter().position(|line| line.contains("Show available commands"))?;
    if command_index == 0 || command_index + 1 >= lines.len() {
        return None;
    }
    let top = lines[command_index - 1].trim().to_owned();
    let command = lines[command_index].trim().to_owned();
    let bottom = lines[command_index + 1].trim().to_owned();
    let composer_index = lines.iter().position(|line| line.contains("❯ /help"))?;
    if !top.starts_with('╔')
        || !top.ends_with('╗')
        || !bottom.starts_with('╚')
        || !bottom.ends_with('╝')
        || !command.contains("Show available commands")
    {
        return None;
    }
    Some(json!({
        "x": lines[command_index - 1].len() - lines[command_index - 1].trim_start().len(),
        "y": command_index - 1,
        "width": top.chars().count(),
        "height": 3,
        "top_border": top,
        "command": HELP_COMMAND,
        "bottom_border": bottom,
        "composer": "❯ /help",
        "composer_y": composer_index,
    }))
}

fn wait_for_panel(
    child: &hades_dev::replay::ReplayChild,
    output: &mut Vec<u8>,
    columns: usize,
    rows: usize,
    timeout: Duration,
) -> Result<Value, String> {
    let deadline = Instant::now() + timeout;
    let mut previous: Option<String> = None;
    let mut stable_samples = 0;
    while Instant::now() < deadline {
        output.extend_from_slice(&read_available(&child.child.master));
        if let Some(state) = panel_state(output, columns, rows) {
            let signature = serde_json::to_string(&state).expect("serialize panel state");
            if previous.as_deref() == Some(signature.as_str()) {
                stable_samples += 1;
            } else {
                previous = Some(signature);
                stable_samples = 1;
            }
            if stable_samples >= 3 {
                let mut state = state;
                state["stable_samples"] = json!(stable_samples);
                return Ok(state);
            }
        } else {
            previous = None;
            stable_samples = 0;
        }
        if try_wait(&child.child)?.is_some() {
            return Err(format!(
                "help-panel-{columns}x{rows}: Hades exited before the resized Help panel stabilized"
            ));
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    output.extend_from_slice(&read_available(&child.child.master));
    Err(format!(
        "help-panel-{columns}x{rows}: timed out after {:.1}s waiting for the resized Help panel",
        timeout.as_secs_f64()
    ))
}

fn run_case(binary: &Path, timeout: Duration) -> Result<Value, String> {
    let root =
        std::env::temp_dir().join(format!("hades-configured-help-resize-{}", std::process::id()));
    let home = root.join("home");
    fs::create_dir_all(&home).map_err(|error| error.to_string())?;

    let extra: [(&str, &str); 4] = [
        ("HADES_PROVIDER_BASE_URL", "http://127.0.0.1:1/v1"),
        ("HADES_MODEL", "help-model"),
        ("HOME", home.to_str().ok_or_else(|| "non-utf8 home".to_owned())?),
        ("HERMES_HOME", home.to_str().ok_or_else(|| "non-utf8 home".to_owned())?),
    ];
    let mut child = spawn_with_env(binary, &[], &extra, &["HADES_PROVIDER_API_KEY"])
        .map_err(|error| error.to_string())?;
    let mut output = Vec::new();
    let mut reaped = false;
    let slave_path = child.slave_path.clone();

    let result = (|| -> Result<Value, String> {
        wait_for(
            &child.child,
            &mut output,
            "startup",
            |text| {
                MAIN_SURFACE_MARKERS.iter().all(|marker| marker_present(text, marker))
                    && marker_present(text, "ready")
            },
            timeout,
        )?;

        hades_dev::replay::send(&child.child.master, b"/help\r")
            .map_err(|error| error.to_string())?;
        let mut observations = Vec::new();
        for (index, (columns, rows)) in RESIZE_CASES.iter().enumerate() {
            if index > 0 {
                resize_pty(&child.child.master, &slave_path, &child.child.child, *columns, *rows)
                    .map_err(|error| format!("resize to {columns}x{rows} failed: {error}"))?;
            }
            let state =
                wait_for_panel(&child, &mut output, *columns as usize, *rows as usize, timeout)?;
            // Composer sits ABOVE the information line (owner-directed
            // deviation): the panel floats above the composer.
            let expected: [(&str, Value); 4] = [
                ("x", json!(1)),
                ("y", json!(rows - 5)),
                ("width", json!(columns - 2)),
                ("height", json!(3)),
            ];
            for (key, value) in expected {
                if state[key] != value {
                    return Err(format!(
                        "help-panel-{columns}x{rows}: observed {key}={}, expected {value}",
                        state[key]
                    ));
                }
            }
            if state["composer_y"] != json!(rows - 2) {
                return Err(format!(
                    "help-panel-{columns}x{rows}: observed composer_y={}, expected {}",
                    state["composer_y"],
                    rows - 2
                ));
            }
            observations.push(json!({"columns": columns, "rows": rows, "panel": state}));
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 0 }) {
            return Err(format!("cleanup: unexpected exit status: {exit_status:?}"));
        }
        let slave = RetainedSlave::retain(&slave_path).map_err(|error| error.to_string())?;
        let flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        let raw = output.as_slice();
        if !find_sequence(raw, b"\x1b[?1049l") || !flags.canonical || !flags.echo {
            return Err(format!("cleanup-terminal: terminal restoration failed: {flags:?}"));
        }
        Ok(json!({
            "id": "configured-help-resize",
            "status": "passed",
            "input": [
                {"kind": "text", "value": "/help", "bytes_hex": "2f 68 65 6c 70"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {"kind": "resize", "values": ["100x30", "160x50"], "meaning": "safe PTY geometry probes"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "bounded cleanup"},
            ],
            "observations": observations,
            "provider_request": "not observed; configured endpoint was an absent loopback port",
            "side_effects": "Only /help, PTY resize, and bounded Ctrl+C cleanup were exercised; no provider request or external network was used",
            "clean_exit": true,
            "terminal_restored": {
                "canonical": flags.canonical,
                "echo": flags.echo,
            },
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child.child);
    }
    let _ = fs::remove_dir_all(&root);
    result
}

fn find_sequence(haystack: &[u8], needle: &[u8]) -> bool {
    haystack.windows(needle.len()).any(|window| window == needle)
}

fn write_report(report: &Value, path: Option<&Path>) -> ExitCode {
    let mut text = serde_json::to_string_pretty(report).expect("serialize report");
    text.push('\n');
    if let Some(path) = path {
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        use std::io::Write;
        if let Ok(mut file) = fs::File::create(path) {
            let _ = file.write_all(text.as_bytes());
        }
    }
    print!("{text}");
    if report.get("passed").and_then(Value::as_bool) == Some(true) {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

fn main() -> ExitCode {
    let mut args = std::env::args().skip(1);
    let mut binary = PathBuf::from("target/debug/hades");
    let mut report_path: Option<PathBuf> = None;
    let mut timeout = Duration::from_secs_f64(60.0);

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
                    timeout = Duration::from_secs_f64(value.parse().unwrap_or(60.0));
                }
            }
            _ => {}
        }
    }

    let binary = binary.canonicalize().unwrap_or_else(|_| binary.clone());
    let mut report = json!({
        "schema_version": 1,
        "observation_id": "OBS-0103",
        "contract_observation": "OBS-0102",
        "reference": {
            "product": "Hermes TUI",
            "version": "0.19.1 (2026.7.30)",
            "source_commit": "e444d165807f489b5c1ab8e4a612c8d09c2e67a2",
            "terminal": {
                "initial_columns": COLUMNS,
                "initial_rows": ROWS,
                "resize_cases": ["100x30", "160x50"],
                "emulator": "direct PTY with normalized ANSI screen geometry",
            },
            "capture": "Hades configured /help resize replay against OBS-0102",
        },
        "normalization": [
            "Binary paths, synthetic HOME/HERMES_HOME paths, loopback ports, timestamps, ANSI redraw bytes, and runtime identifiers are omitted or represented by stable markers.",
            "The configured endpoint is an absent loopback port; the replay must not issue a provider request or use credentials.",
            "The oracle checks only the observed Help geometry, composer retention, process liveness, and Ctrl+C terminal cleanup at the three requested sizes.",
            "Minimum-size clipping, focus/navigation, repeated-help behavior, dynamic catalog behavior, and provider behavior remain unknown.",
        ],
        "steps": [],
        "unknowns": [
            "Only the OBS-0102 120x40, 100x30, and 160x50 geometry boundaries are claimed.",
            "No provider request, credential, OAuth flow, external network, or side-effecting command was exercised.",
        ],
        "passed": false,
    });
    if !binary.is_file() {
        report["failure"] = json!({"case": "precondition", "step": "binary", "message": format!("Hades binary does not exist: {}", binary.display())});
        return write_report(&report, report_path.as_deref());
    }

    match run_case(&binary, timeout) {
        Ok(result) => {
            report["steps"] = json!([{
                "id": result["id"],
                "precondition": "Fresh configured Hades process at 120x40 with an absent loopback endpoint and no credentials.",
                "input_sequence": result["input"],
                "output": result,
            }]);
            report["passed"] = json!(true);
            write_report(&report, report_path.as_deref())
        }
        Err(error) => {
            report["failure"] = json!({"case": "runtime", "step": "report", "message": error});
            write_report(&report, report_path.as_deref())
        }
    }
}
