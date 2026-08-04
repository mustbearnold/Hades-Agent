//! `hades-dev replay-fresh-shell-launch` — Rust port of
//! `scripts/replay_fresh_shell_launch.py` (HAD-153).
//!
//! Proves fresh Bash/Fish command resolution (command -v, --version,
//! --help through the installed launcher symlinks) and the installed TUI
//! lifecycle: startup markers in raw mode, Ctrl+C clean exit, and
//! alternate-screen/terminal restoration.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode, Stdio};
use std::time::Duration;

use hades_dev::pty::spawn_pty;
use hades_dev::replay::{
    ExitStatus, RetainedSlave, marker_present, terminal_flags, wait_for, wait_for_exit,
};
use serde_json::{Value, json};

const STARTUP_MARKERS: [&str; 4] =
    ["Hades Agent", "Underworld", "Available Tools", "Available Skills"];

/// Workspace root: crates/hades-dev -> crates -> repo root.
fn workspace_root() -> PathBuf {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir.parent().and_then(|parent| parent.parent()).unwrap_or(&manifest_dir).to_owned()
}

struct RuntimeEnvironment {
    launcher_dir: PathBuf,
    home: PathBuf,
}

impl RuntimeEnvironment {
    fn variables(&self) -> Vec<(&str, String)> {
        vec![
            ("HOME", self.home.display().to_string()),
            ("HERMES_HOME", self.home.join("hermes").display().to_string()),
            (
                "PATH",
                vec![
                    self.launcher_dir.display().to_string(),
                    "/usr/bin".to_owned(),
                    "/bin".to_owned(),
                ]
                .join(":"),
            ),
            ("TERM", "xterm-256color".to_owned()),
            ("COLUMNS", "120".to_owned()),
            ("LINES", "40".to_owned()),
        ]
    }

    fn shell_path(&self, name: &str) -> Result<PathBuf, String> {
        let path =
            vec![self.launcher_dir.display().to_string(), "/usr/bin".to_owned(), "/bin".to_owned()]
                .join(":");
        for directory in path.split(':') {
            let candidate = Path::new(directory).join(name);
            if candidate.is_file() {
                return Ok(candidate);
            }
        }
        Err(format!("required shell is unavailable: {name}"))
    }
}

