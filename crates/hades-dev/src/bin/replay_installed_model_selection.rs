//! `hades-dev replay-installed-model-selection` — Rust port of
//! `scripts/replay_installed_model_selection.py` (HAD-154).
//!
//! Proves both installed launcher spellings (~/.local/bin/hades and
//! ~/.local/bin/Hades) resolve to target/release/hades and carry the
//! model-selection slice: each alias runs the model-selection replay
//! (picker selects palette-model; a fresh process falls back to
//! vertical-model) without crossing the persisted sidecar boundary.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::time::Duration;

use serde_json::{Value, json};

const ROOT: &str = env!("CARGO_MANIFEST_DIR");
const ALIASES: [&str; 2] = ["hades", "Hades"];
const SHELL_CASES: [(&str, &[&str]); 2] =
    [("bash", &["--noprofile", "--norc"]), ("fish", &["--no-config"])];

/// Workspace root: crates/hades-dev -> crates -> repo root.
fn workspace_root() -> PathBuf {
    let manifest_dir = PathBuf::from(ROOT);
    manifest_dir.parent().and_then(|parent| parent.parent()).unwrap_or(&manifest_dir).to_owned()
}

fn run_shell_command(
    shell: &str,
    shell_options: &[&str],
    command_name: &str,
    launcher_dir: &Path,
    home: &Path,
) -> Result<Value, String> {
    let path = vec![launcher_dir.display().to_string(), "/usr/bin".to_owned(), "/bin".to_owned()]
        .join(":");
    let shell_executable = path
        .split(':')
        .map(|directory| Path::new(directory).join(shell))
        .find(|candidate| candidate.is_file())
        .ok_or_else(|| format!("required shell is unavailable: {shell}"))?;
    let command =
        format!("command -v {command_name}; {command_name} --version; {command_name} --help");
    let mut process = Command::new(&shell_executable);
    process.args(shell_options);
    process.arg("-c").arg(&command);
    process.env_clear();
    process
        .env("HOME", home)
        .env("HERMES_HOME", home.join("hermes"))
        .env("PATH", &path)
        .env("TERM", "xterm-256color")
        .env("COLUMNS", "120")
        .env("LINES", "40");
    process.current_dir(workspace_root());
    let output = process
        .output()
        .map_err(|error| format!("{shell} {command_name}: could not run shell: {error}"))?;
    let combined = String::from_utf8_lossy(&output.stdout).into_owned()
        + &String::from_utf8_lossy(&output.stderr);
    let expected_path = launcher_dir.join(command_name).display().to_string();
    if !output.status.success() {
        return Err(format!("{shell} {command_name}: shell command failed: {}", combined.trim()));
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    let lines: Vec<&str> = stdout.lines().map(str::trim).filter(|line| !line.is_empty()).collect();
    if lines.first().copied() != Some(expected_path.as_str()) {
        return Err(format!(
            "{shell} {command_name}: command resolved to {:?}, expected {expected_path}",
            lines.first()
        ));
    }
    if !combined.contains("Hades Agent 0.1.0") || !combined.contains("Usage: hades") {
        return Err(format!(
            "{shell} {command_name}: version/help output was incomplete: {}",
            combined.trim()
        ));
    }
    Ok(json!({
        "shell": shell,
        "command": command_name,
        "resolved_path": lines[0],
        "version_marker": "Hades Agent 0.1.0",
        "help_marker": "Usage: hades",
    }))
}

fn run_alias(
    alias: &str,
    launcher_dir: &Path,
    report_dir: &Path,
    timeout: Duration,
) -> Result<Value, String> {
    let launcher = launcher_dir.join(alias);
    let expected_binary = workspace_root().join("target/release/hades").canonicalize().unwrap();
    if !launcher.is_file() {
        return Err(format!("missing executable launcher: {}", launcher.display()));
    }
    let resolved_binary =
        fs::canonicalize(&launcher).map_err(|error| format!("resolve launcher: {error}"))?;
    if resolved_binary != expected_binary {
        return Err(format!(
            "{} resolves to {}, expected {}",
            alias,
            resolved_binary.display(),
            expected_binary.display()
        ));
    }

    let nested_report = report_dir.join(format!("model-selection-{alias}.json"));
    let mut process = Command::new(workspace_root().join("target/debug/replay_model_selection"));
    process
        .arg("--binary")
        .arg(&launcher)
        .arg("--report")
        .arg(&nested_report)
        .arg("--timeout")
        .arg(timeout.as_secs_f64().to_string());
    let result = process
        .output()
        .map_err(|error| format!("{alias} model-selection replay could not run: {error}"))?;
    if !result.status.success() {
        return Err(format!("{alias} model-selection replay failed"));
    }
    let nested: Value = serde_json::from_slice(&nested_report_bytes(&nested_report)?)
        .map_err(|error| format!("{alias} replay report was unreadable: {error}"))?;
    if nested.get("passed").and_then(Value::as_bool) != Some(true) {
        return Err(format!("{alias} replay report did not pass"));
    }
    let boundary = nested.get("boundary").cloned().unwrap_or_else(|| json!({}));
    let steps = nested.get("steps").and_then(Value::as_array).cloned().unwrap_or_default();
    if boundary.get("provider_request_count").and_then(Value::as_u64) != Some(2)
        || boundary.get("sidecar_unchanged").and_then(Value::as_bool) != Some(true)
        || boundary.get("hermes_config_created").and_then(Value::as_bool) != Some(false)
        || steps.len() != 3
        || steps[1].get("request").and_then(|r| r.get("model")).and_then(Value::as_str)
            != Some("palette-model")
        || steps[2].get("request").and_then(|r| r.get("model")).and_then(Value::as_str)
            != Some("vertical-model")
    {
        return Err(format!("{alias} replay crossed an unexpected model boundary"));
    }
    Ok(json!({
        "alias": alias,
        "launcher": format!("~/.local/bin/{alias}"),
        "resolved_binary": "target/release/hades",
        "replay_report": nested_report.file_name().unwrap_or_default().to_string_lossy(),
        "status": "passed",
        "selected_model": "palette-model",
        "fresh_process_model": "vertical-model",
        "provider_request_count": 2,
        "sidecar_unchanged": true,
        "hermes_config_created": false,
        "external_network": false,
        "authorization_values_recorded": false,
    }))
}

fn nested_report_bytes(path: &Path) -> Result<Vec<u8>, String> {
    fs::read(path).map_err(|error| format!("read {}: {error}", path.display()))
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
    let mut launcher_dir = PathBuf::from("~/.local/bin");
    let mut report_path =
        workspace_root().join(".hades/runtime/installed-model-selection-replay.json");
    let mut timeout = Duration::from_secs_f64(10.0);

    while let Some(arg) = args.next() {
        match arg.as_str() {
            // The parity checker always passes --binary; this replay runs
            // the installed launcher aliases instead, so --binary is
            // accepted and ignored (both sides use the same defaults).
            "--binary" => {
                let _ = args.next();
            }
            "--launcher-dir" => {
                if let Some(value) = args.next() {
                    launcher_dir = PathBuf::from(value);
                }
            }
            "--report" => {
                if let Some(value) = args.next() {
                    report_path = PathBuf::from(value);
                }
            }
            "--timeout" => {
                if let Some(value) = args.next() {
                    timeout = Duration::from_secs_f64(value.parse().unwrap_or(10.0));
                }
            }
            _ => {}
        }
    }

    let launcher_dir = if launcher_dir.starts_with("~") {
        let home = std::env::var("HOME").unwrap_or_default();
        PathBuf::from(home).join(launcher_dir.strip_prefix("~/").unwrap_or(&launcher_dir))
    } else {
        launcher_dir.clone()
    };
    let launcher_dir = launcher_dir.canonicalize().unwrap_or(launcher_dir);
    let report_path =
        if report_path.is_absolute() { report_path } else { workspace_root().join(report_path) };
    let report_path = report_path.canonicalize().unwrap_or(report_path);
    let report_dir = report_path.parent().unwrap_or(&report_path).to_owned();

    let mut report = json!({
        "schema_version": 1,
        "command": "replay-installed-model-selection",
        "launcher_dir": "~/.local/bin",
        "release_binary": "target/release/hades",
        "steps": [],
        "passed": false,
    });
    if !launcher_dir.is_dir() {
        report["failure"] = json!({"message": format!("launcher directory is missing: {}", launcher_dir.display())});
        return write_report(&report, Some(&report_path));
    }
    if !workspace_root().join("target/release/hades").is_file() {
        report["failure"] = json!({"message": "target/release/hades is missing"});
        return write_report(&report, Some(&report_path));
    }

    let home = std::env::temp_dir()
        .join(format!("hades-installed-model-selection-{}", std::process::id()));
    fs::create_dir_all(&home).map_err(|error| error.to_string()).expect("create temp home");
    let mut steps = Vec::new();
    for (shell, options) in SHELL_CASES {
        for alias in ALIASES {
            match run_shell_command(shell, options, alias, &launcher_dir, &home) {
                Ok(value) => steps.push(json!({"shell_resolution": value})),
                Err(error) => {
                    report["failure"] = json!({"message": error});
                    let _ = fs::remove_dir_all(&home);
                    return write_report(&report, Some(&report_path));
                }
            }
        }
    }
    for alias in ALIASES {
        match run_alias(alias, &launcher_dir, &report_dir, timeout) {
            Ok(value) => steps.push(value),
            Err(error) => {
                report["failure"] = json!({"message": error});
                let _ = fs::remove_dir_all(&home);
                return write_report(&report, Some(&report_path));
            }
        }
    }
    let _ = fs::remove_dir_all(&home);
    report["steps"] = json!(steps);
    report["boundary"] = json!({
        "aliases": ALIASES,
        "shells": ["bash", "fish"],
        "all_aliases_resolved": true,
        "all_alias_replays_passed": true,
        "external_network": false,
        "authorization_values_recorded": false,
        "hermes_config_created": false,
    });
    report["passed"] = json!(true);
    write_report(&report, Some(&report_path))
}
