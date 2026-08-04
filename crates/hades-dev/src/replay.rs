//! Shared replay runtime: the Rust port of `probe_tui_lifecycle.py`
//! helpers that every Python replay imports (HAD-126).
//!
//! Provides: spawn-with-arguments on a PTY, window sizing, slave-path
//! resolution via /proc, retained slave descriptors, terminal-flags
//! inspection (canonical/echo), ANSI-stripped output cleaning, marker
//! matching with compact whitespace, wait_for with early-exit detection,
//! wait_for_exit with describe_status-shaped values, and send.

use std::fs::File;
use std::io::Write;
use std::os::fd::OwnedFd;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};

use rustix::process::{WaitOptions, WaitStatus, waitpid};
use rustix::termios::{LocalModes, tcgetattr};

use crate::pty::{PtyChild, read_available, spawn_pty};

/// Spawn a binary with arguments on a fresh 120x40 PTY with the standard
/// replay environment (TERM/COLUMNS/LINES/HERMES_HOME), mirroring
/// `replay_cli_launch.spawn` and `probe_tui_lifecycle.spawn`.
pub struct ReplayChild {
    pub child: PtyChild,
    pub slave_path: String,
    pub history_home: PathBuf,
}

pub fn spawn(binary: &Path, arguments: &[&str]) -> std::io::Result<ReplayChild> {
    spawn_with_env(binary, arguments, &[], &[])
}

/// Spawn with extra environment entries and a strip list (provider vars),
/// mirroring `replay_unconfigured_startup.spawn`.
pub fn spawn_with_env(
    binary: &Path,
    arguments: &[&str],
    extra: &[(&str, &str)],
    strip: &[&str],
) -> std::io::Result<ReplayChild> {
    let history_home =
        std::env::temp_dir().join(format!("hades-pty-history-{}", std::process::id()));
    std::fs::create_dir_all(&history_home)?;

    let mut command = Command::new(binary);
    command.args(arguments);
    command.env("TERM", "xterm-256color");
    command.env("COLUMNS", "120");
    command.env("LINES", "40");
    command.env("HOME", &history_home);
    command.env("HERMES_HOME", &history_home);
    for (key, value) in extra {
        command.env(key, value);
    }
    for key in strip {
        command.env_remove(key);
    }

    let child = spawn_pty(&mut command, 120, 40)?;
    let slave_path = child.slave_path.clone();
    Ok(ReplayChild { child, slave_path, history_home })
}

/// Resolve a child's fd 0 to its PTY slave across launcher handoff, like
/// `slave_path_for_pid` (reads /proc/<pid>/fd/0).
pub fn slave_path_for_pid(pid: i32, timeout: Duration) -> std::io::Result<String> {
    let deadline = Instant::now() + timeout;
    let mut last = "<unavailable>".to_owned();
    while Instant::now() < deadline {
        let link = format!("/proc/{pid}/fd/0");
        match std::fs::read_link(&link) {
            Ok(path) => {
                last = path.to_string_lossy().to_string();
                if last.starts_with("/dev/pts/") {
                    return Ok(last);
                }
            }
            Err(_) => last = "<process exited>".to_owned(),
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    Err(std::io::Error::new(
        std::io::ErrorKind::NotConnected,
        format!("child fd 0 did not resolve to a PTY slave: {last}"),
    ))
}

/// Keep a slave descriptor open so termios state survives child exit.
pub struct RetainedSlave {
    _file: File,
}

impl RetainedSlave {
    pub fn retain(slave_path: &str) -> std::io::Result<Self> {
        let file = File::options().read(true).write(true).open(slave_path)?;
        Ok(Self { _file: file })
    }
}

/// Terminal flags for a slave path, like `terminal_flags` (canonical/echo
/// from termios local modes).
pub fn terminal_flags(slave: &RetainedSlave) -> std::io::Result<TerminalFlags> {
    let termios = tcgetattr(&slave._file)?;
    let local = termios.local_modes;
    Ok(TerminalFlags {
        canonical: local.contains(LocalModes::ICANON),
        echo: local.contains(LocalModes::ECHO),
    })
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TerminalFlags {
    pub canonical: bool,
    pub echo: bool,
}

/// Exit status shape, like `describe_status`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ExitStatus {
    Exit { code: i32 },
    Signal { number: i32 },
    Other { raw: i32 },
}

impl ExitStatus {
    pub fn describe(status: WaitStatus) -> Self {
        if let Some(code) = status.exit_status() {
            ExitStatus::Exit { code }
        } else if let Some(number) = status.terminating_signal() {
            ExitStatus::Signal { number }
        } else {
            ExitStatus::Other { raw: status.as_raw() }
        }
    }

    pub fn as_json(&self) -> serde_json::Value {
        match self {
            ExitStatus::Exit { code } => serde_json::json!({"kind": "exit", "code": code}),
            ExitStatus::Signal { number } => {
                serde_json::json!({"kind": "signal", "number": number})
            }
            ExitStatus::Other { raw } => serde_json::json!({"kind": "other", "raw": raw}),
        }
    }
}

/// Strip ANSI escapes and CR from raw output, like `clean_output`.
pub fn clean_output(output: &[u8]) -> String {
    let text = String::from_utf8_lossy(output).replace('\r', "");
    strip_ansi(&text)
}

fn strip_ansi(text: &str) -> String {
    let mut result = String::with_capacity(text.len());
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
                _ => {}
            }
        } else {
            result.push(char);
        }
    }
    result
}

