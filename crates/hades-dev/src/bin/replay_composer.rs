//! `hades-dev replay-composer` — Rust port of
//! `scripts/replay_composer.py` (HAD-133).
//!
//! Replays the implemented Hades composer contract in isolated 120x40 tmux
//! sessions: contract loading and validation (OBS-0011, OBS-0037), a
//! hold-provider-backed environment per case, text/key/paste input via tmux
//! send-keys, pty_markers/pty_absent_markers screen assertions via
//! capture-pane, and the same report JSON shape (`checks` with per-step
//! observed/absent records).

use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{Duration, Instant};

use hades_dev::hold_provider::HoldProvider;
use hades_dev::tmux::{
    capture_screen, contains_marker, kill_session, send_input, session_exists, start_session,
    wait_for_screen,
};
use serde_json::{Value, json};

const DEFAULT_CONTRACT: &str = "tests/fixtures/parity/OBS-0011-hades-composer-editing.json";
const STARTUP_MARKERS: [&str; 4] =
    ["Hades Agent", "Underworld", "Available Tools", "Available Skills"];

/// Composer contract/replay failure, like `ComposerReplayFailure`.
struct ComposerError {
    case: String,
    step: String,
    message: String,
    details: Value,
}

impl ComposerError {
    fn new(case: &str, step: &str, message: String) -> Self {
        Self { case: case.to_string(), step: step.to_string(), message, details: json!({}) }
    }

    fn with_screen(case: &str, step: &str, message: String, screen: &str) -> Self {
        let tail: Vec<&str> = screen.lines().rev().take(12).collect();
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

fn unix_millis() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0)
}

/// Validate a composer contract, like `load_contract`.
fn load_contract(path: &Path) -> Result<Value, ComposerError> {
    let text = std::fs::read_to_string(path).map_err(|error| {
        ComposerError::new(
            "contract",
            "load",
            format!("could not read {}: {error}", path.display()),
        )
    })?;
    let contract: Value = serde_json::from_str(&text).map_err(|error| {
        ComposerError::new(
            "contract",
            "load",
            format!("could not read {}: {error}", path.display()),
        )
    })?;
    if !contract.is_object() || contract.get("schema_version") != Some(&json!(1)) {
        return Err(ComposerError::new(
            "contract",
            "load",
            "unsupported composer contract schema".to_string(),
        ));
    }
    let cases = contract
        .get("cases")
        .and_then(Value::as_array)
        .filter(|cases| !cases.is_empty())
        .ok_or_else(|| {
        ComposerError::new("contract", "load", "composer contract has no cases".to_string())
    })?;
    let mut case_ids = std::collections::HashSet::new();
    for (case_index, case) in cases.iter().enumerate() {
        let case_id = case.get("id").and_then(Value::as_str).ok_or_else(|| {
            ComposerError::new(
                "contract",
                &format!("case[{case_index}]"),
                "case needs an id".to_string(),
            )
        })?;
        if !case_ids.insert(case_id.to_string()) {
            return Err(ComposerError::new("contract", case_id, "duplicate case id".to_string()));
        }
        let steps = case
            .get("steps")
            .and_then(Value::as_array)
            .filter(|steps| !steps.is_empty())
            .ok_or_else(|| {
            ComposerError::new("contract", case_id, "case has no steps".to_string())
        })?;
        let mut step_ids = std::collections::HashSet::new();
        for (step_index, step) in steps.iter().enumerate() {
            let step_path = format!("{case_id}[{step_index}]");
            let step_id = step.get("id").and_then(Value::as_str).ok_or_else(|| {
                ComposerError::new("contract", &step_path, "step needs an id".to_string())
            })?;
            if !step_ids.insert(step_id.to_string()) {
                return Err(ComposerError::new(
                    "contract",
                    step_id,
                    "duplicate step id".to_string(),
                ));
            }
            let input = step.get("input").and_then(Value::as_object).ok_or_else(|| {
                ComposerError::new("contract", step_id, "step input must be an object".to_string())
            })?;
            let kind = input.get("kind").and_then(Value::as_str);
            if !matches!(kind, Some("text" | "key" | "paste")) {
                return Err(ComposerError::new(
                    "contract",
                    step_id,
                    "step input must be text, key, or paste".to_string(),
                ));
            }
            if !input.get("value").and_then(Value::as_str).is_some() {
                return Err(ComposerError::new(
                    "contract",
                    step_id,
                    "step input needs a string value".to_string(),
                ));
            }
            let output = step.get("output").and_then(Value::as_object).ok_or_else(|| {
                ComposerError::new("contract", step_id, "step output must be an object".to_string())
            })?;
            let markers = output.get("pty_markers").and_then(Value::as_array);
            if !markers.is_some_and(|markers| markers.iter().all(Value::is_string)) {
                return Err(ComposerError::new(
                    "contract",
                    step_id,
                    "pty_markers must be a string array".to_string(),
                ));
            }
            let absent = output.get("pty_absent_markers").and_then(Value::as_array);
            // Python defaults a MISSING key to [] (output.get("...", [])),
            // so absent is only invalid when present and not a string array.
            if let Some(absent) = absent
                && !absent.iter().all(Value::is_string)
            {
                return Err(ComposerError::new(
                    "contract",
                    step_id,
                    "pty_absent_markers must be a string array".to_string(),
                ));
            }
        }
    }
    Ok(contract)
}