fn run_shell_command(
    shell: &str,
    shell_options: &[&str],
    command_name: &str,
    launcher_dir: &Path,
    home: &Path,
) -> Result<Value, String> {
    let environment =
        RuntimeEnvironment { launcher_dir: launcher_dir.to_owned(), home: home.to_owned() };
    let shell_executable = environment.shell_path(shell)?;
    let command =
        format!("command -v {command_name}; {command_name} --version; {command_name} --help");
    let mut process = Command::new(&shell_executable);
    process.args(shell_options);
    process.arg("-c").arg(&command);
    process.env_clear();
    for (key, value) in environment.variables() {
        process.env(key, value);
    }
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

fn run_tui_case(
    shell: &str,
    shell_options: &[&str],
    command_name: &str,
    command_arguments: &[&str],
    launcher_dir: &Path,
    home: &Path,
    timeout: Duration,
) -> Result<Value, String> {
    let environment =
        RuntimeEnvironment { launcher_dir: launcher_dir.to_owned(), home: home.to_owned() };
    let shell_executable = environment.shell_path(shell)?;
    let history_home = std::env::temp_dir().join(format!(
        "hades-fresh-shell-history-{}-{}",
        shell,
        std::process::id()
    ));
    fs::create_dir_all(&history_home).map_err(|error| error.to_string())?;
    let command = format!("exec {} {}", command_name, command_arguments.join(" "));

    let mut process = Command::new(&shell_executable);
    process.args(shell_options);
    process.arg("-c").arg(&command);
    process.env_clear();
    for (key, value) in environment.variables() {
        process.env(key, value);
    }
    process.env("HERMES_HOME", history_home.join("hermes").display().to_string());
    process.stdin(Stdio::inherit());
    process.stdout(Stdio::inherit());
    process.stderr(Stdio::inherit());

    let child = hades_dev::pty::spawn_pty(&mut process, 120, 40)
        .map_err(|error| format!("{shell} {command_name}: could not spawn shell: {error}"))?;
    let mut child = child;
    let mut output = Vec::new();
    let mut reaped = false;
    let slave_path = child.slave_path.clone();

    let result = (|| -> Result<Value, String> {
        wait_for(
            &child,
            &mut output,
            &format!("{shell} {command_name} startup"),
            |text| STARTUP_MARKERS.iter().all(|marker| marker_present(text, marker)),
            timeout,
        )?;
        let slave = RetainedSlave::retain(&slave_path).map_err(|error| error.to_string())?;
        let startup_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if startup_flags.canonical || startup_flags.echo {
            return Err(format!("{shell} {command_name}: startup was not raw: {startup_flags:?}"));
        }

        hades_dev::replay::send(&child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 0 }) {
            return Err(format!("{shell} {command_name}: unexpected exit: {exit_status:?}"));
        }
        let raw_output = output.as_slice();
        if !find_sequence(raw_output, b"\x1b[?1049h") || !find_sequence(raw_output, b"\x1b[?1049l")
        {
            return Err(format!(
                "{shell} {command_name}: alternate-screen lifecycle was incomplete"
            ));
        }
        let cleanup_flags = terminal_flags(&slave).map_err(|error| error.to_string())?;
        if !cleanup_flags.canonical || !cleanup_flags.echo {
            return Err(format!(
                "{shell} {command_name}: terminal was not restored: {cleanup_flags:?}"
            ));
        }
        Ok(json!({
            "shell": shell,
            "command": command_name,
            "arguments": command_arguments,
            "startup_markers": STARTUP_MARKERS,
            "startup_raw_mode": {
                "canonical": startup_flags.canonical,
                "echo": startup_flags.echo,
            },
            "process_alive_until": "explicit Ctrl+C",
            "exit": exit_status.as_json(),
            "alternate_screen_entered": true,
            "alternate_screen_left": true,
            "terminal_restored": {
                "canonical": cleanup_flags.canonical,
                "echo": cleanup_flags.echo,
            },
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child);
    }
    let _ = fs::remove_dir_all(&history_home);
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
    let mut launcher_dir = PathBuf::from("~/.local/bin");
    let mut release_binary = PathBuf::from("target/release/hades");
    let mut report_path: Option<PathBuf> = None;
    let mut timeout = Duration::from_secs_f64(5.0);

    while let Some(arg) = args.next() {
        match arg.as_str() {
            // The parity checker always passes --binary; this replay runs
            // the installed release launcher instead, so --binary is
            // accepted and ignored (both sides use the same defaults).
            "--binary" => {
                let _ = args.next();
            }
            "--launcher-dir" => {
                if let Some(value) = args.next() {
                    launcher_dir = PathBuf::from(value);
                }
            }
            "--release-binary" => {
                if let Some(value) = args.next() {
                    release_binary = PathBuf::from(value);
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

    let launcher_dir = if launcher_dir.starts_with("~") {
        let home = std::env::var("HOME").unwrap_or_default();
        PathBuf::from(home).join(launcher_dir.strip_prefix("~/").unwrap_or(&launcher_dir))
    } else {
        launcher_dir.clone()
    };
    let launcher_dir = launcher_dir.canonicalize().unwrap_or(launcher_dir);
    let release_binary = if release_binary.is_absolute() {
        release_binary.clone()
    } else {
        // Anchor to the workspace root: crates/hades-dev -> crates -> root.
        workspace_root().join(&release_binary)
    };
    let release_binary = release_binary.canonicalize().unwrap_or(release_binary);

    let mut report = json!({
        "probe": "hades-fresh-shell-launch",
        "launcher_dir": launcher_dir.display().to_string(),
        "release_binary": release_binary.display().to_string(),
        "dimensions": {"columns": 120, "rows": 40},
        "shells": [],
        "tui_cases": [],
        "passed": false,
    });

    if !release_binary.is_file() {
        report["error"] = json!(format!(
            "release binary is missing or not executable: {}",
            release_binary.display()
        ));
        return write_report(&report, report_path.as_deref());
    }

    let mut launcher_paths = serde_json::Map::new();
    for command_name in ["hades", "Hades"] {
        let launcher = launcher_dir.join(command_name);
        let Ok(metadata) = fs::symlink_metadata(&launcher) else {
            report["error"] = json!(format!("launcher is not a symlink: {}", launcher.display()));
            return write_report(&report, report_path.as_deref());
        };
        if !metadata.file_type().is_symlink() {
            report["error"] = json!(format!("launcher is not a symlink: {}", launcher.display()));
            return write_report(&report, report_path.as_deref());
        }
        let resolved = fs::canonicalize(&launcher).unwrap_or_default();
        if resolved != release_binary {
            report["error"] = json!(format!(
                "{} resolves to {}, expected {}",
                launcher.display(),
                resolved.display(),
                release_binary.display()
            ));
            return write_report(&report, report_path.as_deref());
        }
        launcher_paths.insert(command_name.to_owned(), json!(resolved.display().to_string()));
    }
    report["launcher_paths"] = Value::Object(launcher_paths);

    let home = std::env::temp_dir().join(format!("hades-fresh-shell-home-{}", std::process::id()));
    fs::create_dir_all(&home).map_err(|error| error.to_string()).expect("create temp home");
    let mut shells = Vec::new();
    let mut tui_cases = Vec::new();
    for (shell, options) in [("bash", vec!["--noprofile", "--norc"]), ("fish", vec!["--no-config"])]
    {
        for command in ["hades", "Hades"] {
            match run_shell_command(shell, &options, command, &launcher_dir, &home) {
                Ok(value) => shells.push(value),
                Err(error) => {
                    report["error"] = json!(error);
                    let _ = fs::remove_dir_all(&home);
                    return write_report(&report, report_path.as_deref());
                }
            }
        }
    }
    report["shells"] = json!(shells);

    let cases: [(&str, &[&str], &str, &[&str]); 4] = [
        ("bash", &["--noprofile", "--norc"], "hades", &[]),
        ("bash", &["--noprofile", "--norc"], "Hades", &["tui"]),
        ("fish", &["--no-config"], "hades", &["tui"]),
        ("fish", &["--no-config"], "Hades", &[]),
    ];
    for (shell, options, command, arguments) in cases {
        match run_tui_case(shell, options, command, arguments, &launcher_dir, &home, timeout) {
            Ok(value) => tui_cases.push(value),
            Err(error) => {
                report["error"] = json!(error);
                let _ = fs::remove_dir_all(&home);
                return write_report(&report, report_path.as_deref());
            }
        }
    }
    report["tui_cases"] = json!(tui_cases);
    let _ = fs::remove_dir_all(&home);
    report["passed"] = json!(true);
    write_report(&report, report_path.as_deref())
}
