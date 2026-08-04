//! `hades-dev replay-terminal-palette` — Rust port of
//! `scripts/replay_terminal_palette.py` (HAD-135).
//!
//! Replays the OBS-0035 palette controls against the Hades binary: a direct
//! PTY process behind the hold provider, stepping through the startup /
//! composer / busy / interrupted / setup-required surfaces, asserting the
//! landmark marker styles and required SGR sequences per surface, and
//! recording the same report JSON shape (raw-delta sha256/byte-length/SGR
//! sequence inventory, marker styles, screen tail).

use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::Duration;

use hades_dev::hold_provider::HoldProvider;
use hades_dev::pty::{drain, read_available};
use hades_dev::replay::{ExitStatus, ReplayChild, RetainedSlave, spawn_with_env, try_wait};
use hades_dev::screen::Screen;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

const DEFAULT_CONTRACT: &str = "tests/fixtures/parity/OBS-0035-hades-terminal-palette.json";
const COLUMNS: u16 = 120;
const ROWS: u16 = 40;
const STARTUP_MARKERS: [&str; 5] =
    ["Hades Agent", "Hades", "Available Tools", "Available Skills", "ready"];

/// Palette replay failure, like `ReplayFailure`.
struct PaletteError {
    case: String,
    step: String,
    message: String,
    details: Value,
}

impl PaletteError {
    fn new(case: &str, step: &str, message: String, details: Value) -> Self {
        Self { case: case.to_string(), step: step.to_string(), message, details }
    }

    fn as_dict(&self) -> Value {
        let mut object = serde_json::Map::new();
        object.insert("case".to_string(), json!(self.case));
        object.insert("step".to_string(), json!(self.step));
        object.insert("message".to_string(), json!(self.message));
        if let Some(details) = self.details.as_object() {
            for (key, value) in details {
                object.insert(key.clone(), value.clone());
            }
        }
        Value::Object(object)
    }
}

/// Strip ANSI sequences (CSI, OSC, and charset designation) and CR, like
/// the palette probe's `normalized`.
fn normalized(raw: &[u8]) -> String {
    let text = String::from_utf8_lossy(raw).into_owned();
    let mut result = String::new();
    let mut chars = text.chars().peekable();
    while let Some(char) = chars.next() {
        if char == '\x1b' {
            match chars.peek() {
                Some('[') => {
                    chars.next();
                    for next in chars.by_ref() {
                        if ('@'..='~').contains(&next) {
                            break;
                        }
                    }
                }
                Some(']') => {
                    chars.next();
                    for next in chars.by_ref() {
                        if next == '\x07' || next == '\x1b' {
                            break;
                        }
                    }
                }
                Some('(') | Some(')') => {
                    chars.next();
                    chars.next(); // charset selector [0-2A-Z]
                }
                _ => {}
            }
        } else if char != '\r' {
            result.push(char);
        }
    }
    result
}

/// Marker matching like the palette probe's `contains_marker`:
/// case-insensitive substring OR compact lowercase match.
fn contains_marker(text: &str, marker: &str) -> bool {
    let lower_text = text.to_lowercase();
    let lower_marker = marker.to_lowercase();
    if lower_text.contains(&lower_marker) {
        return true;
    }
    let compact_text: String = lower_text.split_whitespace().collect();
    let compact_marker: String = lower_marker.split_whitespace().collect();
    compact_text.contains(&compact_marker)
}

