//! `hades-dev replay-history` — Rust port of
//! `scripts/replay_history.py` (HAD-134).
//!
//! Replays Hades persistent input history across isolated tmux PTY
//! processes: restart-recall (history written by one process is recalled
//! by a fresh one), duplicate-suppression (consecutive duplicate drafts do
//! not rewrite the file), multiline-readback (multiline pastes persist as
//! one record per line), and load-cap (the newest-1,000 entry cap with a
//! seeded history file). Same report JSON shape as the Python replay.

use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{Duration, Instant};

use hades_dev::hold_provider::HoldProvider;
use hades_dev::tmux::{
    contains_marker, send_input, session_exists, start_session, wait_for_screen,
};
use serde_json::{Value, json};

const DEFAULT_CONTRACT: &str =
    "tests/fixtures/parity/OBS-0017-hades-input-history-persistence.json";
const STARTUP_MARKERS: [&str; 4] =
    ["Hades Agent", "Underworld", "Available Tools", "Available Skills"];

/// History contract/replay failure, like `ComposerReplayFailure`.
struct HistoryError {
    case: String,
    step: String,
    message: String,
    details: Value,
}

impl HistoryError {
    fn new(case: &str, step: &str, message: String) -> Self {
        Self { case: case.to_string(), step: step.to_string(), message, details: json!({}) }
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

/// Validate the history contract, like `load_contract`.
fn load_contract(path: &Path) -> Result<Value, HistoryError> {
    let text = std::fs::read_to_string(path).map_err(|error| {
        HistoryError::new("contract", "load", format!("could not read {}: {error}", path.display()))
    })?;
    let contract: Value = serde_json::from_str(&text).map_err(|error| {
        HistoryError::new("contract", "load", format!("could not read {}: {error}", path.display()))
    })?;
    if !contract.is_object() || contract.get("schema_version") != Some(&json!(1)) {
        return Err(HistoryError::new(
            "contract",
            "load",
            "unsupported history contract schema".to_string(),
        ));
    }
    let cases = contract
        .get("cases")
        .and_then(Value::as_array)
        .filter(|cases| !cases.is_empty())
        .ok_or_else(|| {
        HistoryError::new("contract", "load", "history contract has no cases".to_string())
    })?;
    let required: HashSet<&str> =
        ["restart-recall", "duplicate-suppression", "multiline-readback", "load-cap"]
            .into_iter()
            .collect();
    let actual: HashSet<&str> =
        cases.iter().filter_map(|case| case.get("id").and_then(Value::as_str)).collect();
    if actual != required {
        let mut sorted: Vec<&str> = required.iter().copied().collect();
        sorted.sort();
        return Err(HistoryError::new(
            "contract",
            "load",
            format!("history cases must be {sorted:?}"),
        ));
    }
    Ok(contract)
}

/// Start a Hades session with the given history home, like
/// `start_history_session`.
fn start_history_session(
    binary: &Path,
    session: &str,
    history_home: &Path,
    timeout: Duration,
    provider: &HoldProvider,
) -> Result<(), HistoryError> {
    let mut environment: Vec<(String, String)> =
        provider.environment().into_iter().map(|(key, value)| (key.to_string(), value)).collect();
    environment.push(("HERMES_HOME".to_string(), history_home.to_string_lossy().to_string()));
    let environment_refs: Vec<(&str, &str)> =
        environment.iter().map(|(key, value)| (key.as_str(), value.as_str())).collect();
    start_session(binary, session, &environment_refs)
        .map_err(|error| HistoryError::new(session, "startup", error))?;
    wait_for_screen(
        session,
        "startup",
        |screen| STARTUP_MARKERS.iter().all(|marker| contains_marker(screen, marker)),
        timeout,
    )
    .map_err(|error| HistoryError::new(session, "startup", error))?;
    Ok(())
}
/// Wait for the session to exit, like `wait_for_exit`.
fn wait_for_exit(session: &str, timeout: Duration) -> Result<(), HistoryError> {
    let deadline = Instant::now() + timeout;
    while session_exists(session) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(50));
    }
    if session_exists(session) {
        return Err(HistoryError::new(session, "exit", "process did not exit".to_string()));
    }
    Ok(())
}

