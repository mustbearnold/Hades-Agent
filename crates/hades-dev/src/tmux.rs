//! tmux driver: the Rust port of the `replay_composer` tmux helpers
//! (HAD-132).
//!
//! The configured-family replays (composer, history) drive Hades inside
//! isolated tmux sessions instead of raw PTYs: `new-session` with a fixed
//! 120x40 window, `send-keys` for text/paste/key input, `capture-pane` for
//! screen reads, `has-session`/`kill-session` for lifecycle. This module
//! wraps those tmux subprocess calls with the same semantics as the Python
//! helpers, including `contains_marker` (which LOWERCASES before compact
//! matching — distinct from `hades_dev::replay::marker_present`).

use std::path::Path;
use std::process::Command;
use std::time::{Duration, Instant};

/// Run a `tmux` subprocess from the repo root, like `tmux_run`.
pub fn tmux_run(arguments: &[&str]) -> (i32, String, String) {
    let output = Command::new("tmux").args(arguments).current_dir(repo_root()).output();
    match output {
        Ok(output) => (
            output.status.code().unwrap_or(-1),
            String::from_utf8_lossy(&output.stdout).to_string(),
            String::from_utf8_lossy(&output.stderr).to_string(),
        ),
        Err(error) => (-1, String::new(), format!("tmux failed to start: {error}")),
    }
}

fn repo_root() -> std::path::PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("hades-dev crate is two levels under the repo root")
        .to_path_buf()
}

/// Capture the current pane contents, like `capture_screen`.
pub fn capture_screen(session: &str) -> String {
    let (code, stdout, _) = tmux_run(&["capture-pane", "-p", "-t", session]);
    if code != 0 {
        return String::new();
    }
    stdout
}

/// Whether a tmux session exists, like `session_exists`.
pub fn session_exists(session: &str) -> bool {
    tmux_run(&["has-session", "-t", session]).0 == 0
}

/// Kill a tmux session, ignoring errors, like the Python `kill-session` call.
pub fn kill_session(session: &str) {
    let _ = tmux_run(&["kill-session", "-t", session]);
}

/// Marker matching, like `contains_marker`: raw substring OR compact
/// whitespace-insensitive LOWERCASE match. Note the lowercase — this is the
/// tmux-family variant, distinct from `replay::marker_present`.
pub fn contains_marker(screen: &str, marker: &str) -> bool {
    if screen.contains(marker) {
        return true;
    }
    let compact_screen: String = screen.split_whitespace().collect::<String>().to_lowercase();
    let compact_marker: String = marker.split_whitespace().collect::<String>().to_lowercase();
    compact_screen.contains(&compact_marker)
}