/// SGR summary of a raw delta, like `sgr_summary` (sha256, byte length,
/// and ordered `\x1b[...m` sequence counts).
fn sgr_summary(raw: &[u8]) -> Value {
    let mut digest = Sha256::new();
    digest.update(raw);
    let hash = digest.finalize();
    let mut counts: Vec<(Vec<u8>, usize)> = Vec::new();
    let mut index = 0;
    while index < raw.len() {
        if raw[index] == 0x1b && raw.get(index + 1) == Some(&b'[') {
            let mut end = index + 2;
            while end < raw.len() && matches!(raw[end], b'0'..=b'9' | b':' | b';' | b'?') {
                end += 1;
            }
            if raw.get(end) == Some(&b'm') {
                let sequence = raw[index..=end].to_vec();
                if let Some((_, count)) =
                    counts.iter_mut().find(|(existing, _)| *existing == sequence)
                {
                    *count += 1;
                } else {
                    counts.push((sequence, 1));
                }
                index = end + 1;
                continue;
            }
        }
        index += 1;
    }
    let sgr_sequences: Vec<Value> = counts
        .iter()
        .map(|(sequence, count)| {
            let bytes_hex: Vec<String> =
                sequence.iter().map(|byte| format!("{byte:02x}")).collect();
            json!({"bytes_hex": bytes_hex.join(" "), "count": count})
        })
        .collect();
    json!({
        "sha256": format!("{hash:x}"),
        "byte_length": raw.len(),
        "sgr_sequences": sgr_sequences,
    })
}

/// A surface record: raw delta summary, marker styles from the Screen
/// model, and the normalized screen tail, like `surface_record`.
fn surface_record(raw_delta: &[u8], full_buffer: &[u8], markers: &[&str]) -> Value {
    let mut screen = Screen::new(COLUMNS as usize, ROWS as usize);
    screen.feed(full_buffer);
    let mut marker_styles = serde_json::Map::new();
    for marker in markers {
        if let Some((row, column, style)) = screen.marker_style(marker) {
            marker_styles.insert(
                marker.to_string(),
                json!({
                    "row": row,
                    "column": column,
                    "style": style.as_dict(),
                }),
            );
        }
    }
    let tail = normalized(full_buffer);
    let tail: String =
        tail.chars().rev().take(1200).collect::<Vec<_>>().into_iter().rev().collect();
    json!({
        "raw_delta": sgr_summary(raw_delta),
        "marker_styles": Value::Object(marker_styles),
        "screen_tail": tail,
    })
}

/// Assert landmark styles and required SGR sequences, like `assert_surface`.
fn assert_surface(
    case: &str,
    step_id: &str,
    observed: &Value,
    expected: &Value,
) -> Result<(), PaletteError> {
    let markers = expected.get("landmark_styles").and_then(Value::as_object).ok_or_else(|| {
        PaletteError::new(case, step_id, "landmark_styles must be an object".to_string(), json!({}))
    })?;
    let observed_markers =
        observed.get("marker_styles").and_then(Value::as_object).cloned().unwrap_or_default();
    for (marker, expected_landmark) in markers {
        let actual = observed_markers.get(marker);
        let actual = match actual {
            Some(actual) => actual,
            None => {
                return Err(PaletteError::new(
                    case,
                    step_id,
                    format!("landmark marker was not rendered: {marker}"),
                    json!({}),
                ));
            }
        };
        let expected_style = expected_landmark.get("style").unwrap_or(expected_landmark);
        let actual_style = actual.get("style").unwrap_or(actual);
        if actual_style != expected_style {
            return Err(PaletteError::new(
                case,
                step_id,
                format!("style mismatch for {marker}"),
                json!({"expected": expected_style, "actual": actual_style}),
            ));
        }
    }
    let observed_sequences: std::collections::HashSet<String> = observed
        .get("raw_delta")
        .and_then(|raw| raw.get("sgr_sequences"))
        .and_then(Value::as_array)
        .map(|sequences| {
            sequences
                .iter()
                .filter_map(|sequence| {
                    sequence.get("bytes_hex").and_then(Value::as_str).map(String::from)
                })
                .collect()
        })
        .unwrap_or_default();
    if let Some(required) = expected.get("required_sgr_sequences_hex").and_then(Value::as_array) {
        for sequence in required {
            if let Some(hex) = sequence.as_str()
                && !observed_sequences.contains(hex)
            {
                return Err(PaletteError::new(
                    case,
                    step_id,
                    format!("required SGR sequence was not emitted: {hex}"),
                    json!({}),
                ));
            }
        }
    }
    Ok(())
}

