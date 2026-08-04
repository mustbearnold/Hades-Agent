//! `hades-dev replay-editor-outcomes` — Rust port of
//! `scripts/replay_editor_outcomes.py` (HAD-144).
//!
//! Replays the OBS-0019 editor-outcome contract in isolated 120x40 tmux
//! sessions with a per-case deterministic `EDITOR`: modified drafts
//! (single-line, multiline, trailing-newline trim) submit with the edited
//! text; an empty editor result and a cancelled (non-zero) editor exit
//! keep the original draft. The replay asserts screen markers, reads the
//! `.hermes_history` file back, then interrupts and exits.

use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{Duration, Instant};

use hades_dev::composer::{ComposerError, emit_report};
use hades_dev::hold_provider::HoldProvider;
use hades_dev::tmux::{
    capture_screen, contains_marker, kill_session, session_exists, start_session, wait_for_screen,
};
use serde_json::{Value, json};

fn unix_millis() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0)
}

/// Validate the editor-outcomes contract: schema 1 with exactly the five
/// required case ids.
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
            "unsupported editor outcome contract".to_string(),
        ));
    }
    let cases = contract.get("cases").and_then(Value::as_array);
    let ids: std::collections::BTreeSet<&str> = cases
        .map(|cases| cases.iter())
        .unwrap_or_else(|| [].iter())
        .filter_map(|case| case.get("id").and_then(Value::as_str))
        .collect();
    let required: std::collections::BTreeSet<&str> = [
        "modified-clean-exit",
        "multiline-clean-exit",
        "trailing-newline-trim",
        "empty-clean-exit",
        "cancelled-nonzero-exit",
    ]
    .into_iter()
    .collect();
    if ids != required {
        return Err(ComposerError::new(
            "contract",
            "load",
            format!("case ids must be {required:?}"),
        ));
    }
    Ok(contract)
}

fn send_text(session: &str, text: &str) -> Result<(), ComposerError> {
    let result = hades_dev::tmux::tmux_run(&["send-keys", "-t", session, "-l", text]);
    if result.0 != 0 {
        let detail = result.2.trim().to_string();
        return Err(ComposerError::new(
            session,
            "type-draft",
            if detail.is_empty() { "tmux send failed".to_string() } else { detail },
        ));
    }
    Ok(())
}

fn send_key(session: &str, key: &str) -> Result<(), ComposerError> {
    let payload = match key {
        "Ctrl+G" => "C-g",
        "Ctrl+C" => "C-c",
        _ => {
            return Err(ComposerError::new(
                session,
                key,
                format!("unsupported editor-outcomes key: {key}"),
            ));
        }
    };
    let result = hades_dev::tmux::tmux_run(&["send-keys", "-t", session, payload]);
    if result.0 != 0 {
        let detail = result.2.trim().to_string();
        return Err(ComposerError::new(
            session,
            key,
            if detail.is_empty() { "tmux send failed".to_string() } else { detail },
        ));
    }
    Ok(())
}

fn wait_for_exit(session: &str, timeout: Duration) -> Result<(), ComposerError> {
    let deadline = Instant::now() + timeout;
    while session_exists(session) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(50));
    }
    if session_exists(session) {
        return Err(ComposerError::new(session, "exit", "process did not exit".to_string()));
    }
    Ok(())
}