/// Interrupt once, then exit cleanly, like `interrupt_and_exit`.
fn interrupt_and_exit(
    session: &str,
    timeout: Duration,
    steps: &mut Vec<Value>,
) -> Result<(), HistoryError> {
    send_input(session, "key", "Ctrl+C")
        .map_err(|error| HistoryError::new(session, "interrupt", error))?;
    wait_for_screen(session, "interrupt", |screen| contains_marker(screen, "interrupted"), timeout)
        .map_err(|error| HistoryError::new(session, "interrupt", error))?;
    steps.push(json!({"id": "interrupt", "status": "passed", "observed": ["interrupted"]}));
    send_input(session, "key", "Ctrl+C")
        .map_err(|error| HistoryError::new(session, "exit", error))?;
    wait_for_exit(session, timeout)?;
    steps.push(json!({"id": "exit", "status": "passed", "observed": ["process exit"]}));
    Ok(())
}

/// Type/paste a draft, submit it, and record both steps, like
/// `submit_draft`.
fn submit_draft(
    session: &str,
    draft: &str,
    timeout: Duration,
    steps: &mut Vec<Value>,
    paste: bool,
) -> Result<(), HistoryError> {
    let kind = if paste { "paste" } else { "text" };
    send_input(session, kind, draft).map_err(|error| HistoryError::new(session, "draft", error))?;
    let lines: Vec<&str> = draft.split('\n').collect();
    wait_for_screen(
        session,
        "draft",
        |screen| lines.iter().all(|line| contains_marker(screen, line)),
        timeout,
    )
    .map_err(|error| HistoryError::new(session, "draft", error))?;
    let observed: Vec<String> = lines.iter().map(|line| line.to_string()).collect();
    steps.push(json!({
        "id": "draft",
        "input": {"kind": kind, "value": draft},
        "status": "passed",
        "observed": observed,
    }));
    send_input(session, "key", "Enter")
        .map_err(|error| HistoryError::new(session, "submit", error))?;
    wait_for_screen(
        session,
        "submit",
        |screen| {
            ["musing", "mulling", "Ctrl+C to interrupt"]
                .iter()
                .all(|marker| contains_marker(screen, marker))
        },
        timeout,
    )
    .map_err(|error| HistoryError::new(session, "submit", error))?;
    steps.push(json!({
        "id": "submit",
        "status": "passed",
        "observed": ["musing", "mulling", "Ctrl+C to interrupt"],
    }));
    Ok(())
}

fn run_restart_case(
    binary: &Path,
    case: &Value,
    timeout: Duration,
    history_home: &Path,
    provider: &HoldProvider,
) -> Result<Value, HistoryError> {
    let session_a = format!("had017-history-a-{}", unix_millis());
    let session_b = format!("had017-history-b-{}", unix_millis());
    let mut steps: Vec<Value> = Vec::new();
    let draft = case["draft"].as_str().unwrap_or("").to_string();

    let result = (|| -> Result<Value, HistoryError> {
        start_history_session(binary, &session_a, history_home, timeout, provider)?;
        submit_draft(&session_a, &draft, timeout, &mut steps, false)?;
        interrupt_and_exit(&session_a, timeout, &mut steps)?;

        let history_path = history_home.join(".hermes_history");
        let history_text = std::fs::read_to_string(&history_path).map_err(|error| {
            HistoryError::new("restart-recall", "history-write", error.to_string())
        })?;
        let expected_entry = case["expected_history_entry"].as_str().unwrap_or("");
        if !history_text.contains(expected_entry) {
            return Err(HistoryError::new(
                "restart-recall",
                "history-write",
                format!("missing history record {expected_entry}"),
            ));
        }

        start_history_session(binary, &session_b, history_home, timeout, provider)?;
        send_input(&session_b, "key", "Up")
            .map_err(|error| HistoryError::new(&session_b, "history-up", error))?;
        let recalled = case["expected_recalled_draft"].as_str().unwrap_or("").to_string();
        wait_for_screen(
            &session_b,
            "history-up",
            |screen| contains_marker(screen, &recalled),
            timeout,
        )
        .map_err(|error| HistoryError::new(&session_b, "history-up", error))?;
        steps.push(json!({"id": "history-up", "status": "passed", "observed": [recalled]}));

        send_input(&session_b, "key", "Down")
            .map_err(|error| HistoryError::new(&session_b, "history-down", error))?;
        let empty_marker = case["expected_empty_draft_marker"].as_str().unwrap_or("").to_string();
        wait_for_screen(
            &session_b,
            "history-down",
            |screen| contains_marker(screen, &empty_marker),
            timeout,
        )
        .map_err(|error| HistoryError::new(&session_b, "history-down", error))?;
        steps.push(json!({"id": "history-down", "status": "passed", "observed": ["empty draft"]}));

        send_input(&session_b, "key", "Ctrl+C")
            .map_err(|error| HistoryError::new(&session_b, "exit", error))?;
        wait_for_exit(&session_b, timeout)?;
        steps.push(json!({"id": "exit", "status": "passed", "observed": ["process exit"]}));

        Ok(json!({"id": "restart-recall", "status": "passed", "steps": steps}))
    })();

    for session in [&session_a, &session_b] {
        if session_exists(session) {
            hades_dev::tmux::kill_session(session);
        }
    }
    result
}