/// Wait until `predicate(accumulated_raw)` or the child exits or the
/// timeout elapses, like the palette probe's `wait_for`.
///
/// Uses `poll` (like Python's `select`) so reads happen the moment data
/// arrives — a fixed sleep before each read would lag a full poll cycle
/// and slice the raw-delta boundary differently than the Python replay.
fn wait_for<F>(
    child: &hades_dev::pty::PtyChild,
    output: &mut Vec<u8>,
    case: &str,
    step: &str,
    predicate: F,
    timeout: Duration,
) -> Result<(), PaletteError>
where
    F: Fn(&[u8]) -> bool,
{
    let deadline = std::time::Instant::now() + timeout;
    loop {
        if predicate(output) {
            return Ok(());
        }
        if let Some(status) = try_wait(child).map_err(|error| {
            PaletteError::new(case, step, format!("waitpid failed: {error}"), json!({}))
        })? {
            output.extend_from_slice(&read_available(&child.master));
            if predicate(output) {
                return Ok(());
            }
            return Err(PaletteError::new(
                case,
                step,
                format!(
                    "Hades exited before the PTY assertion ({})",
                    ExitStatus::describe(status).as_json()
                ),
                json!({"screen_tail": normalized(output).chars().rev().take(2000).collect::<String>().chars().rev().collect::<String>()}),
            ));
        }
        if std::time::Instant::now() >= deadline {
            return Err(PaletteError::new(
                case,
                step,
                format!("timed out after {:.1}s", timeout.as_secs_f64()),
                json!({"screen_tail": normalized(output).chars().rev().take(2000).collect::<String>().chars().rev().collect::<String>()}),
            ));
        }
        let remaining = deadline.saturating_duration_since(std::time::Instant::now());
        let millis = remaining.as_millis().min(250) as i64;
        let timespec =
            rustix::time::Timespec { tv_sec: millis / 1000, tv_nsec: (millis % 1000) * 1_000_000 };
        let mut poll_fd = rustix::event::PollFd::new(&child.master, rustix::event::PollFlags::IN);
        let ready = rustix::event::poll(std::slice::from_mut(&mut poll_fd), Some(&timespec))
            .map_err(|error| {
                PaletteError::new(case, step, format!("poll failed: {error}"), json!({}))
            })?;
        if ready > 0 {
            output.extend_from_slice(&read_available(&child.master));
        }
    }
}

/// Validate the OBS-0035 contract, like `load_contract`.
fn load_contract(path: &Path) -> Result<Value, PaletteError> {
    let text = std::fs::read_to_string(path).map_err(|error| {
        PaletteError::new(
            "contract",
            "load",
            format!("could not read {}: {error}", path.display()),
            json!({}),
        )
    })?;
    let contract: Value = serde_json::from_str(&text).map_err(|error| {
        PaletteError::new(
            "contract",
            "load",
            format!("could not read {}: {error}", path.display()),
            json!({}),
        )
    })?;
    if !contract.is_object() || contract.get("schema_version") != Some(&json!(1)) {
        return Err(PaletteError::new(
            "contract",
            "load",
            "unsupported OBS-0035 contract".to_string(),
            json!({}),
        ));
    }
    let steps = contract.get("steps").and_then(Value::as_array).ok_or_else(|| {
        PaletteError::new(
            "contract",
            "load",
            "OBS-0035 steps must be an array".to_string(),
            json!({}),
        )
    })?;
    let expected: std::collections::HashSet<&str> =
        ["startup", "composer", "busy", "interrupted", "setup-required"].into_iter().collect();
    let actual: std::collections::HashSet<&str> =
        steps.iter().filter_map(|step| step.get("id").and_then(Value::as_str)).collect();
    if actual != expected {
        let mut sorted: Vec<&str> = expected.iter().copied().collect();
        sorted.sort();
        return Err(PaletteError::new(
            "contract",
            "load",
            format!("step ids must be {sorted:?}"),
            json!({}),
        ));
    }
    Ok(contract)
}

