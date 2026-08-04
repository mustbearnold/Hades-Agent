//! `hades-dev replay-clipboard-text` — Rust port of
//! `scripts/replay_clipboard_text.py` (HAD-147).
//!
//! Replays the Hades successful-text clipboard contract (OBS-0023) in an
//! isolated direct PTY with a synthetic xclip provider: seed text typed
//! into the composer, Ctrl+V (raw 0x16) invoking the fake xclip that
//! records its arguments and returns the fixture payload, the pasted
//! markers rendered on the reconstructed screen, the provider-argument
//! log matching the contract, and a clean Ctrl+C exit from ready.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{Duration, Instant};

use hades_dev::pty::read_available;
use hades_dev::replay::{
    ExitStatus, ReplayChild, RetainedSlave, marker_present, spawn_with_env, terminal_flags,
    try_wait, wait_for, wait_for_exit, wait_for_rendered,
};
use hades_dev::screen::Screen;
use serde_json::{Value, json};

const STARTUP_MARKERS: [&str; 4] =
    ["Hades Agent", "Underworld", "Available Tools", "Available Skills"];
const STRIP_ENV: [&str; 3] = ["WAYLAND_DISPLAY", "WSL_INTEROP", "WSL_DISTRO_NAME"];

/// Reconstruct the on-screen text (what a real terminal shows). The
/// animated startup logo emits interleaved sparse-redraw cell writes that
/// fragment typed text in the raw stream; the Screen emulator rebuilds the
/// grid so draft/paste markers are contiguous again.
fn rendered_text(output: &[u8]) -> String {
    let mut screen = Screen::new(120, 40);
    screen.feed(output);
    screen.lines().join("\n")
}

struct Contract {
    observation_id: String,
    reference_observation: Option<String>,
    steps: Vec<Value>,
}

