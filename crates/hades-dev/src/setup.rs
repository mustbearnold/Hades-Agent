//! Setup-family contract replay machinery, shared by the four setup
//! replays (setup-wizard, setup-provider-menu, setup-provider-model-prompt,
//! setup-terminal-backend).
//!
//! Port of the shared parts of `scripts/replay_setup_wizard.py` and
//! siblings (HAD-140+). These differ from the composer family: the
//! provider base URL is a fixed loopback endpoint (no hold provider), the
//! report binary is the sanitized `<hades-binary>` literal, `--contract`
//! is required, and the key payload set is a small subset.

use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{Duration, Instant};

use crate::tmux::{contains_marker, session_exists, start_session, wait_for_screen};
use serde_json::{Value, json};

/// Setup contract/replay failure, reusing the composer error shape.
pub use crate::composer::ComposerError as SetupError;

fn key_payload(value: &str) -> Result<&'static str, String> {
    match value {
        "Enter" => Ok("C-m"),
        "Down" => Ok("Down"),
        "Escape" => Ok("Escape"),
        "Ctrl+C" => Ok("C-c"),
        _ => Err(format!("unsupported setup key: {value}")),
    }
}

/// Validate a setup-family contract (text/key inputs only).
pub fn load_contract(path: &Path) -> Result<Value, SetupError> {
    let text = std::fs::read_to_string(path).map_err(|error| {
        SetupError::new("contract", "load", format!("could not read {}: {error}", path.display()))
    })?;
    let contract: Value = serde_json::from_str(&text).map_err(|error| {
        SetupError::new("contract", "load", format!("could not read {}: {error}", path.display()))
    })?;
    if !contract.is_object() || contract.get("schema_version") != Some(&json!(1)) {
        return Err(SetupError::new(
            "contract",
            "load",
            "unsupported setup contract schema".to_string(),
        ));
    }
    let cases = contract
        .get("cases")
        .and_then(Value::as_array)
        .filter(|cases| !cases.is_empty())
        .ok_or_else(|| {
        SetupError::new("contract", "load", "setup contract has no cases".to_string())
    })?;
    for case in cases {
        let case_id = case
            .get("id")
            .and_then(Value::as_str)
            .ok_or_else(|| SetupError::new("contract", "case", "case needs an id".to_string()))?;
        let steps = case
            .get("steps")
            .and_then(Value::as_array)
            .filter(|steps| !steps.is_empty())
            .ok_or_else(|| {
            SetupError::new("contract", case_id, "case has no steps".to_string())
        })?;
        for step in steps {
            let step_id = step.get("id").and_then(Value::as_str).ok_or_else(|| {
                SetupError::new("contract", case_id, "step needs an id".to_string())
            })?;
            let input = step.get("input").and_then(Value::as_object).ok_or_else(|| {
                SetupError::new("contract", step_id, "input must be an object".to_string())
            })?;
            let kind = input.get("kind").and_then(Value::as_str);
            if !matches!(kind, Some("text" | "key")) {
                return Err(SetupError::new(
                    "contract",
                    step_id,
                    "input must be text or key".to_string(),
                ));
            }
            if !input.get("value").and_then(Value::as_str).is_some() {
                return Err(SetupError::new(
                    "contract",
                    step_id,
                    "input needs a string value".to_string(),
                ));
            }
            let output = step.get("output").and_then(Value::as_object).ok_or_else(|| {
                SetupError::new("contract", step_id, "output must be an object".to_string())
            })?;
            for key in ["pty_markers", "pty_absent_markers"] {
                let markers = output.get(key).and_then(Value::as_array);
                if !markers.is_some_and(|markers| markers.iter().all(Value::is_string)) {
                    return Err(SetupError::new(
                        "contract",
                        step_id,
                        format!("{key} must be a string array"),
                    ));
                }
            }
        }
    }
    Ok(contract)
}

/// Send a setup-family input (text or one of the small key set).
fn send_setup_input(session: &str, input_value: &Value) -> Result<(), SetupError> {
    let kind = input_value["kind"].as_str().unwrap_or("");
    let value = input_value["value"].as_str().unwrap_or("");
    let result = if kind == "text" {
        crate::tmux::tmux_run(&["send-keys", "-t", session, "-l", value])
    } else {
        let payload = key_payload(value).map_err(|error| {
            SetupError::new("input", value, format!("unsupported setup key: {error}"))
        })?;
        crate::tmux::tmux_run(&["send-keys", "-t", session, payload])
    };
    if result.0 != 0 {
        let detail = if result.2.trim().is_empty() {
            result.1.trim().to_string()
        } else {
            result.2.trim().to_string()
        };
        return Err(SetupError::new(session, "input", format!("tmux send-keys failed: {detail}")));
    }
    Ok(())
}