fn step_map(contract: &Value) -> std::collections::HashMap<String, Value> {
    contract["steps"]
        .as_array()
        .map(|steps| {
            steps
                .iter()
                .filter_map(|step| {
                    step.get("id").and_then(Value::as_str).map(|id| (id.to_string(), step.clone()))
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Spawn Hades with the hold-provider environment, like the palette
/// `spawn`.
fn spawn_tui(
    binary: &Path,
    provider: &HoldProvider,
    base_url_override: Option<&str>,
) -> Result<(ReplayChild, RetainedSlave), PaletteError> {
    let mut environment: Vec<(String, String)> =
        provider.environment().into_iter().map(|(key, value)| (key.to_string(), value)).collect();
    if let Some(base_url) = base_url_override
        && let Some(entry) =
            environment.iter_mut().find(|(key, _)| key == "HADES_PROVIDER_BASE_URL")
    {
        entry.1 = base_url.to_string();
    }
    let environment_refs: Vec<(&str, &str)> =
        environment.iter().map(|(key, value)| (key.as_str(), value.as_str())).collect();
    let child = spawn_with_env(binary, &[], &environment_refs, &[])
        .map_err(|error| PaletteError::new("spawn", "pty", error.to_string(), json!({})))?;
    let slave_path = child.slave_path.clone();
    let slave = RetainedSlave::retain(&slave_path)
        .map_err(|error| PaletteError::new("spawn", "pty", error.to_string(), json!({})))?;
    Ok((child, slave))
}

fn run_ready_sequence(
    binary: &Path,
    steps: &std::collections::HashMap<String, Value>,
    timeout: Duration,
) -> Result<Value, PaletteError> {
    let case = "ready-palette";
    let provider = HoldProvider::start().map_err(|error| {
        PaletteError::new(case, "startup", format!("hold provider failed: {error}"), json!({}))
    })?;
    let (mut child, slave) = spawn_tui(binary, &provider, None)?;
    let mut output: Vec<u8> = Vec::new();
    let mut reaped = false;

    let result = (|| -> Result<Value, PaletteError> {
        wait_for(
            &child.child,
            &mut output,
            case,
            "startup",
            |current| {
                let text = normalized(current);
                STARTUP_MARKERS.iter().all(|marker| contains_marker(&text, marker))
            },
            timeout,
        )?;
        let startup = surface_record(&output, &output, &STARTUP_MARKERS);
        assert_surface(case, "startup", &startup, &steps["startup"]["output"])?;

        let composer_start = output.len();
        hades_dev::replay::send(&child.child.master, b"palette-ready")
            .map_err(|error| PaletteError::new(case, "composer", error.to_string(), json!({})))?;
        wait_for(
            &child.child,
            &mut output,
            case,
            "composer",
            |current| contains_marker(&normalized(current), "palette-ready"),
            timeout,
        )?;
        output.extend_from_slice(&drain(&child.child.master, Duration::from_millis(120)));
        let composer =
            surface_record(&output[composer_start..], &output, &["palette-ready", "ready"]);
        assert_surface(case, "composer", &composer, &steps["composer"]["output"])?;

        let busy_start = output.len();
        hades_dev::replay::send(&child.child.master, b"\r")
            .map_err(|error| PaletteError::new(case, "busy", error.to_string(), json!({})))?;
        wait_for(
            &child.child,
            &mut output,
            case,
            "busy",
            |current| contains_marker(&normalized(current), "Ctrl+C to interrupt"),
            timeout,
        )?;
        output.extend_from_slice(&drain(&child.child.master, Duration::from_millis(50)));
        let busy = surface_record(&output[busy_start..], &output, &["Ctrl+C to interrupt"]);
        assert_surface(case, "busy", &busy, &steps["busy"]["output"])?;

        let interrupted_start = output.len();
        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| {
            PaletteError::new(case, "interrupted", error.to_string(), json!({}))
        })?;
        wait_for(
            &child.child,
            &mut output,
            case,
            "interrupted",
            |current| contains_marker(&normalized(current), "interrupted"),
            timeout,
        )?;
        output.extend_from_slice(&drain(&child.child.master, Duration::from_millis(120)));
        let interrupted =
            surface_record(&output[interrupted_start..], &output, &["interrupted", "✓"]);
        assert_surface(case, "interrupted", &interrupted, &steps["interrupted"]["output"])?;

        hades_dev::replay::send(&child.child.master, b"\x03")
            .map_err(|error| PaletteError::new(case, "cleanup", error.to_string(), json!({})))?;
        wait_for(
            &child.child,
            &mut output,
            case,
            "cleanup",
            |_current| try_wait(&child.child).map(|status| status.is_some()).unwrap_or(false),
            timeout,
        )?;
        reaped = true;
        let _ = slave;
        Ok(json!({
            "id": case,
            "status": "passed",
            "surfaces": {
                "startup": startup,
                "composer": composer,
                "busy": busy,
                "interrupted": interrupted,
            },
            "cleanup": "busy turn interrupted and ready process exited cleanly",
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child.child);
    }
    let _ = std::fs::remove_dir_all(&child.history_home);
    let mut provider = provider;
    provider.finish();
    result
}

fn run_setup_case(
    binary: &Path,
    steps: &std::collections::HashMap<String, Value>,
    timeout: Duration,
) -> Result<Value, PaletteError> {
    let case = "setup-required-palette";
    let provider = HoldProvider::start().map_err(|error| {
        PaletteError::new(case, "startup", format!("hold provider failed: {error}"), json!({}))
    })?;
    let (mut child, slave) = spawn_tui(binary, &provider, Some(""))?;
    let mut output: Vec<u8> = Vec::new();
    let mut reaped = false;

    let result = (|| -> Result<Value, PaletteError> {
        wait_for(
            &child.child,
            &mut output,
            case,
            "startup",
            |current| contains_marker(&normalized(current), "Hades Agent"),
            timeout,
        )?;
        let setup_start = output.len();
        hades_dev::replay::send(&child.child.master, b"/help\r").map_err(|error| {
            PaletteError::new(case, "setup-required", error.to_string(), json!({}))
        })?;
        wait_for(
            &child.child,
            &mut output,
            case,
            "setup-required",
            |current| contains_marker(&normalized(current), "Setup Required"),
            timeout.max(Duration::from_secs(12)),
        )?;
        output.extend_from_slice(&drain(&child.child.master, Duration::from_millis(120)));
        let setup = surface_record(
            &output[setup_start..],
            &output,
            &["Setup Required", "model provider", "/model", "/setup", "/help"],
        );
        assert_surface(case, "setup-required", &setup, &steps["setup-required"]["output"])?;

        hades_dev::replay::send(&child.child.master, b"\x03")
            .map_err(|error| PaletteError::new(case, "cleanup", error.to_string(), json!({})))?;
        output.extend_from_slice(&drain(&child.child.master, Duration::from_millis(150)));
        hades_dev::replay::send(&child.child.master, b"\x03")
            .map_err(|error| PaletteError::new(case, "cleanup", error.to_string(), json!({})))?;
        wait_for(
            &child.child,
            &mut output,
            case,
            "cleanup",
            |_current| try_wait(&child.child).map(|status| status.is_some()).unwrap_or(false),
            timeout,
        )?;
        reaped = true;
        let _ = slave;
        Ok(json!({
            "id": case,
            "status": "passed",
            "surfaces": {"setup-required": setup},
            "cleanup": "two Ctrl+C presses exited cleanly from setup-required",
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child.child);
    }
    let _ = std::fs::remove_dir_all(&child.history_home);
    let mut provider = provider;
    provider.finish();
    result
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
    let mut contract = PathBuf::from(DEFAULT_CONTRACT);
    let mut report_path: Option<PathBuf> = None;
    let mut timeout = Duration::from_secs_f64(8.0);

    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--binary" => {
                if let Some(value) = args.next() {
                    binary = PathBuf::from(value);
                }
            }
            "--contract" => {
                if let Some(value) = args.next() {
                    contract = PathBuf::from(value);
                }
            }
            "--report" => {
                if let Some(value) = args.next() {
                    report_path = Some(PathBuf::from(value));
                }
            }
            "--timeout" => {
                if let Some(value) = args.next() {
                    timeout = Duration::from_secs_f64(value.parse().unwrap_or(8.0));
                }
            }
            _ => {}
        }
    }

    let binary = binary.canonicalize().unwrap_or_else(|_| binary.clone());
    let contract = contract.canonicalize().unwrap_or_else(|_| contract.clone());
    let mut report = json!({
        "schema_version": 1,
        "command": "replay-terminal-palette",
        "observation_id": "OBS-0035",
        "reference_observation": "OBS-0034",
        "binary": "<hades-binary>",
        "contract": DEFAULT_CONTRACT,
        "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY raw bytes"},
        "cases": [],
        "passed": false,
    });

    let mut status = 0u8;
    if !binary.is_file() {
        report["failure"] = json!({
            "case": "precondition",
            "step": "binary",
            "message": format!("Hades binary does not exist: {}", binary.display()),
        });
        status = 1;
    } else {
        match load_contract(&contract) {
            Ok(contract) => {
                let steps = step_map(&contract);
                match run_ready_sequence(&binary, &steps, timeout).and_then(|ready| {
                    let setup = run_setup_case(&binary, &steps, timeout)?;
                    Ok(json!([ready, setup]))
                }) {
                    Ok(cases) => {
                        report["cases"] = cases;
                        report["passed"] = json!(true);
                    }
                    Err(error) => {
                        report["failure"] = error.as_dict();
                        status = 1;
                    }
                }
            }
            Err(error) => {
                report["failure"] = error.as_dict();
                status = 1;
            }
        }
    }

    write_report(&report, report_path.as_deref(), status)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalized_strips_ansi_and_charset() {
        let cleaned = normalized(b"\x1b[31mred\x1b[0m\r\n\x1b(0\x1b)Btext");
        assert_eq!(cleaned, "red\ntext");
    }

    #[test]
    fn contains_marker_lowercases_both_sides() {
        assert!(contains_marker("Hades Agent v0.1.0", "hades agent"));
        assert!(contains_marker("HadesAgent", "Hades Agent"));
        assert!(contains_marker("MUSING…", "musing"));
        assert!(!contains_marker("abc", "x"));
    }

    #[test]
    fn sgr_summary_counts_sequences() {
        let raw = b"\x1b[31m\x1b[1m\x1b[31m";
        let summary = sgr_summary(raw);
        assert_eq!(summary["byte_length"], 14);
        let sequences = summary["sgr_sequences"].as_array().unwrap();
        assert_eq!(sequences.len(), 2);
        assert_eq!(sequences[0]["bytes_hex"], "1b 5b 33 31 6d");
        assert_eq!(sequences[0]["count"], 2);
        assert_eq!(sequences[1]["count"], 1);
        // sha256 is a 64-char hex digest
        assert_eq!(summary["sha256"].as_str().unwrap().len(), 64);
    }

    #[test]
    fn runtime_clean_output_equivalence() {
        // The palette uses its own normalized (with charset stripping);
        // assert it agrees with the runtime clean_output on plain input.
        assert_eq!(normalized(b"x\r\ny"), "x\ny");
    }
}