/// Run one contract case in its own tmux session, like `run_case`.
fn run_case(
    binary: &Path,
    case: &Value,
    timeout: Duration,
    ordinal: usize,
) -> Result<Value, ComposerError> {
    let case_id = case["id"].as_str().unwrap_or("?").to_string();
    let session = format!("had011-composer-{ordinal}-{}", unix_millis());
    let mut owned_history_home: Option<PathBuf> = None;
    let mut provider = HoldProvider::start().map_err(|error| {
        ComposerError::new(&case_id, "startup", format!("hold provider failed: {error}"))
    })?;
    let mut environment: Vec<(String, String)> =
        provider.environment().into_iter().map(|(key, value)| (key.to_string(), value)).collect();
    if !environment.iter().any(|(key, _)| key == "HERMES_HOME") {
        let home = std::env::temp_dir()
            .join(format!("had011-composer-history-{}-{ordinal}", std::process::id()));
        let _ = std::fs::create_dir_all(&home);
        environment.push(("HERMES_HOME".to_string(), home.to_string_lossy().to_string()));
        owned_history_home = Some(home);
    }
    let environment_refs: Vec<(&str, &str)> =
        environment.iter().map(|(key, value)| (key.as_str(), value.as_str())).collect();

    let mut replayed_steps: Vec<Value> = Vec::new();
    let result = (|| -> Result<Value, ComposerError> {
        start_session(binary, &session, &environment_refs)
            .map_err(|error| ComposerError::new(&case_id, "startup", error))?;
        wait_for_screen(
            &session,
            "startup",
            |screen| STARTUP_MARKERS.iter().all(|marker| contains_marker(screen, marker)),
            timeout,
        )
        .map_err(|error| {
            ComposerError::with_screen(&case_id, "startup", error, &capture_screen(&session))
        })?;

        let steps = case["steps"].as_array().expect("validated steps");
        for step in steps {
            let step_id = step["id"].as_str().unwrap_or("?").to_string();
            let input = step["input"].clone();
            let output_contract = &step["output"];
            let markers: Vec<String> = output_contract["pty_markers"]
                .as_array()
                .map(|array| {
                    array.iter().filter_map(|marker| marker.as_str().map(String::from)).collect()
                })
                .unwrap_or_default();
            let absent: Vec<String> = output_contract
                .get("pty_absent_markers")
                .and_then(Value::as_array)
                .map(|array| {
                    array.iter().filter_map(|marker| marker.as_str().map(String::from)).collect()
                })
                .unwrap_or_default();

            let kind = input["kind"].as_str().unwrap_or("");
            let value = input["value"].as_str().unwrap_or("");
            send_input(&session, kind, value).map_err(|error| {
                ComposerError::new(&session, "input", format!("tmux send-keys failed: {error}"))
            })?;

            let observed: Vec<String> = if output_contract
                .get("process_exit")
                .and_then(Value::as_bool)
                == Some(true)
            {
                let deadline = Instant::now() + timeout;
                while session_exists(&session) && Instant::now() < deadline {
                    std::thread::sleep(Duration::from_millis(50));
                }
                if session_exists(&session) {
                    return Err(ComposerError::new(
                        &case_id,
                        &step_id,
                        "process did not exit".to_string(),
                    ));
                }
                vec!["process exit".to_string()]
            } else if !markers.is_empty() || !absent.is_empty() {
                wait_for_screen(
                    &session,
                    &step_id,
                    |screen| {
                        markers.iter().all(|marker| contains_marker(screen, marker))
                            && absent.iter().all(|marker| !contains_marker(screen, marker))
                    },
                    timeout,
                )
                .map_err(|error| {
                    ComposerError::with_screen(&case_id, &step_id, error, &capture_screen(&session))
                })?;
                markers.clone()
            } else {
                std::thread::sleep(Duration::from_millis(80));
                if !session_exists(&session) {
                    return Err(ComposerError::new(
                        &case_id,
                        &step_id,
                        "process exited during a non-terminal step".to_string(),
                    ));
                }
                let _ = capture_screen(&session);
                Vec::new()
            };

            replayed_steps.push(json!({
                "id": step_id,
                "input": input,
                "status": "passed",
                "observed": observed,
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
        kill_session(&session);
    }
    if let Some(home) = owned_history_home {
        let _ = std::fs::remove_dir_all(home);
    }
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
        "command": "replay-composer",
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
                report["dimensions"] = contract["terminal"].clone();
                let cases = contract["cases"].as_array().cloned().unwrap_or_default();
                let mut checks: Vec<Value> = Vec::new();
                let mut failed = false;
                for (ordinal, case) in cases.iter().enumerate() {
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