/// Run one setup-family case in its own tmux session.
pub fn run_case(
    binary: &Path,
    case: &Value,
    timeout: Duration,
    ordinal: usize,
    session_prefix: &str,
) -> Result<Value, SetupError> {
    let case_id = case["id"].as_str().unwrap_or("?").to_string();
    let session = format!("{session_prefix}-{ordinal}-{}", unix_millis());
    let history_home = std::env::temp_dir()
        .join(format!("{session_prefix}-history-{}-{ordinal}", std::process::id()));
    let _ = std::fs::create_dir_all(&history_home);
    let env: [(&str, String); 2] = [
        ("HERMES_HOME", history_home.to_string_lossy().to_string()),
        ("HADES_PROVIDER_BASE_URL", "http://127.0.0.1:8765/v1".to_string()),
    ];
    let env_refs: Vec<(&str, &str)> =
        env.iter().map(|(key, value)| (*key, value.as_str())).collect();

    let mut replayed_steps: Vec<Value> = Vec::new();
    let result = (|| -> Result<Value, SetupError> {
        start_session(binary, &session, &env_refs)
            .map_err(|error| SetupError::new(&case_id, "startup", error))?;
        wait_for_screen(
            &session,
            "startup",
            |screen| {
                ["Hades Agent", "Underworld", "Available Tools", "Available Skills"]
                    .iter()
                    .all(|marker| contains_marker(screen, marker))
            },
            timeout,
        )
        .map_err(|error| SetupError::new(&case_id, "startup", error))?;

        let steps = case["steps"].as_array().expect("validated steps");
        for step in steps {
            let step_id = step["id"].as_str().unwrap_or("?").to_string();
            let input_value = step["input"].clone();
            let output = &step["output"];
            let markers: Vec<String> = output
                .get("pty_markers")
                .and_then(Value::as_array)
                .map(|array| {
                    array.iter().filter_map(|marker| marker.as_str().map(String::from)).collect()
                })
                .unwrap_or_default();
            let absent: Vec<String> = output
                .get("pty_absent_markers")
                .and_then(Value::as_array)
                .map(|array| {
                    array.iter().filter_map(|marker| marker.as_str().map(String::from)).collect()
                })
                .unwrap_or_default();

            send_setup_input(&session, &input_value)?;
            if output.get("process_exit").and_then(Value::as_bool) == Some(true) {
                let deadline = Instant::now() + timeout;
                while session_exists(&session) && Instant::now() < deadline {
                    std::thread::sleep(Duration::from_millis(50));
                }
                if session_exists(&session) {
                    return Err(SetupError::new(
                        &case_id,
                        &step_id,
                        "process did not exit".to_string(),
                    ));
                }
            } else {
                wait_for_screen(
                    &session,
                    &step_id,
                    |screen| {
                        markers.iter().all(|marker| contains_marker(screen, marker))
                            && absent.iter().all(|marker| !contains_marker(screen, marker))
                    },
                    timeout,
                )
                .map_err(|error| SetupError::new(&case_id, &step_id, error))?;
            }
            replayed_steps.push(json!({
                "id": step_id,
                "input": input_value,
                "status": "passed",
                "observed": markers,
                "absent": absent,
            }));
        }

        Ok(json!({
            "id": case_id,
            "status": "passed",
            "steps": replayed_steps,
            "capture": "tmux capture-pane -p",
        }))
    })();

    if session_exists(&session) {
        crate::tmux::kill_session(&session);
    }
    let _ = std::fs::remove_dir_all(&history_home);
    result
}

fn unix_millis() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0)
}

/// Shared main body for setup-family replays. `--contract` is required,
/// matching the Python argparser.
pub fn run_wrapper(command: &str, session_prefix: &str) -> ExitCode {
    let mut args = std::env::args().skip(1);
    let mut binary = PathBuf::from("target/debug/hades");
    let mut contract: Option<PathBuf> = None;
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
                    contract = Some(PathBuf::from(value));
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
        "schema_version": 1,
        "command": command,
        "passed": false,
        "binary": "<hades-binary>",
        "contract": "",
        "checks": [],
    });

    let mut status = 0u8;
    let Some(contract) = contract else {
        report["failure"] = json!({
            "case": "input",
            "step": "contract",
            "message": "the following arguments are required: --contract",
        });
        return crate::composer::emit_report(&report, report_path.as_deref(), 1);
    };
    let contract = contract.canonicalize().unwrap_or_else(|_| contract.clone());
    report["contract"] = json!(contract.to_string_lossy());

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
                report["dimensions"] = contract["terminal"].clone();
                let cases = contract["cases"].as_array().cloned().unwrap_or_default();
                let mut checks: Vec<Value> = Vec::new();
                let mut failed = false;
                for (ordinal, case) in cases.iter().enumerate() {
                    match run_case(&binary, case, timeout, ordinal + 1, session_prefix) {
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

    crate::composer::emit_report(&report, report_path.as_deref(), status)
}