fn run_case(
    binary: &Path,
    case: &Value,
    timeout: Duration,
    ordinal: usize,
    provider_environment: &[(&str, &str)],
) -> Result<Value, ComposerError> {
    let case_id = case["id"].as_str().unwrap_or("?").to_string();
    let session = format!("had019-editor-{ordinal}-{}", unix_millis());
    let history_home = std::env::temp_dir().join(format!("had019-editor-{case_id}-{ordinal}"));
    let _ = std::fs::create_dir_all(&history_home);

    let mut environment: Vec<(String, String)> = provider_environment
        .iter()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect();
    environment.push(("HERMES_HOME".to_string(), history_home.to_string_lossy().to_string()));
    environment.push(("VISUAL".to_string(), String::new()));
    environment.push(("EDITOR".to_string(), case["editor"].as_str().unwrap_or("").to_string()));
    let env_refs: Vec<(&str, &str)> =
        environment.iter().map(|(key, value)| (key.as_str(), value.as_str())).collect();

    let expected = &case["expected"];
    let screen_markers: Vec<String> = expected["screen_markers"]
        .as_array()
        .map(|array| array.iter().filter_map(|marker| marker.as_str().map(String::from)).collect())
        .unwrap_or_default();

    let result = (|| -> Result<Value, ComposerError> {
        start_session(binary, &session, &env_refs)
            .map_err(|error| ComposerError::new(&case_id, "startup", error))?;
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
        .map_err(|error| ComposerError::new(&case_id, "startup", error))?;

        let draft = case["draft"].as_str().unwrap_or("");
        send_text(&session, draft)?;
        wait_for_screen(&session, "type-draft", |screen| contains_marker(screen, draft), timeout)
            .map_err(|error| ComposerError::new(&case_id, "type-draft", error))?;
        send_key(&session, "Ctrl+G")?;

        let screen = if screen_markers.iter().any(|marker| marker == "Ctrl+C to interrupt") {
            wait_for_screen(
                &session,
                "editor-submit",
                |current| screen_markers.iter().all(|marker| contains_marker(current, marker)),
                timeout,
            )
            .map_err(|error| ComposerError::new(&case_id, "editor-submit", error))?
        } else {
            std::thread::sleep(Duration::from_millis(350));
            if !session_exists(&session) {
                return Err(ComposerError::new(
                    &case_id,
                    "editor-return",
                    "process exited after editor return".to_string(),
                ));
            }
            capture_screen(&session)
        };

        for marker in &screen_markers {
            if !contains_marker(&screen, marker) {
                return Err(ComposerError::new(
                    &case_id,
                    "editor-return",
                    format!("missing marker: {marker}"),
                ));
            }
        }
        if let Some(absent) = expected.get("screen_absent_markers").and_then(Value::as_array) {
            for marker in absent.iter().filter_map(|marker| marker.as_str()) {
                if contains_marker(&screen, marker) {
                    return Err(ComposerError::new(
                        &case_id,
                        "editor-return",
                        format!("unexpected marker: {marker}"),
                    ));
                }
            }
        }

        let history_path = history_home.join(".hermes_history");
        let history = std::fs::read_to_string(&history_path).unwrap_or_default();
        let expected_records: Vec<String> = expected
            .get("history_records")
            .and_then(Value::as_array)
            .map(|array| {
                array.iter().filter_map(|record| record.as_str().map(String::from)).collect()
            })
            .unwrap_or_default();
        for record in &expected_records {
            if !history.contains(record) {
                return Err(ComposerError::new(
                    &case_id,
                    "history-readback",
                    format!("missing history record: {record}"),
                ));
            }
        }
        if expected_records.is_empty() && !history.is_empty() {
            return Err(ComposerError::new(
                &case_id,
                "history-readback",
                "unexpected history entry".to_string(),
            ));
        }

        let mut steps = vec![
            json!({"id": "type-draft", "status": "passed", "observed": [draft]}),
            json!({"id": "editor-return", "status": "passed", "observed": screen_markers}),
            json!({"id": "history-readback", "status": "passed", "observed": expected_records}),
        ];

        send_key(&session, "Ctrl+C")?;
        if screen_markers.iter().any(|marker| marker == "Ctrl+C to interrupt") {
            wait_for_screen(
                &session,
                "interrupt",
                |current| contains_marker(current, "interrupted"),
                timeout,
            )
            .map_err(|error| ComposerError::new(&case_id, "interrupt", error))?;
        }
        send_key(&session, "Ctrl+C")?;
        wait_for_exit(&session, timeout)?;
        steps.extend([
            json!({"id": "interrupt-or-clear", "status": "passed", "observed": ["ready after editor outcome"]}),
            json!({"id": "exit", "status": "passed", "observed": ["process exit"]}),
        ]);

        Ok(json!({
            "id": case_id,
            "status": "passed",
            "steps": steps,
            "capture": "tmux capture-pane -p",
        }))
    })();

    if session_exists(&session) {
        kill_session(&session);
    }
    let _ = std::fs::remove_dir_all(&history_home);
    result
}

fn main() -> ExitCode {
    let mut args = std::env::args().skip(1);
    let mut binary = PathBuf::from("target/debug/hades");
    let mut contract = PathBuf::from("tests/fixtures/parity/OBS-0019-hades-editor-outcomes.json");
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
        "command": "replay-editor-outcomes",
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
                    let mut provider = match HoldProvider::start() {
                        Ok(provider) => provider,
                        Err(error) => {
                            report["failure"] = json!({
                                "case": case["id"],
                                "step": "startup",
                                "message": format!("hold provider failed: {error}"),
                            });
                            failed = true;
                            break;
                        }
                    };
                    let environment = provider.environment();
                    let env_refs: Vec<(&str, &str)> =
                        environment.iter().map(|(key, value)| (*key, value.as_str())).collect();
                    let outcome = run_case(&binary, case, timeout, ordinal + 1, &env_refs);
                    provider.finish();
                    match outcome {
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

    emit_report(&report, report_path.as_deref(), status)
}