/// Marker matching, like `marker_present`: direct substring or compact
/// whitespace-insensitive match.
pub fn marker_present(text: &str, marker: &str) -> bool {
    if text.contains(marker) {
        return true;
    }
    let compact_text: String = text.split_whitespace().collect();
    let compact_marker: String = marker.split_whitespace().collect();
    compact_text.contains(&compact_marker)
}

/// Wait until `predicate(cleaned_text)` or the child exits early or the
/// timeout elapses, like `wait_for`.
pub fn wait_for<F>(
    child: &PtyChild,
    output: &mut Vec<u8>,
    description: &str,
    predicate: F,
    timeout: Duration,
) -> Result<(), String>
where
    F: Fn(&str) -> bool,
{
    let deadline = Instant::now() + timeout;
    loop {
        output.extend_from_slice(&read_available(&child.master));
        let cleaned = clean_output(output);
        if predicate(&cleaned) {
            return Ok(());
        }
        if let Some(status) = try_wait(child)? {
            return Err(format!(
                "{description}: process exited early with {}\n{}",
                serde_json::to_string(&ExitStatus::describe(status).as_json()).unwrap_or_default(),
                output_tail(output)
            ));
        }
        if Instant::now() >= deadline {
            return Err(format!("{description}: timed out\n{}", output_tail(output)));
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

/// Non-blocking wait; returns the status if the child has exited.
pub fn try_wait(child: &PtyChild) -> Result<Option<WaitStatus>, String> {
    let pid = rustix::process::Pid::from_child(&child.child);
    let result = waitpid(Some(pid), WaitOptions::NOHANG)
        .map_err(|error| format!("waitpid failed: {error}"))?;
    Ok(result.map(|(_, status)| status))
}

/// Wait until `predicate(rendered_screen)` — the predicate receives the
/// RENDERED screen text (rebuilt from raw bytes via the Screen emulator),
/// not the raw byte stream. The animated startup logo emits interleaved
/// sparse-redraw cell writes that fragment typed text in the raw stream;
/// the reconstructed screen — the view a real terminal shows — keeps it
/// contiguous.
pub fn wait_for_rendered<F>(
    child: &PtyChild,
    output: &mut Vec<u8>,
    description: &str,
    predicate: F,
    timeout: Duration,
) -> Result<(), String>
where
    F: Fn(&str) -> bool,
{
    let deadline = Instant::now() + timeout;
    loop {
        output.extend_from_slice(&read_available(&child.master));
        let mut screen = crate::screen::Screen::new(120, 40);
        screen.feed(output);
        let rendered = screen.lines().join("\n");
        if predicate(&rendered) {
            return Ok(());
        }
        if let Some(status) = try_wait(child)? {
            return Err(format!(
                "{description}: process exited early with {}\n{}",
                serde_json::to_string(&ExitStatus::describe(status).as_json()).unwrap_or_default(),
                output_tail(output)
            ));
        }
        if Instant::now() >= deadline {
            return Err(format!("{description}: timed out\n{}", output_tail(output)));
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

/// Wait for the child to exit, draining output, like `wait_for_exit`.
pub fn wait_for_exit(
    child: &PtyChild,
    output: &mut Vec<u8>,
    timeout: Duration,
) -> Result<WaitStatus, String> {
    let deadline = Instant::now() + timeout;
    loop {
        output.extend_from_slice(&read_available(&child.master));
        if let Some(status) = try_wait(child)? {
            // Drain for a short grace period after exit, like the Python.
            let drain_deadline = Instant::now() + Duration::from_millis(50);
            while Instant::now() < drain_deadline {
                output.extend_from_slice(&read_available(&child.master));
                std::thread::sleep(Duration::from_millis(10));
            }
            return Ok(status);
        }
        if Instant::now() >= deadline {
            return Err(format!(
                "process did not exit within {:.1}s\n{}",
                timeout.as_secs_f64(),
                output_tail(output)
            ));
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

/// Last 12 lines of cleaned output, like `output_tail`.
pub fn output_tail(output: &[u8]) -> String {
    let cleaned = clean_output(output);
    let lines: Vec<&str> = cleaned.lines().collect();
    let start = lines.len().saturating_sub(12);
    lines[start..].join("\n")
}

/// Send a payload to the child's stdin, like `send`.
pub fn send(master: &OwnedFd, payload: &[u8]) -> std::io::Result<()> {
    crate::pty::write_bytes(master, payload)
}

/// Write the ready config into a history home, mirroring
/// `write_ready_config` from the probe harness (loopback-only, synthetic
/// key — never a real credential).
pub fn write_ready_config(home: &Path, base_url: &str, api_key: &str) -> std::io::Result<()> {
    let config = format!(
        "model:\n  provider: custom\n  default: palette-model\n  base_url: {base_url}\n  api_key: {api_key}\ncustom_providers:\n  - name: palette-loopback\n    base_url: {base_url}\n    api_key: {api_key}\n    model: palette-model\n"
    );
    let mut file = File::create(home.join("config.yaml"))?;
    file.write_all(config.as_bytes())?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clean_output_strips_ansi_and_cr() {
        let cleaned = clean_output(b"\x1b[31mred\x1b[0m\r\ntext\x1b]0;title\x07");
        assert_eq!(cleaned, "red\ntext");
    }

    #[test]
    fn marker_present_compacts_whitespace() {
        assert!(marker_present("Hades Agent v0.1.0", "Hades Agent"));
        assert!(marker_present("a  b", "a b"));
        assert!(marker_present("ab", "a b"));
        assert!(!marker_present("abc", "x"));
    }

    #[test]
    fn output_tail_keeps_last_twelve_lines() {
        let mut output = Vec::new();
        for index in 0..20 {
            output.extend_from_slice(format!("line {index}\n").as_bytes());
        }
        let tail = output_tail(&output);
        assert_eq!(tail.lines().count(), 12);
        assert!(tail.starts_with("line 8"));
    }

    #[test]
    fn spawn_and_window_size() {
        let binary = Path::new("sh");
        let mut child = spawn(binary, &["-c", "stty size; sleep 1"]).expect("spawn");
        let mut output = Vec::new();
        wait_for(
            &child.child,
            &mut output,
            "stty",
            |text| text.contains("40 120"),
            Duration::from_secs(5),
        )
        .expect("window size echoed");
        crate::pty::stop(&mut child.child.child);
    }

    #[test]
    fn early_exit_detection_reports_status() {
        let binary = Path::new("sh");
        let mut child = spawn(binary, &["-c", "exit 3"]).expect("spawn");
        let mut output = Vec::new();
        let error = wait_for(&child.child, &mut output, "never", |_| false, Duration::from_secs(5))
            .expect_err("should detect early exit");
        assert!(error.contains("exit"), "{error}");
        assert!(error.contains("\"code\":3") || error.contains("\"code\": 3"), "{error}");
        crate::pty::stop(&mut child.child.child);
    }

    #[test]
    fn wait_for_exit_returns_status() {
        let binary = Path::new("sh");
        let mut child = spawn(binary, &["-c", "exit 7"]).expect("spawn");
        let mut output = Vec::new();
        let status =
            wait_for_exit(&child.child, &mut output, Duration::from_secs(5)).expect("exit");
        assert_eq!(ExitStatus::describe(status), ExitStatus::Exit { code: 7 });
        crate::pty::stop(&mut child.child.child);
    }

    #[test]
    fn terminal_flags_reflect_raw_mode() {
        let binary = Path::new("sh");
        let mut child = spawn(binary, &["-c", "sleep 2"]).expect("spawn");
        let slave = RetainedSlave::retain(&child.slave_path).expect("retain");
        // The child hasn't put the terminal in raw mode yet, so canonical
        // and echo are both set by default.
        let flags = terminal_flags(&slave).expect("flags");
        assert!(flags.canonical);
        assert!(flags.echo);
        crate::pty::stop(&mut child.child.child);
    }

    #[test]
    fn write_ready_config_round_trips() {
        let home = std::env::temp_dir().join(format!("hades-config-test-{}", std::process::id()));
        std::fs::create_dir_all(&home).unwrap();
        write_ready_config(&home, "http://127.0.0.1:8765/v1", "sk-test-key").unwrap();
        let text = std::fs::read_to_string(home.join("config.yaml")).unwrap();
        assert!(text.contains("palette-model"));
        assert!(text.contains("http://127.0.0.1:8765/v1"));
        let _ = std::fs::remove_dir_all(&home);
    }
}
