//! `hades-dev replay-configured-help-lifecycle` — Rust port of
//! `scripts/replay_configured_help_lifecycle.py` (HAD-149).
//!
//! Replays the configured /help Escape lifecycle against the OBS-0100
//! contract: /help opens the stable bordered panel, Escape preserves the
//! panel and the /help composer while keeping the process alive, and a
//! clean Ctrl+C exit restores the terminal.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{Duration, Instant};

use hades_dev::pty::read_available;
use hades_dev::replay::{
    ExitStatus, RetainedSlave, marker_present, spawn_with_env, terminal_flags, try_wait, wait_for,
    wait_for_exit,
};
use hades_dev::screen::Screen;
use serde_json::{Value, json};

const COLUMNS: u16 = 120;
const ROWS: u16 = 40;
const HELP_COMMAND: &str = "/help Show available commands";
const HELP_TOP_BORDER: &str = concat!(
    "╔",
    "════════════════════════════════════════════════════════════════════════════════════════════════════════════════════",
    "╗"
);
const HELP_BOTTOM_BORDER: &str = concat!(
    "╚",
    "════════════════════════════════════════════════════════════════════════════════════════════════════════════════════",
    "╝"
);
const MAIN_SURFACE_MARKERS: [&str; 4] =
    ["Hades Agent", "Available Tools", "Available Skills", "/help for commands"];

fn screen_lines(raw: &[u8]) -> Vec<String> {
    let mut screen = Screen::new(COLUMNS as usize, ROWS as usize);
    screen.feed(raw);
    screen.lines().into_iter().map(|line| line.trim_end().to_owned()).collect()
}

fn help_state(raw: &[u8]) -> Option<Value> {
    let lines = screen_lines(raw);
    let command_index = lines.iter().position(|line| line.contains("Show available commands"))?;
    if command_index == 0 || command_index + 1 >= lines.len() {
        return None;
    }
    let top = lines[command_index - 1].trim().to_owned();
    let bottom = lines[command_index + 1].trim().to_owned();
    let composer =
        lines.iter().find(|line| line.contains("❯ /help")).map(|line| line.trim().to_owned());
    if top != HELP_TOP_BORDER
        || bottom != HELP_BOTTOM_BORDER
        || composer.as_deref() != Some("❯ /help")
    {
        return None;
    }
    Some(json!({
        "top_border": top,
        "command": HELP_COMMAND,
        "bottom_border": bottom,
        "composer": composer,
    }))
}