fn run_duplicate_case(
    binary: &Path,
    case: &Value,
    timeout: Duration,
    history_home: &Path,
    provider: &HoldProvider,
) -> Result<Value, HistoryError> {
    let session = format!("had017-history-dup-{}", unix_millis());
    let mut steps: Vec<Value> = Vec::new();
    let result = (|| -> Result<Value, HistoryError> {
        start_history_session(binary, &session, history_home, timeout, provider)?;
        let history_path = history_home.join(".hermes_history");
        let before = std::fs::read(&history_path).unwrap_or_default();
        submit_draft(&session, case["draft"].as_str().unwrap_or(""), timeout, &mut steps, false)?;
        send_input(&session, "key", "Ctrl+C")
            .map_err(|error| HistoryError::new(&session, "interrupt", error))?;
        wait_for_screen(
            &session,
            "interrupt",
            |screen| contains_marker(screen, "interrupted"),
            timeout,
        )
        .map_err(|error| HistoryError::new(&session, "interrupt", error))?;
        let after = std::fs::read(&history_path).unwrap_or_default();
        if before != after {
            return Err(HistoryError::new(
                "duplicate-suppression",
                "history-write",
                "history file changed for a consecutive duplicate".to_string(),
            ));
        }
        steps.push(
            json!({"id": "duplicate-readback", "status": "passed", "observed": ["file unchanged"]}),
        );
        send_input(&session, "key", "Ctrl+C")
            .map_err(|error| HistoryError::new(&session, "exit", error))?;
        wait_for_exit(&session, timeout)?;
        steps.push(json!({"id": "exit", "status": "passed", "observed": ["process exit"]}));
        Ok(
            json!({"id": "duplicate-suppression", "status": "passed", "steps": steps, "file_unchanged": true}),
        )
    })();
    if session_exists(&session) {
        hades_dev::tmux::kill_session(&session);
    }
    result
}

fn run_multiline_case(
    binary: &Path,
    case: &Value,
    timeout: Duration,
    history_home: &Path,
    provider: &HoldProvider,
) -> Result<Value, HistoryError> {
    let session = format!("had017-history-multi-{}", unix_millis());
    let mut steps: Vec<Value> = Vec::new();
    let result = (|| -> Result<Value, HistoryError> {
        start_history_session(binary, &session, history_home, timeout, provider)?;
        let lines: Vec<String> = case["lines"]
            .as_array()
            .map(|array| array.iter().filter_map(|line| line.as_str().map(String::from)).collect())
            .unwrap_or_default();
        submit_draft(&session, &lines.join("\n"), timeout, &mut steps, true)?;
        interrupt_and_exit(&session, timeout, &mut steps)?;
        let history_text =
            std::fs::read_to_string(history_home.join(".hermes_history")).map_err(|error| {
                HistoryError::new("multiline-readback", "history-readback", error.to_string())
            })?;
        let records: Vec<String> = case["expected_history_records"]
            .as_array()
            .map(|array| {
                array.iter().filter_map(|record| record.as_str().map(String::from)).collect()
            })
            .unwrap_or_default();
        for record in &records {
            if !history_text.contains(&format!("{record}\n")) {
                return Err(HistoryError::new(
                    "multiline-readback",
                    "history-readback",
                    format!("missing record {record}"),
                ));
            }
        }
        steps.push(json!({"id": "history-readback", "status": "passed", "observed": ["multiline + records"]}));
        Ok(json!({"id": "multiline-readback", "status": "passed", "steps": steps}))
    })();
    if session_exists(&session) {
        hades_dev::tmux::kill_session(&session);
    }
    result
}

