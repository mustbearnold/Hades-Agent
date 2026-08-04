//! `hades-dev tmux_hold_diff` — differential driver for the HAD-132
//! configured-family runtime extensions.
//!
//! Emits a JSON document of the pure helper behaviors (contains_marker,
//! key_payload) and real-tmux session helper results (session_exists,
//! capture_screen on a live session, send_input text/key) so
//! `scripts/check_tmux_hold_parity.py` can compare them against the Python
//! originals in `replay_composer.py`.

use std::path::Path;

use hades_dev::hold_provider::HoldProvider;
use hades_dev::tmux::{capture_screen, contains_marker, kill_session, send_input, session_exists};
use serde_json::{Value, json};

const MARKER_SAMPLES: [(&str, &str); 6] = [
    ("Hades Agent v0.1.0  Underworld", "hades agent"),
    ("HadesAgent  Underworld", "Hades Agent"),
    ("a  b", "A B"),
    ("MUSING…", "musing"),
    ("Ctrl+C to interrupt", "Ctrl+C to interrupt"),
    ("abc", "x"),
];

const KEY_SAMPLES: [&str; 14] = [
    "Enter",
    "Ctrl+A",
    "Ctrl+C",
    "Ctrl+G",
    "Ctrl+K",
    "Ctrl+V",
    "Backspace",
    "Up",
    "Down",
    "Left",
    "Right",
    "Home",
    "End",
    "Tab",
];

fn main() {
    let markers: Vec<Value> = MARKER_SAMPLES
        .iter()
        .map(|(screen, marker)| json!({"screen": screen, "marker": marker, "match": contains_marker(screen, marker)}))
        .collect();

    let keys: Vec<Value> = KEY_SAMPLES
        .iter()
        .map(|key| match hades_dev::tmux::key_payload(key) {
            Ok(payload) => json!({"key": key, "payload": payload}),
            Err(error) => json!({"key": key, "error": error}),
        })
        .collect();

    // Real tmux session: start one running `sh`, send text and a key, and
    // capture the pane; then verify session_exists and kill it.
    let session = format!("had132-diff-{}", std::process::id());
    let tmux = json!({
        "start_session": {
            "result": start_session_with_env(&session),
        },
        "exists_after_start": session_exists(&session),
        "send_text": {
            "result": send_result(send_input(&session, "text", "hello-diff")),
        },
        "send_key": {
            "result": send_result(send_input(&session, "key", "Enter")),
        },
        "capture_has_text": capture_screen(&session).contains("hello-diff"),
        "kill": {
            "result": kill_result(&session),
        },
        "exists_after_kill": session_exists(&session),
    });

    // Hold provider: request_seen gating with a real loopback request.
    let provider = HoldProvider::start().expect("hold provider start");
    let base_url = provider
        .environment()
        .iter()
        .find(|(key, _)| *key == "HADES_PROVIDER_BASE_URL")
        .map(|(_, value)| value.clone())
        .expect("base url");
    let model = provider
        .environment()
        .iter()
        .find(|(key, _)| *key == "HADES_MODEL")
        .map(|(_, value)| value.clone())
        .expect("model");
    let api_key = provider
        .environment()
        .iter()
        .find(|(key, _)| *key == "HADES_PROVIDER_API_KEY")
        .map(|(_, value)| value.clone())
        .expect("api key");
    let request_seen_before = provider.request_seen();
    let client_host = base_url.clone().replace("http://", "");
    let client = std::thread::spawn(move || {
        let _ = std::net::TcpStream::connect(client_host.as_str());
    });
    let _ = client.join();
    // Give the accept loop a moment to read the (empty) request.
    std::thread::sleep(std::time::Duration::from_millis(300));
    let request_seen_after = provider.request_seen();
    let mut provider = provider;
    provider.finish();
    let hold = json!({
        "environment": {
            "base_url_prefix": base_url.starts_with("http://127.0.0.1:"),
            "model": model,
            "api_key_empty": api_key.is_empty(),
        },
        "request_seen_before_any": request_seen_before,
        "request_seen_after_connect": request_seen_after,
    });

    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "markers": markers,
            "keys": keys,
            "tmux": tmux,
            "hold": hold,
        }))
        .expect("serialize")
    );
}

/// Start a tmux session running `sh` (not a Hades binary) with no extra
/// environment, for the helper-level differential.
fn start_session_with_env(session: &str) -> String {
    match hades_dev::tmux::start_session(Path::new("sh"), session, &[]) {
        Ok(()) => "ok".to_string(),
        Err(error) => error,
    }
}

/// Serialize a `send_input` result the way the Python replay records it.
fn send_result(result: Result<(), String>) -> &'static str {
    match result {
        Ok(()) => "ok",
        Err(_) => "error",
    }
}

/// Kill a session and record the result the way the Python replay does.
fn kill_result(session: &str) -> &'static str {
    kill_session(session);
    "ok"
}