fn wait_for_stable_help(
    child: &hades_dev::replay::ReplayChild,
    output: &mut Vec<u8>,
    timeout: Duration,
) -> Result<(Value, usize), String> {
    let deadline = Instant::now() + timeout;
    let mut previous: Option<String> = None;
    let mut stable_samples = 0;
    while Instant::now() < deadline {
        output.extend_from_slice(&read_available(&child.child.master));
        if let Some(state) = help_state(output) {
            let signature = serde_json::to_string(&state).expect("serialize help state");
            if previous.as_deref() == Some(signature.as_str()) {
                stable_samples += 1;
            } else {
                previous = Some(signature);
                stable_samples = 1;
            }
            if stable_samples >= 3 {
                return Ok((state, stable_samples));
            }
        } else {
            previous = None;
            stable_samples = 0;
        }
        if try_wait(&child.child)?.is_some() {
            return Err("Hades exited before the help panel stabilized".to_owned());
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    Err(format!("timed out after {:.1}s waiting for the exact help panel", timeout.as_secs_f64()))
}

fn read_for(child: &hades_dev::replay::ReplayChild, output: &mut Vec<u8>, duration: Duration) {
    let deadline = Instant::now() + duration;
    while Instant::now() < deadline {
        output.extend_from_slice(&read_available(&child.child.master));
        if try_wait(&child.child).ok().flatten().is_some() {
            return;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}

fn run_case(binary: &Path, timeout: Duration) -> Result<Value, String> {
    let root = std::env::temp_dir()
        .join(format!("hades-configured-help-lifecycle-{}", std::process::id()));
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
            |text| marker_present(text, "Hades Agent") && marker_present(text, "ready"),
            timeout,
        )?;

        hades_dev::replay::send(&child.child.master, b"/help\r")
            .map_err(|error| error.to_string())?;
        let (before, stable_samples) = wait_for_stable_help(&child, &mut output, timeout)?;

        let lines = screen_lines(&output);
        for marker in MAIN_SURFACE_MARKERS {
            if !lines.iter().any(|line| marker_present(line, marker)) {
                return Err(format!(
                    "before-escape surface: stable help surface lost a main marker: {marker}"
                ));
            }
        }

        hades_dev::replay::send(&child.child.master, b"\x1b").map_err(|error| error.to_string())?;
        read_for(&child, &mut output, Duration::from_millis(500));
        let after = help_state(&output).ok_or_else(|| {
            "after-escape help-panel: Escape did not preserve the stable help panel".to_owned()
        })?;
        if try_wait(&child.child)?.is_some() {
            return Err("after-escape lifecycle: Escape exited the ready Hades process".to_owned());
        }
        if after.get("composer").and_then(Value::as_str) != Some("❯ /help") {
            return Err(
                "after-escape composer: Escape did not preserve the /help composer".to_owned()
            );
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 0 }) {
            return Err(format!("cleanup exit: unexpected exit status: {exit_status:?}"));
        }
        let slave = RetainedSlave::retain(&slave_path).map_err(|error| error.to_string())?;
        let flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        let raw = output.as_slice();
        if !find_sequence(raw, b"\x1b[?1049l") || !flags.canonical || !flags.echo {
            return Err(format!("cleanup terminal: terminal restoration failed: {flags:?}"));
        }
        Ok(json!({
            "id": "configured-help-escape-lifecycle",
            "status": "passed",
            "input": [
                {"kind": "text", "value": "/help", "bytes_hex": "2f 68 65 6c 70"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {"kind": "key", "value": "Escape", "bytes_hex": "1b", "meaning": "safe lifecycle probe"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03", "meaning": "bounded cleanup"},
            ],
            "before_escape": {"help_panel": before, "stable_samples": stable_samples, "state": "ready"},
            "after_escape": {
                "help_panel_preserved": true,
                "composer_preserved": true,
                "process_alive_before_cleanup": true,
            },
            "provider_request": "not observed; configured endpoint was an absent loopback port",
            "side_effects": "Only /help, Escape, and bounded Ctrl+C cleanup were exercised; no provider request or external network was used",
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
        "observation_id": "OBS-0101",
        "contract_observation": "OBS-0100",
        "reference": {
            "product": "Hermes TUI",
            "version": "0.19.1 (2026.7.30)",
            "source_commit": "e444d165807f489b5c1ab8e4a612c8d09c2e67a2",
            "terminal": {
                "columns": COLUMNS,
                "rows": ROWS,
                "emulator": "direct PTY with normalized stable landmarks",
            },
            "capture": "Hades configured /help Escape lifecycle replay against OBS-0100",
        },
        "normalization": [
            "Binary paths, synthetic HOME/HERMES_HOME paths, loopback ports, timestamps, ANSI redraw bytes, and runtime identifiers are omitted or represented by stable markers.",
            "The configured endpoint is an absent loopback port; the replay must not issue a provider request or use credentials.",
            "The oracle checks only the OBS-0100 stable help panel/composer preservation, live process boundary, and Ctrl+C cleanup.",
            "Other focus, navigation, close, repeated-help, catalog, and dynamic inventory behavior remains unknown.",
        ],
        "steps": [],
        "unknowns": [
            "The complete slash-command catalog, aliases, arguments, command-specific state, and help pagination remain unknown.",
            "Provider/tool/skill counts, discovery timing, redraw ordering, and dynamic command inventory remain outside this lifecycle boundary.",
            "Only the observed Escape preservation and Ctrl+C cleanup route are claimed.",
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