fn run_cap_case(
    binary: &Path,
    case: &Value,
    timeout: Duration,
    history_home: &Path,
    provider: &HoldProvider,
) -> Result<Value, HistoryError> {
    let session = format!("had017-history-cap-{}", unix_millis());
    let mut steps: Vec<Value> = Vec::new();
    let history_path = history_home.join(".hermes_history");
    let seed_count = case["seed_count"].as_u64().unwrap_or(0) as usize;
    let mut seed = String::new();
    for index in 1..=seed_count {
        seed.push_str(&format!("\n# timestamp\n+cap-{index:04}\n"));
    }
    let _ = std::fs::create_dir_all(history_home);
    let _ = std::fs::write(&history_path, seed);

    let result = (|| -> Result<Value, HistoryError> {
        start_history_session(binary, &session, history_home, timeout, provider)?;
        send_input(&session, "key", "Up")
            .map_err(|error| HistoryError::new(&session, "cap-newest", error))?;
        let newest = case["newest_entry"].as_str().unwrap_or("").to_string();
        wait_for_screen(&session, "cap-newest", |screen| contains_marker(screen, &newest), timeout)
            .map_err(|error| HistoryError::new(&session, "cap-newest", error))?;
        steps.push(json!({"id": "cap-newest", "status": "passed", "observed": [newest]}));

        for _ in 0..999 {
            let _ = hades_dev::tmux::tmux_run(&["send-keys", "-t", &session, "Up"]);
            std::thread::sleep(Duration::from_millis(10));
        }
        let oldest = case["oldest_retained_entry"].as_str().unwrap_or("").to_string();
        wait_for_screen(&session, "cap-oldest", |screen| contains_marker(screen, &oldest), timeout)
            .map_err(|error| HistoryError::new(&session, "cap-oldest", error))?;
        steps.push(json!({"id": "cap-oldest", "status": "passed", "observed": [oldest]}));

        let _ = hades_dev::tmux::tmux_run(&["send-keys", "-t", &session, "Up"]);
        wait_for_screen(&session, "cap-floor", |screen| contains_marker(screen, &oldest), timeout)
            .map_err(|error| HistoryError::new(&session, "cap-floor", error))?;
        steps.push(json!({"id": "cap-floor", "status": "passed", "observed": [oldest]}));

        send_input(&session, "key", "Ctrl+C")
            .map_err(|error| HistoryError::new(&session, "exit", error))?;
        wait_for_exit(&session, timeout)?;
        steps.push(json!({"id": "exit", "status": "passed", "observed": ["process exit"]}));
        Ok(json!({"id": "load-cap", "status": "passed", "steps": steps, "seed_count": seed_count}))
    })();
    if session_exists(&session) {
        hades_dev::tmux::kill_session(&session);
    }
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
        "command": "replay-history",
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
                let root =
                    std::env::temp_dir().join(format!("had017-history-{}", std::process::id()));
                let _ = std::fs::create_dir_all(&root);
                let mut provider = match HoldProvider::start() {
                    Ok(provider) => provider,
                    Err(error) => {
                        report["failure"] = json!({
                            "case": "report",
                            "step": "runtime",
                            "message": format!("hold provider failed: {error}"),
                        });
                        return write_report(&report, report_path.as_deref(), 1);
                    }
                };
                let mut checks: Vec<Value> = Vec::new();
                let case_for = |id: &str| {
                    cases.iter().find(|case| case.get("id").and_then(Value::as_str) == Some(id))
                };
                let restart_home = root.join("restart");
                let multiline_home = root.join("multiline");
                let cap_home = root.join("cap");
                let run_result = (|| -> Result<(), HistoryError> {
                    checks.push(run_restart_case(
                        &binary,
                        case_for("restart-recall").ok_or_else(|| {
                            HistoryError::new(
                                "report",
                                "runtime",
                                "missing restart-recall case".to_string(),
                            )
                        })?,
                        timeout,
                        &restart_home,
                        &provider,
                    )?);
                    checks.push(run_duplicate_case(
                        &binary,
                        case_for("duplicate-suppression").ok_or_else(|| {
                            HistoryError::new(
                                "report",
                                "runtime",
                                "missing duplicate-suppression case".to_string(),
                            )
                        })?,
                        timeout,
                        &restart_home,
                        &provider,
                    )?);
                    checks.push(run_multiline_case(
                        &binary,
                        case_for("multiline-readback").ok_or_else(|| {
                            HistoryError::new(
                                "report",
                                "runtime",
                                "missing multiline-readback case".to_string(),
                            )
                        })?,
                        timeout,
                        &multiline_home,
                        &provider,
                    )?);
                    let _ = std::fs::create_dir_all(&cap_home);
                    checks.push(run_cap_case(
                        &binary,
                        case_for("load-cap").ok_or_else(|| {
                            HistoryError::new(
                                "report",
                                "runtime",
                                "missing load-cap case".to_string(),
                            )
                        })?,
                        timeout,
                        &cap_home,
                        &provider,
                    )?);
                    Ok(())
                })();
                provider.finish();
                let _ = std::fs::remove_dir_all(&root);
                match run_result {
                    Ok(()) => {
                        report["checks"] = json!(checks);
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