/// Wait until `predicate(screen)` or the session dies or the timeout
/// elapses, like `wait_for_screen`. Returns the matching screen.
pub fn wait_for_screen<F>(
    session: &str,
    description: &str,
    predicate: F,
    timeout: Duration,
) -> Result<String, String>
where
    F: Fn(&str) -> bool,
{
    let deadline = Instant::now() + timeout;
    let mut latest = String::new();
    while Instant::now() < deadline {
        latest = capture_screen(session);
        if predicate(&latest) {
            return Ok(latest);
        }
        if !session_exists(session) {
            return Err(format!(
                "{description}: tmux session exited before the screen assertion\n{}",
                tail(&latest, 12)
            ));
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    Err(format!(
        "{description}: timed out after {:.1}s\n{}",
        timeout.as_secs_f64(),
        tail(&latest, 12)
    ))
}

fn tail(text: &str, lines: usize) -> String {
    let all: Vec<&str> = text.lines().collect();
    let start = all.len().saturating_sub(lines);
    all[start..].join("\n")
}

/// Map a contract key name to a tmux key payload, like `key_payload`.
pub fn key_payload(value: &str) -> Result<&'static str, String> {
    match value {
        "Enter" => Ok("C-m"),
        "Ctrl+A" => Ok("C-a"),
        "Ctrl+C" => Ok("C-c"),
        "Ctrl+G" => Ok("C-g"),
        "Ctrl+K" => Ok("C-k"),
        "Ctrl+V" => Ok("C-v"),
        "Backspace" => Ok("BSpace"),
        "Up" => Ok("Up"),
        "Down" => Ok("Down"),
        "Left" => Ok("Left"),
        "Right" => Ok("Right"),
        "Home" => Ok("Home"),
        "End" => Ok("End"),
        "Tab" => Ok("Tab"),
        _ => Err(format!("unsupported composer key: {value}")),
    }
}

/// Send text/paste/key input to a session, like `send_input`.
pub fn send_input(session: &str, kind: &str, value: &str) -> Result<(), String> {
    let (code, _, stderr) = match kind {
        "text" | "paste" => {
            let payload = if kind == "paste" {
                format!("\x1b[200~{value}\x1b[201~")
            } else {
                value.to_string()
            };
            tmux_run(&["send-keys", "-t", session, "-l", &payload])
        }
        "key" => {
            let payload = key_payload(value)?;
            tmux_run(&["send-keys", "-t", session, payload])
        }
        _ => return Err(format!("unsupported input kind: {kind}")),
    };
    if code != 0 {
        let detail =
            if stderr.trim().is_empty() { String::new() } else { stderr.trim().to_string() };
        return Err(format!("tmux send-keys failed: {detail}"));
    }
    Ok(())
}

/// Start a detached tmux session running `binary` at 120x40 with the given
/// environment, like `start_session`.
pub fn start_session(
    binary: &Path,
    session: &str,
    environment: &[(&str, &str)],
) -> Result<(), String> {
    let mut command = Command::new("tmux");
    command
        .arg("new-session")
        .arg("-d")
        .arg("-s")
        .arg(session)
        .arg("-x")
        .arg("120")
        .arg("-y")
        .arg("40")
        .arg("-c")
        .arg(repo_root());
    command.arg("env");
    command.arg("TERM=xterm-256color");
    for (key, value) in environment {
        command.arg(format!("{key}={value}"));
    }
    command.arg(binary);
    let output =
        command.output().map_err(|error| format!("tmux session failed to start: {error}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        return Err(format!(
            "tmux session failed to start: {}",
            if stderr.is_empty() { stdout } else { stderr }
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn contains_marker_lowercases_before_compact_match() {
        // The tmux-family contains_marker lowercases, unlike
        // replay::marker_present — this is the composer contract.
        assert!(contains_marker("Hades Agent v0.1.0", "hades agent"));
        assert!(contains_marker("a  b", "A B"));
        assert!(contains_marker("AB", "a b"));
        assert!(contains_marker("MUSING…", "musing"));
        assert!(!contains_marker("abc", "x"));
    }

    #[test]
    fn key_payload_maps_contract_keys() {
        assert_eq!(key_payload("Enter").unwrap(), "C-m");
        assert_eq!(key_payload("Ctrl+C").unwrap(), "C-c");
        assert_eq!(key_payload("Up").unwrap(), "Up");
        assert_eq!(key_payload("Backspace").unwrap(), "BSpace");
        assert!(key_payload("Shift+F5").is_err());
    }

    #[test]
    fn session_helpers_report_missing_session() {
        let ghost = format!("had132-ghost-{}", std::process::id());
        assert!(!session_exists(&ghost));
        assert_eq!(capture_screen(&ghost), "");
        kill_session(&ghost); // must not panic on a missing session
    }

    #[test]
    fn wait_for_screen_times_out_cleanly() {
        let ghost = format!("had132-ghost-wait-{}", std::process::id());
        let error = wait_for_screen(&ghost, "never", |_| false, Duration::from_millis(300))
            .expect_err("missing session should fail fast");
        assert!(error.contains("never"), "{error}");
    }
}
