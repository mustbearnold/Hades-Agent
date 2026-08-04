//! `hades-dev replay-modified-enter` — Rust port of
//! `scripts/replay_modified_enter.py` (HAD-145).
//!
//! Replays the modified-Enter input contract (OBS-0021) against Hades in a
//! direct 120x40 PTY with the hold-provider loopback: shift-Enter and
//! alt-Enter produce a submission from the ready state, while plain Enter
//! in an empty composer does not submit. Input events arrive as raw hex
//! byte payloads; the replay asserts screen markers, then interrupts and
//! exits.

use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{Duration, Instant};

use hades_dev::hold_provider::HoldProvider;
use hades_dev::pty::{drain, read_available};
use hades_dev::replay::{ReplayChild, RetainedSlave, spawn_with_env, try_wait};
use serde_json::{Value, json};

/// Modified-Enter replay failure, mirroring `ModifiedEnterReplayFailure`.
struct ModifiedEnterError {
    case: String,
    step: String,
    message: String,
    details: Value,
}

impl ModifiedEnterError {
    fn new(case: &str, step: &str, message: String) -> Self {
        Self { case: case.to_string(), step: step.to_string(), message, details: json!({}) }
    }

    fn with_screen(case: &str, step: &str, message: String, screen: &str) -> Self {
        let tail: Vec<&str> = screen.lines().rev().take(40).collect();
        let tail = tail.iter().rev().cloned().collect::<Vec<_>>().join("\n");
        Self {
            case: case.to_string(),
            step: step.to_string(),
            message,
            details: json!({"screen_tail": tail}),
        }
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

/// Strip ANSI escapes + CR like the probe's `normalize` (the modified-enter
/// replay uses the tui_lifecycle clean output semantics).
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

fn contains_marker(text: &str, marker: &str) -> bool {
    let compact_text = text.split_whitespace().collect::<String>().to_lowercase();
    let compact_marker = marker.split_whitespace().collect::<String>().to_lowercase();
    text.to_lowercase().contains(&marker.to_lowercase()) || compact_text.contains(&compact_marker)
}

/// Poll-based wait (like Python's select loop): returns the accumulated
/// buffer once `predicate` holds, or the child exits, or the timeout runs
/// out.
fn wait_for<F>(
    child: &hades_dev::pty::PtyChild,
    output: &mut Vec<u8>,
    case: &str,
    step: &str,
    predicate: F,
    timeout: Duration,
) -> Result<(), ModifiedEnterError>
where
    F: Fn(&[u8]) -> bool,
{
    let deadline = Instant::now() + timeout;
    loop {
        if predicate(output) {
            return Ok(());
        }
        if let Some(_status) = try_wait(child).map_err(|error| {
            ModifiedEnterError::new(case, step, format!("waitpid failed: {error}"))
        })? {
            return Err(ModifiedEnterError::with_screen(
                case,
                step,
                "process exited during wait".to_string(),
                &normalized(output),
            ));
        }
        if Instant::now() >= deadline {
            return Err(ModifiedEnterError::with_screen(
                case,
                step,
                format!("timed out after {:.1}s", timeout.as_secs_f64()),
                &normalized(output),
            ));
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        let millis = remaining.as_millis().min(250) as i64;
        let timespec =
            rustix::time::Timespec { tv_sec: millis / 1000, tv_nsec: (millis % 1000) * 1_000_000 };
        let mut poll_fd = rustix::event::PollFd::new(&child.master, rustix::event::PollFlags::IN);
        let ready = rustix::event::poll(std::slice::from_mut(&mut poll_fd), Some(&timespec))
            .map_err(|error| {
                ModifiedEnterError::new(case, step, format!("poll failed: {error}"))
            })?;
        if ready > 0 {
            output.extend_from_slice(&read_available(&child.master));
        }
    }
}

/// Like `wait_for`, but the predicate receives the RENDERED screen text
/// (rebuilt via the Screen emulator) instead of the raw byte stream. The
/// animated startup logo emits interleaved sparse-redraw cell writes that
/// fragment typed text in the raw stream; the reconstructed screen — the
/// view a real terminal shows — keeps markers contiguous.
fn wait_for_rendered<F>(
    child: &hades_dev::pty::PtyChild,
    output: &mut Vec<u8>,
    case: &str,
    step: &str,
    predicate: F,
    timeout: Duration,
) -> Result<(), ModifiedEnterError>
where
    F: Fn(&str) -> bool,
{
    let deadline = Instant::now() + timeout;
    loop {
        let mut screen = hades_dev::screen::Screen::new(120, 40);
        screen.feed(output);
        let rendered = screen.lines().join("\n");
        if predicate(&rendered) {
            return Ok(());
        }
        if let Some(_status) = try_wait(child).map_err(|error| {
            ModifiedEnterError::new(case, step, format!("waitpid failed: {error}"))
        })? {
            return Err(ModifiedEnterError::with_screen(
                case,
                step,
                "process exited during wait".to_string(),
                &normalized(output),
            ));
        }
        if Instant::now() >= deadline {
            return Err(ModifiedEnterError::with_screen(
                case,
                step,
                format!("timed out after {:.1}s", timeout.as_secs_f64()),
                &normalized(output),
            ));
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        let millis = remaining.as_millis().min(250) as i64;
        let timespec =
            rustix::time::Timespec { tv_sec: millis / 1000, tv_nsec: (millis % 1000) * 1_000_000 };
        let mut poll_fd = rustix::event::PollFd::new(&child.master, rustix::event::PollFlags::IN);
        let ready = rustix::event::poll(std::slice::from_mut(&mut poll_fd), Some(&timespec))
            .map_err(|error| {
                ModifiedEnterError::new(case, step, format!("poll failed: {error}"))
            })?;
        if ready > 0 {
            output.extend_from_slice(&read_available(&child.master));
        }
    }
}

fn write_bytes(master: &rustix::fd::OwnedFd, payload: &[u8]) -> Result<(), ModifiedEnterError> {
    let mut offset = 0;
    while offset < payload.len() {
        match rustix::io::write(master, &payload[offset..]) {
            Ok(count) => offset += count,
            Err(error) => {
                return Err(ModifiedEnterError::new(
                    "input",
                    "write",
                    format!("os.write failed: {error}"),
                ));
            }
        }
    }
    Ok(())
}

fn child_exited(child: &ReplayChild) -> bool {
    matches!(try_wait(&child.child), Ok(Some(_)))
}

/// Spawn Hades with the hold-provider environment, like `spawn`.
fn spawn_tui(
    binary: &Path,
    provider: &HoldProvider,
) -> Result<(ReplayChild, RetainedSlave), String> {
    let environment = provider.environment();
    let env_refs: Vec<(&str, &str)> =
        environment.iter().map(|(key, value)| (*key, value.as_str())).collect();
    let child = spawn_with_env(binary, &[], &env_refs, &["VISUAL", "EDITOR"])
        .map_err(|error| error.to_string())?;
    let slave_path = child.slave_path.clone();
    let slave = RetainedSlave::retain(&slave_path).map_err(|error| error.to_string())?;
    Ok((child, slave))
}

/// Validate the modified-Enter contract: schema 1 with exactly the three
/// required step ids.
fn load_contract(path: &Path) -> Result<Value, ModifiedEnterError> {
    let text = std::fs::read_to_string(path).map_err(|error| {
        ModifiedEnterError::new(
            "contract",
            "load",
            format!("could not read {}: {error}", path.display()),
        )
    })?;
    let contract: Value = serde_json::from_str(&text).map_err(|error| {
        ModifiedEnterError::new(
            "contract",
            "load",
            format!("could not read {}: {error}", path.display()),
        )
    })?;
    if !contract.is_object() || contract.get("schema_version") != Some(&json!(1)) {
        return Err(ModifiedEnterError::new(
            "contract",
            "load",
            "unsupported modified-Enter contract".to_string(),
        ));
    }
    let steps = contract.get("steps").and_then(Value::as_array);
    let ids: std::collections::BTreeSet<&str> = steps
        .map(|steps| steps.iter())
        .unwrap_or_else(|| [].iter())
        .filter_map(|step| step.get("id").and_then(Value::as_str))
        .collect();
    let required: std::collections::BTreeSet<&str> =
        ["shift-enter", "alt-enter", "plain-enter-control"].into_iter().collect();
    if ids != required {
        return Err(ModifiedEnterError::new(
            "contract",
            "load",
            format!("step ids must be {required:?}"),
        ));
    }
    Ok(contract)
}

fn input_bytes(event: &Value) -> Result<Vec<u8>, ModifiedEnterError> {
    let hex = event.get("bytes_hex").and_then(Value::as_str).ok_or_else(|| {
        ModifiedEnterError::new("contract", "input", "invalid input bytes".to_string())
    })?;
    // Like Python's bytes.fromhex: whitespace between bytes is allowed.
    let compact: String = hex.chars().filter(|ch| !ch.is_whitespace()).collect();
    if !compact.len().is_multiple_of(2) {
        return Err(ModifiedEnterError::new(
            "contract",
            "input",
            format!("invalid input bytes: {hex}"),
        ));
    }
    let mut bytes = Vec::with_capacity(compact.len() / 2);
    let mut index = 0;
    while index < compact.len() {
        match u8::from_str_radix(&compact[index..index + 2], 16) {
            Ok(byte) => bytes.push(byte),
            Err(_) => {
                return Err(ModifiedEnterError::new(
                    "contract",
                    "input",
                    format!("invalid input bytes: {hex}"),
                ));
            }
        }
        index += 2;
    }
    Ok(bytes)
}

fn run_case(
    binary: &Path,
    case: &Value,
    timeout: Duration,
    _ordinal: usize,
) -> Result<Value, ModifiedEnterError> {
    let case_id = case["id"].as_str().unwrap_or("?").to_string();
    let mut provider = HoldProvider::start().map_err(|error| {
        ModifiedEnterError::new(&case_id, "startup", format!("hold provider failed: {error}"))
    })?;
    let (mut child, _slave) = spawn_tui(binary, &provider)
        .map_err(|error| ModifiedEnterError::new(&case_id, "startup", error))?;
    let mut buffer: Vec<u8> = Vec::new();

    let result = (|| -> Result<Value, ModifiedEnterError> {
        wait_for(
            &child.child,
            &mut buffer,
            &case_id,
            "startup",
            |current| {
                ["Hades Agent", "Underworld", "Available Tools", "Available Skills"]
                    .iter()
                    .all(|marker| contains_marker(&normalized(current), marker))
            },
            timeout,
        )?;

        let input_sequence = case["input_sequence"].as_array().cloned().unwrap_or_default();
        for event in &input_sequence {
            let bytes = input_bytes(event)?;
            write_bytes(&child.child.master, &bytes)?;
            let drained = drain(&child.child.master, Duration::from_millis(120));
            buffer.extend_from_slice(&drained);
        }

        let expected = &case["output"];
        let markers: Vec<String> = expected["screen_markers"]
            .as_array()
            .map(|array| {
                array.iter().filter_map(|marker| marker.as_str().map(String::from)).collect()
            })
            .unwrap_or_default();
        let absent: Vec<String> = expected
            .get("screen_absent_markers")
            .and_then(Value::as_array)
            .map(|array| {
                array.iter().filter_map(|marker| marker.as_str().map(String::from)).collect()
            })
            .unwrap_or_default();

        let step_name =
            if case_id == "plain-enter-control" { "plain-enter" } else { "modified-enter" };
        wait_for_rendered(
            &child.child,
            &mut buffer,
            &case_id,
            step_name,
            |text| markers.iter().all(|marker| contains_marker(text, marker)),
            timeout,
        )?;
        let screen = normalized(&buffer);
        for marker in &absent {
            if contains_marker(&screen, marker) {
                return Err(ModifiedEnterError::new(
                    &case_id,
                    "screen",
                    format!("unexpected marker: {marker}"),
                ));
            }
        }

        let cleanup: Vec<&str> = if case_id != "plain-enter-control" {
            if child_exited(&child) {
                return Err(ModifiedEnterError::with_screen(
                    &case_id,
                    "ready-state",
                    "process exited after modified Enter".to_string(),
                    &screen,
                ));
            }
            write_bytes(&child.child.master, b"\x03")?;
            wait_for(
                &child.child,
                &mut buffer,
                &case_id,
                "exit",
                |_| child_exited(&child),
                timeout,
            )?;
            vec!["Ctrl+C exits from ready without submission"]
        } else {
            write_bytes(&child.child.master, b"\x03")?;
            wait_for_rendered(
                &child.child,
                &mut buffer,
                &case_id,
                "interrupt",
                |text| {
                    contains_marker(text, "Interrupted.") || contains_marker(text, "interrupted")
                },
                timeout,
            )?;
            write_bytes(&child.child.master, b"\x03")?;
            wait_for(
                &child.child,
                &mut buffer,
                &case_id,
                "exit",
                |_| child_exited(&child),
                timeout,
            )?;
            vec!["Ctrl+C interrupts busy state", "Ctrl+C exits cleanly"]
        };

        Ok(json!({
            "id": case_id,
            "status": "passed",
            "input_bytes": input_sequence
                .iter()
                .filter_map(|event| event.get("bytes_hex").and_then(Value::as_str))
                .collect::<Vec<_>>(),
            "observed": {
                "screen_markers": markers,
                "screen_absent_markers": absent,
                "cleanup": cleanup,
            },
            "capture": "direct PTY with TIOCSWINSZ 120x40",
        }))
    })();

    let _ = try_wait(&child.child);
    hades_dev::pty::stop(&mut child.child.child);
    provider.finish();
    result
}

fn write_report(report: &Value, path: Option<&Path>, status: u8) -> ExitCode {
    use std::io::Write;
    let text = serde_json::to_string_pretty(report).expect("serialize report");
    if let Some(path) = path {
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        if let Ok(mut file) = std::fs::File::create(path) {
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
    let mut contract = PathBuf::from("tests/fixtures/parity/OBS-0021-hades-modified-enter.json");
    let mut report_path: Option<PathBuf> = None;
    let mut timeout = Duration::from_secs_f64(5.0);

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
                    timeout = Duration::from_secs_f64(value.parse().unwrap_or(5.0));
                }
            }
            _ => {}
        }
    }

    let binary = binary.canonicalize().unwrap_or_else(|_| binary.clone());
    let contract = contract.canonicalize().unwrap_or_else(|_| contract.clone());
    let mut report = json!({
        "schema_version": 1,
        "command": "replay-modified-enter",
        "passed": false,
        "binary": binary.to_string_lossy(),
        "contract": contract.to_string_lossy(),
        "checks": [],
    });

    let mut status = 0u8;
    if !binary.is_file() {
        report["failure"] = json!({
            "case": "input",
            "step": "binary",
            "message": format!("binary not found: {}", binary.display()),
        });
        status = 1;
    } else {
        match load_contract(&contract) {
            Ok(contract) => {
                report["contract_observation"] = contract["observation_id"].clone();
                report["reference_observation"] =
                    contract.get("reference_observation").cloned().unwrap_or(Value::Null);
                report["dimensions"] = contract["reference"]["terminal"].clone();
                let steps = contract["steps"].as_array().cloned().unwrap_or_default();
                let mut checks: Vec<Value> = Vec::new();
                let mut failed = false;
                for (ordinal, case) in steps.iter().enumerate() {
                    match run_case(&binary, case, timeout, ordinal + 1) {
                        Ok(check) => checks.push(check),
                        Err(error) => {
                            report["failure"] = error.as_dict();
                            failed = true;
                            break;
                        }
                    }
                }
                if !failed {
                    report["checks"] = json!(checks);
                    report["passed"] = json!(true);
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