fn load_contract(path: &Path) -> Result<Contract, String> {
    let contents =
        fs::read_to_string(path).map_err(|error| format!("could not read contract: {error}"))?;
    let contract: Value =
        serde_json::from_str(&contents).map_err(|error| format!("invalid contract: {error}"))?;
    if contract.get("schema_version").and_then(Value::as_u64) != Some(1) {
        return Err("unsupported clipboard contract".to_owned());
    }
    let steps = contract
        .get("steps")
        .and_then(Value::as_array)
        .cloned()
        .ok_or_else(|| "contract has no steps".to_owned())?;
    let ids: Vec<String> = steps
        .iter()
        .filter_map(|step| step.get("id").and_then(Value::as_str).map(str::to_owned))
        .collect();
    let required = ["successful-text", "empty-provider-control"];
    let mut sorted = ids.clone();
    sorted.sort();
    let mut required_sorted = required.to_vec();
    required_sorted.sort();
    if sorted != required_sorted {
        return Err(format!("step ids must be {:?}", required.to_vec()));
    }
    Ok(Contract {
        observation_id: contract
            .get("observation_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        reference_observation: contract
            .get("reference_observation")
            .and_then(Value::as_str)
            .map(str::to_owned),
        steps,
    })
}

fn input_bytes(event: &Value) -> Result<Vec<u8>, String> {
    let hex = event
        .get("bytes_hex")
        .and_then(Value::as_str)
        .ok_or_else(|| "input event has no bytes_hex".to_owned())?;
    let compact: String = hex.split_whitespace().collect();
    let bytes = (0..compact.len())
        .step_by(2)
        .map(|index| {
            u8::from_str_radix(&compact[index..index + 2], 16)
                .map_err(|error| format!("invalid input bytes: {error}"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(bytes)
}

/// Write the synthetic xclip provider: records argv into the log file and
/// echoes the fixture payload to stdout.
fn create_xclip(provider_dir: &Path, log_path: &Path) -> Result<(), String> {
    fs::create_dir_all(provider_dir).map_err(|error| error.to_string())?;
    let script =
        "#!/bin/sh\nprintf '%s\\n' \"$*\" > \"$HADES_CLIPBOARD_LOG\"\ncat \"$HADES_CLIPBOARD_PAYLOAD\"\n"
            .to_string();
    let xclip = provider_dir.join("xclip");
    fs::write(&xclip, script).map_err(|error| error.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions =
            fs::metadata(&xclip).map_err(|error| error.to_string())?.permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&xclip, permissions).map_err(|error| error.to_string())?;
    }
    // Note: unlike Python's `Path.touch()`, `fs::write` truncates — the
    // payload file must keep the fixture bytes already written by run_case,
    // so only the (initially empty) argument log is created here.
    fs::write(log_path, []).map_err(|error| error.to_string())?;
    Ok(())
}

fn spawn_with_provider(
    binary: &Path,
    home: &Path,
    provider_dir: &Path,
    payload_path: &Path,
    log_path: &Path,
) -> Result<ReplayChild, String> {
    let path_value = std::env::var("PATH").unwrap_or_default();
    // PATH entries are separated by the platform's path list separator
    // (':' on Unix) — use join_paths, not MAIN_SEPARATOR.
    let mut entries = vec![provider_dir.as_os_str().to_owned()];
    entries.extend(std::env::split_paths(&path_value).map(std::ffi::OsString::from));
    let provider_path =
        std::env::join_paths(entries).map_err(|error| format!("could not build PATH: {error}"))?;
    let provider_path =
        provider_path.to_str().ok_or_else(|| "non-utf8 provider path".to_owned())?.to_owned();
    let extra: [(&str, &str); 6] = [
        ("HOME", home.to_str().ok_or_else(|| "non-utf8 home".to_owned())?),
        ("HERMES_HOME", home.to_str().ok_or_else(|| "non-utf8 home".to_owned())?),
        ("HADES_PROVIDER_BASE_URL", "http://127.0.0.1:8765/v1"),
        ("PATH", &provider_path),
        (
            "HADES_CLIPBOARD_PAYLOAD",
            payload_path.to_str().ok_or_else(|| "non-utf8 payload".to_owned())?,
        ),
        ("HADES_CLIPBOARD_LOG", log_path.to_str().ok_or_else(|| "non-utf8 log".to_owned())?),
    ];
    spawn_with_env(binary, &[], &extra, &STRIP_ENV).map_err(|error| error.to_string())
}

fn run_case(
    binary: &Path,
    case: &Value,
    timeout: Duration,
    ordinal: usize,
) -> Result<Value, String> {
    let case_id = case
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| "case has no id".to_owned())?
        .to_owned();
    let home =
        std::env::temp_dir().join(format!("had023-{case_id}-{ordinal}-{}", std::process::id()));
    let provider_dir = home.join("bin");
    let payload_path = home.join("clipboard.payload");
    let log_path = home.join("clipboard.args");
    fs::create_dir_all(&home).map_err(|error| error.to_string())?;
    let payload = case
        .get("provider_payload")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .as_bytes()
        .to_vec();
    fs::write(&payload_path, &payload).map_err(|error| error.to_string())?;
    create_xclip(&provider_dir, &log_path)?;

    let mut reaped = false;
    let result = (|| -> Result<Value, String> {
        let child = spawn_with_provider(binary, &home, &provider_dir, &payload_path, &log_path)?;
        let mut output = Vec::new();
        let slave_path = child.slave_path.clone();

        wait_for(
            &child.child,
            &mut output,
            &format!("{case_id}: startup"),
            |text| STARTUP_MARKERS.iter().all(|marker| marker_present(text, marker)),
            timeout,
        )?;

        for event in
            case.get("input_sequence").and_then(Value::as_array).cloned().unwrap_or_default()
        {
            hades_dev::replay::send(&child.child.master, &input_bytes(&event)?)
                .map_err(|error| error.to_string())?;
            std::thread::sleep(Duration::from_millis(80));
            output.extend_from_slice(&read_available(&child.child.master));
        }

        let expected =
            case.get("output").ok_or_else(|| "case has no output contract".to_owned())?.clone();
        let markers: Vec<String> = expected
            .get("screen_markers")
            .and_then(Value::as_array)
            .map(|markers| {
                markers.iter().filter_map(|marker| marker.as_str().map(str::to_owned)).collect()
            })
            .unwrap_or_default();
        wait_for_rendered(
            &child.child,
            &mut output,
            &format!("{case_id}: clipboard"),
            |rendered| markers.iter().all(|marker| marker_present(rendered, marker)),
            timeout,
        )?;

        let rendered = rendered_text(&output);
        for marker in expected
            .get("screen_absent_markers")
            .and_then(Value::as_array)
            .map(|markers| {
                markers
                    .iter()
                    .filter_map(|marker| marker.as_str().map(str::to_owned))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default()
        {
            if marker_present(&rendered, &marker) {
                return Err(format!("{case_id}: unexpected marker: {marker}"));
            }
        }

        let provider_arguments = expected
            .get("provider_arguments")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        let log_deadline = Instant::now() + timeout;
        loop {
            let log_contents = fs::read_to_string(&log_path).unwrap_or_default();
            if log_contents.trim_end() == provider_arguments {
                break;
            }
            if try_wait(&child.child)?.is_some() {
                return Err(format!("{case_id}: provider: process exited before xclip log match"));
            }
            if Instant::now() >= log_deadline {
                return Err(format!("{case_id}: provider: timed out waiting for xclip arguments"));
            }
            std::thread::sleep(Duration::from_millis(50));
        }

        if try_wait(&child.child)?.is_some() {
            return Err(format!("{case_id}: process exited before cleanup"));
        }
        let slave = RetainedSlave::retain(&slave_path).map_err(|error| error.to_string())?;
        let ready_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if ready_flags.canonical || ready_flags.echo {
            return Err(format!("{case_id}: ready state was not raw mode: {ready_flags:?}"));
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 0 }) {
            return Err(format!("{case_id}: unexpected exit status: {exit_status:?}"));
        }

        Ok(json!({
            "id": case_id,
            "status": "passed",
            "input_bytes": case
                .get("input_sequence")
                .and_then(Value::as_array)
                .map(|events| {
                    events
                        .iter()
                        .filter_map(|event| event.get("bytes_hex").and_then(Value::as_str))
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default(),
            "provider_arguments": provider_arguments,
            "observed": {
                "screen_markers": markers,
                "screen_absent_markers": expected
                    .get("screen_absent_markers")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default(),
                "cleanup": "Ctrl+C exits from ready without submission",
            },
            "capture": "direct PTY with TIOCSWINSZ 120x40",
        }))
    })();

    if !reaped {
        let _ = fs::remove_dir_all(&home);
    }
    result
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
    let mut contract_path =
        PathBuf::from("tests/fixtures/parity/OBS-0023-hades-text-clipboard.json");
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
                    contract_path = PathBuf::from(value);
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
    let contract_path = contract_path.canonicalize().unwrap_or_else(|_| contract_path.clone());
    let mut report = json!({
        "schema_version": 1,
        "command": "replay-clipboard-text",
        "passed": false,
        "binary": binary.display().to_string(),
        "contract": contract_path.display().to_string(),
        "checks": [],
    });
    if !binary.is_file() {
        report["failure"] = json!({"case": "input", "step": "binary", "message": format!("binary not found: {}", binary.display())});
        return write_report(&report, report_path.as_deref(), 1);
    }

    match load_contract(&contract_path) {
        Ok(contract) => {
            report["contract_observation"] = json!(contract.observation_id);
            if let Some(reference) = contract.reference_observation {
                report["reference_observation"] = json!(reference);
            }
            report["dimensions"] = json!({
                "columns": 120,
                "rows": 40,
                "emulator": "direct PTY with raw byte writes",
            });
            let mut checks = Vec::new();
            for (ordinal, case) in contract.steps.iter().enumerate() {
                match run_case(&binary, case, timeout, ordinal + 1) {
                    Ok(check) => checks.push(check),
                    Err(error) => {
                        report["failure"] =
                            json!({"case": "report", "step": "runtime", "message": error});
                        return write_report(&report, report_path.as_deref(), 1);
                    }
                }
            }
            report["checks"] = json!(checks);
            report["passed"] = json!(true);
            write_report(&report, report_path.as_deref(), 0)
        }
        Err(error) => {
            report["failure"] = json!({"case": "contract", "step": "load", "message": error});
            write_report(&report, report_path.as_deref(), 1)
        }
    }
}
