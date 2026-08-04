//! `hades-dev replay-provider-recovery` — Rust port of
//! `scripts/replay_provider_recovery.py` (HAD-160).
//!
//! Replays safe Hades provider failure recovery and explicit follow-up
//! prompts in an isolated direct PTY across three failure fixtures served
//! by a loopback server: an HTTP 500 error, malformed SSE, and an
//! incomplete stream (deltas without `[DONE]`). Each case asserts the
//! provider error is visible, the TUI returns to ready without any
//! automatic follow-up request, the partial answer survives the
//! incomplete-stream case, a user-typed follow-up clears the notice and
//! produces exactly one recovered request (full SSE stream), and Ctrl+C
//! exits 0 with the terminal restored. Every request is recorded and
//! checked against the sanitized local boundary (no credentials, loopback
//! provider/model from the persisted sidecar).
//!
//! All post-startup typed/streamed markers are matched on the RENDERED
//! screen (`wait_for_rendered`) because the animated startup logo emits
//! interleaved sparse-redraw cell writes that fragment raw bytes; startup
//! markers stay on raw `wait_for`, mirroring the Python replay.

use std::io::{Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use hades_dev::pty::read_available;
use hades_dev::replay::{
    ExitStatus, ReplayChild, RetainedSlave, TerminalFlags, marker_present, spawn_with_env,
    terminal_flags, wait_for, wait_for_exit, wait_for_rendered,
};
use hades_dev::screen::Screen;
use serde_json::{Value, json};

const CHAT_PATH: &str = "/v1/chat/completions";
const CASES: [&str; 3] = ["http-error", "malformed-sse", "incomplete-stream"];
const FOLLOW_UP: &str = "recovery follow-up";
const FIRST_PROMPT: &str = "failure probe prompt";
const RECOVERED_ANSWER: &str = "Recovered answer.";
const PARTIAL_ANSWER: &str = "Partial answer before failure.";
const SENSITIVE_ENV_PARTS: [&str; 6] =
    ["API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "ACCESS_KEY"];
const STRIP_ENV: [&str; 3] = ["HADES_PROVIDER_BASE_URL", "HADES_MODEL", "HADES_PROVIDER_API_KEY"];

/// One recorded provider request, like the Python replay's `records`.
struct RequestRecord {
    method: String,
    path: String,
    content_type: String,
    authorization_present: bool,
    body: Value,
}

/// Shared server state: the active failure case, recorded requests, and
/// the recovered-stream completion event.
struct ServerState {
    case: Mutex<String>,
    records: Mutex<Vec<RequestRecord>>,
    recovered: AtomicBool,
    shutdown: AtomicBool,
}

/// Parsed request head: header block end plus the fields the replay asserts.
struct ParsedHead {
    header_end: usize,
    method: String,
    path: String,
    content_type: String,
    authorization_present: bool,
    content_length: usize,
}

/// Parse the HTTP head (request line + headers, up to `\r\n\r\n`).
fn parse_head(buf: &[u8]) -> Result<ParsedHead, String> {
    let header_end = buf
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(|| "request head did not end with \\r\\n\\r\\n".to_string())?;
    let header_block = &buf[..header_end];
    let mut method = String::new();
    let mut path = String::new();
    let mut content_type = String::new();
    let mut authorization_present = false;
    let mut content_length = 0usize;
    for line in header_block.split(|&byte| byte == b'\n') {
        let line = line.strip_suffix(b"\r").unwrap_or(line);
        if line.is_empty() {
            continue;
        }
        let text = String::from_utf8_lossy(line);
        if path.is_empty() {
            // Request line: METHOD PATH HTTP/1.1
            let mut parts = text.split_whitespace();
            if let Some(part) = parts.next() {
                method = part.to_string();
            }
            if let Some(part) = parts.next() {
                path = part.to_string();
            }
            continue;
        }
        if let Some((key, value)) = text.split_once(':') {
            match key.trim().to_ascii_lowercase().as_str() {
                "content-length" => content_length = value.trim().parse().unwrap_or(0),
                "content-type" => content_type = value.trim().to_string(),
                "authorization" => authorization_present = true,
                _ => {}
            }
        }
    }
    Ok(ParsedHead { header_end, method, path, content_type, authorization_present, content_length })
}

/// Read one request: head plus the Content-Length body.
fn read_request(stream: &mut TcpStream) -> Result<RequestRecord, String> {
    let mut buf = Vec::new();
    let mut tmp = [0u8; 8192];
    let head = loop {
        let count =
            stream.read(&mut tmp).map_err(|error| format!("request read failed: {error}"))?;
        if count == 0 {
            return Err("request ended inside the head".to_string());
        }
        buf.extend_from_slice(&tmp[..count]);
        if buf.windows(4).any(|window| window == b"\r\n\r\n") {
            break parse_head(&buf)?;
        }
    };
    let mut body_bytes: Vec<u8> = buf[head.header_end + 4..].to_vec();
    while body_bytes.len() < head.content_length {
        let count =
            stream.read(&mut tmp).map_err(|error| format!("request body read failed: {error}"))?;
        if count == 0 {
            break;
        }
        body_bytes.extend_from_slice(&tmp[..count]);
    }
    body_bytes.truncate(head.content_length);
    let body = serde_json::from_slice(&body_bytes).unwrap_or(Value::Null);
    Ok(RequestRecord {
        method: head.method,
        path: head.path,
        content_type: head.content_type,
        authorization_present: head.authorization_present,
        body,
    })
}

/// A compact SSE `data:` frame, like `sse_payload` (serde_json's default
/// separators match Python's `separators=(',', ':')`).
fn sse_payload(payload: &Value) -> Vec<u8> {
    format!("data: {}\n\n", serde_json::to_string(payload).expect("serialize payload")).into_bytes()
}

fn role_delta() -> Vec<u8> {
    sse_payload(&json!({"choices": [{"delta": {"role": "assistant"}}]}))
}

fn content_delta(content: &str) -> Vec<u8> {
    sse_payload(&json!({"choices": [{"delta": {"content": content}}]}))
}

fn finish_delta() -> Vec<u8> {
    sse_payload(&json!({"choices": [{"delta": {}, "finish_reason": "stop"}]}))
}

/// Respond to one request, mirroring the Python handler: request 1 of the
/// `http-error` case is a 500 with a JSON error body; request 1 of
/// `malformed-sse` writes `data: {not-json}`; request 1 of
/// `incomplete-stream` sends the role + partial content deltas without
/// `[DONE]`; every other request streams the full recovered SSE response
/// (role, recovered answer, finish, `[DONE]`) with 20ms pacing and then
/// sets the recovered event.
fn respond(stream: &mut TcpStream, state: &ServerState, request_number: usize, case: &str) {
    if request_number == 1 && case == "http-error" {
        let body = br#"{"error":{"message":"synthetic provider failure"}}"#;
        if stream
            .write_all(
                format!(
                    "HTTP/1.0 500 Internal Server Error\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    body.len()
                )
                .as_bytes(),
            )
            .is_err()
        {
            return;
        }
        let _ = stream.write_all(body);
        let _ = stream.flush();
        return;
    }

    if stream
        .write_all(
            b"HTTP/1.0 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\nConnection: close\r\n\r\n",
        )
        .is_err()
    {
        return;
    }

    if request_number == 1 && case == "malformed-sse" {
        let _ = stream.write_all(b"data: {not-json}\n\n");
        let _ = stream.flush();
        return;
    }

    if request_number == 1 && case == "incomplete-stream" {
        for chunk in [role_delta(), content_delta(PARTIAL_ANSWER)] {
            if stream.write_all(&chunk).is_err() {
                return;
            }
            let _ = stream.flush();
        }
        return;
    }

    for chunk in [
        role_delta(),
        content_delta(RECOVERED_ANSWER),
        finish_delta(),
        b"data: [DONE]\n\n".to_vec(),
    ] {
        if stream.write_all(&chunk).is_err() {
            return;
        }
        let _ = stream.flush();
        std::thread::sleep(Duration::from_millis(20));
    }
    state.recovered.store(true, Ordering::SeqCst);
}

fn handle_connection(mut stream: TcpStream, state: Arc<ServerState>) {
    let _ = stream.set_nodelay(true);
    let record = match read_request(&mut stream) {
        Ok(record) => record,
        Err(_) => return,
    };
    let (request_number, case) = {
        let mut records = state.records.lock().unwrap();
        records.push(record);
        (records.len(), state.case.lock().unwrap().clone())
    };
    respond(&mut stream, &state, request_number, &case);
    let _ = stream.shutdown(Shutdown::Both);
}

/// Accept loop on a non-blocking listener; exits on the shutdown flag.
fn serve(listener: TcpListener, state: Arc<ServerState>) {
    let _ = listener.set_nonblocking(true);
    loop {
        if state.shutdown.load(Ordering::SeqCst) {
            break;
        }
        match listener.accept() {
            Ok((stream, _)) => {
                let state = Arc::clone(&state);
                std::thread::spawn(move || handle_connection(stream, state));
            }
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                std::thread::sleep(Duration::from_millis(20));
            }
            Err(_) => break,
        }
    }
}

/// Start the loopback server on an ephemeral port.
fn start_server() -> std::io::Result<(u16, Arc<ServerState>, std::thread::JoinHandle<()>)> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let port = listener.local_addr()?.port();
    let state = Arc::new(ServerState {
        case: Mutex::new(String::new()),
        records: Mutex::new(Vec::new()),
        recovered: AtomicBool::new(false),
        shutdown: AtomicBool::new(false),
    });
    let thread_state = Arc::clone(&state);
    let handle = std::thread::spawn(move || serve(listener, thread_state));
    Ok((port, state, handle))
}

/// Reset the server for a new case, like `RecoveryServer.reset`.
fn reset(state: &ServerState, case: &str) {
    *state.case.lock().unwrap() = case.to_string();
    state.records.lock().unwrap().clear();
    state.recovered.store(false, Ordering::SeqCst);
}

fn record_count(state: &ServerState) -> usize {
    state.records.lock().unwrap().len()
}

/// Wait for the recovered-stream completion event, like
/// `server.recovered.wait(timeout)`.
fn wait_recovered(state: &ServerState, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if state.recovered.load(Ordering::SeqCst) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    state.recovered.load(Ordering::SeqCst)
}

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("hades-dev crate is two levels under the repo root")
        .to_path_buf()
}

/// The setup step: run `hades setup --local <loopback-url> vertical-model`
/// and assert the sanitized sidecar contract, like `run_setup`.
fn run_setup(binary: &Path, home: &Path, endpoint: &str) -> Result<Value, String> {
    let output = Command::new(binary)
        .args(["setup", "--local", endpoint, "vertical-model"])
        .current_dir(repo_root())
        .env("HERMES_HOME", home)
        .env_remove("HADES_PROVIDER_BASE_URL")
        .env_remove("HADES_MODEL")
        .env_remove("HADES_PROVIDER_API_KEY")
        .output()
        .map_err(|error| format!("setup command failed: {error}"))?;
    let text = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    if !output.status.success() {
        return Err(format!("setup command failed: {}", text.trim()));
    }
    for marker in ["Hades local setup complete", "Provider: loopback", "Model: vertical-model"] {
        if !text.contains(marker) {
            return Err(format!("missing setup marker: {marker}"));
        }
    }
    let sidecar = home.join("hades-local-provider.conf");
    let contents = std::fs::read_to_string(&sidecar)
        .map_err(|error| format!("local provider sidecar was not created: {error}"))?;
    if !contents.contains("vertical-model") || contents.contains("api_key") {
        return Err("sidecar was not sanitized".to_string());
    }
    if home.join("config.yaml").exists() {
        return Err("setup overwrote or created Hermes config.yaml".to_string());
    }
    Ok(json!({
        "status": "passed",
        "command": "hades setup --local <loopback-url> vertical-model",
        "provider": "loopback",
        "model": "vertical-model",
        "sidecar": "~/.hermes/hades-local-provider.conf",
        "hermes_config_unchanged": true,
        "credential_persisted": false,
    }))
}

/// Build the child-environment strip list like the Python replay's
/// filtered environment: every variable whose UPPERCASE name contains a
/// sensitive part (API_KEY/TOKEN/SECRET/PASSWORD/PRIVATE_KEY/ACCESS_KEY)
/// plus the three provider variables (the base URL matches no sensitive
/// part and must be stripped explicitly).
fn sensitive_strip_list() -> Vec<String> {
    let mut names: Vec<String> = std::env::vars()
        .map(|(key, _)| key)
        .filter(|key| {
            let upper = key.to_ascii_uppercase();
            SENSITIVE_ENV_PARTS.iter().any(|part| upper.contains(part))
        })
        .collect();
    names.extend(STRIP_ENV.iter().map(|name| name.to_string()));
    names
}

/// Spawn Hades with the Python replay's exact isolated environment: the
/// live environment minus sensitive variables and provider overrides,
/// with HERMES_HOME pointed at the isolated home (the persisted sidecar
/// supplies the loopback provider).
fn spawn_isolated(binary: &Path, home: &Path) -> Result<ReplayChild, String> {
    let home_str = home.to_str().ok_or_else(|| "non-UTF-8 home path".to_string())?;
    let real_home = std::env::var("HOME").unwrap_or_default();
    let strip = sensitive_strip_list();
    let strip_refs: Vec<&str> = strip.iter().map(String::as_str).collect();
    spawn_with_env(
        binary,
        &[],
        &[("HERMES_HOME", home_str), ("HOME", real_home.as_str())],
        &strip_refs,
    )
    .map_err(|error| error.to_string())
}

/// Reconstruct the on-screen text (what a real terminal shows), like
/// `modeled_marker`'s Screen feed.
fn rendered_text(output: &[u8]) -> String {
    let mut screen = Screen::new(120, 40);
    screen.feed(output);
    screen.lines().join("\n")
}

/// Read PTY flags across the short post-exec ioctl race (retry on errno 25
/// ENOTTY), like `stable_terminal_flags`.
fn stable_terminal_flags(slave: &RetainedSlave) -> Result<TerminalFlags, String> {
    let mut last_error: Option<std::io::Error> = None;
    for _ in 0..20 {
        match terminal_flags(slave) {
            Ok(flags) => return Ok(flags),
            Err(error) => {
                if error.raw_os_error() != Some(25) {
                    return Err(error.to_string());
                }
                last_error = Some(error);
                std::thread::sleep(Duration::from_millis(10));
            }
        }
    }
    Err(format!(
        "terminal flags stayed unavailable: {}",
        last_error.map_or_else(|| "unknown".to_owned(), |error| error.to_string())
    ))
}

fn find_sequence(haystack: &[u8], needle: &[u8]) -> bool {
    haystack.windows(needle.len()).any(|window| window == needle)
}

/// One recovery case: first request fails per the fixture, the TUI shows
/// the provider error and returns to ready with no automatic retry, a
/// user-typed follow-up recovers with exactly one more request, and
/// Ctrl+C exits 0 with the terminal restored.
fn run_case(
    binary: &Path,
    home: &Path,
    state: &ServerState,
    case: &str,
    timeout: Duration,
) -> Result<Value, String> {
    reset(state, case);
    let mut child = spawn_isolated(binary, home)?;
    let mut output = Vec::new();
    let mut reaped = false;
    let slave = RetainedSlave::retain(&child.slave_path)
        .map_err(|error| format!("retain slave: {error}"))?;

    let result = (|| -> Result<Value, String> {
        wait_for(
            &child.child,
            &mut output,
            &format!("{case}-startup"),
            |text| text.contains("Hades Agent") && marker_present(text, "ready"),
            timeout,
        )?;
        hades_dev::replay::send(&child.child.master, FIRST_PROMPT.as_bytes())
            .map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(100));
        hades_dev::replay::send(&child.child.master, b"\r").map_err(|error| error.to_string())?;
        wait_for(
            &child.child,
            &mut output,
            &format!("{case}-failure-request"),
            |_text| record_count(state) >= 1,
            timeout,
        )?;
        wait_for_rendered(
            &child.child,
            &mut output,
            &format!("{case}-failure-visible"),
            |text| marker_present(text, "Provider error:"),
            timeout,
        )?;
        std::thread::sleep(Duration::from_millis(250));
        output.extend_from_slice(&read_available(&child.child.master));
        if record_count(state) != 1 {
            return Err(format!(
                "{case}-no-automatic-follow-up: failure caused an automatic follow-up request (count={})",
                record_count(state)
            ));
        }
        let rendered = rendered_text(&output);
        if marker_present(&rendered, "Ctrl+C to interrupt") {
            return Err(format!(
                "{case}-ready-state: provider failure left the busy interrupt surface active"
            ));
        }
        let partial_visible = marker_present(&rendered, PARTIAL_ANSWER);
        if case == "incomplete-stream" && !partial_visible {
            return Err(format!(
                "{case}-partial-response: incomplete stream discarded already-rendered assistant text"
            ));
        }

        hades_dev::replay::send(&child.child.master, FOLLOW_UP.as_bytes())
            .map_err(|error| error.to_string())?;
        wait_for_rendered(
            &child.child,
            &mut output,
            &format!("{case}-notice-cleared"),
            |text| marker_present(text, FOLLOW_UP) && !marker_present(text, "Provider error:"),
            timeout,
        )?;
        hades_dev::replay::send(&child.child.master, b"\r").map_err(|error| error.to_string())?;
        wait_for(
            &child.child,
            &mut output,
            &format!("{case}-follow-up-request"),
            |_text| record_count(state) >= 2,
            timeout,
        )?;
        wait_for_rendered(
            &child.child,
            &mut output,
            &format!("{case}-recovered-answer"),
            |text| marker_present(text, RECOVERED_ANSWER),
            timeout,
        )?;
        if !wait_recovered(state, timeout) {
            return Err(format!("{case}-recovered-answer: follow-up stream did not complete"));
        }
        std::thread::sleep(Duration::from_millis(200));
        if record_count(state) != 2 {
            return Err(format!(
                "{case}-request-count: follow-up caused an unexpected request count (count={})",
                record_count(state)
            ));
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 0 }) {
            return Err(format!("{case}-cleanup: unexpected exit status: {exit_status:?}"));
        }
        let flags = stable_terminal_flags(&slave)?;
        if !find_sequence(&output, b"\x1b[?1049l") || !flags.canonical || !flags.echo {
            return Err(format!("{case}-cleanup: terminal restoration failed: {flags:?}"));
        }

        let (prompts, requests) = {
            let records = state.records.lock().unwrap();
            if records.len() != 2 {
                return Err(format!(
                    "{case}-request-count: expected two requests, got {}",
                    records.len()
                ));
            }
            let mut prompts = Vec::new();
            let mut requests = Vec::new();
            for record in records.iter() {
                if record.method != "POST"
                    || record.path != CHAT_PATH
                    || record.content_type != "application/json"
                    || record.authorization_present
                    || record.body.get("model").and_then(Value::as_str) != Some("vertical-model")
                    || record.body.get("stream").and_then(Value::as_bool) != Some(true)
                {
                    return Err(format!(
                        "{case}-request-boundary: request crossed the local sanitized boundary"
                    ));
                }
                let prompt = record
                    .body
                    .get("messages")
                    .and_then(Value::as_array)
                    .and_then(|messages| messages.last())
                    .and_then(|message| message.get("content"))
                    .cloned()
                    .unwrap_or(Value::Null);
                prompts.push(prompt.clone());
                let roles: Vec<Value> = record
                    .body
                    .get("messages")
                    .and_then(Value::as_array)
                    .map(|messages| {
                        messages
                            .iter()
                            .map(|message| message.get("role").cloned().unwrap_or(Value::Null))
                            .collect()
                    })
                    .unwrap_or_default();
                requests.push(json!({
                    "method": record.method,
                    "path": record.path,
                    "content_type": record.content_type,
                    "authorization_present": record.authorization_present,
                    "model": record.body.get("model").cloned().unwrap_or(Value::Null),
                    "message_roles": roles,
                    "prompt": prompt,
                    "stream": record.body.get("stream").cloned().unwrap_or(Value::Null),
                }));
            }
            (prompts, requests)
        };
        if prompts != [json!(FIRST_PROMPT), json!(FOLLOW_UP)] {
            return Err(format!(
                "{case}-request-boundary: unexpected prompt sequence: {prompts:?}"
            ));
        }

        Ok(json!({
            "id": case,
            "status": "passed",
            "failure": {
                "provider_error_visible": true,
                "ready_after_failure": true,
                "automatic_follow_up_requests": 0,
                "partial_response_preserved": partial_visible,
            },
            "follow_up": {
                "prompt": FOLLOW_UP,
                "notice_cleared_on_edit": true,
                "recovered_answer": RECOVERED_ANSWER,
                "request_count": 2,
            },
            "requests": requests,
            "cleanup": {
                "exit": exit_status.as_json(),
                "alternate_screen_left": true,
                "terminal_restored": {"canonical": flags.canonical, "echo": flags.echo},
            },
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child.child);
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
        let _ = file.write_all(text.as_bytes());
        let _ = file.write_all(b"\n");
    }
    println!("{text}");
    if status == 0 { ExitCode::SUCCESS } else { ExitCode::from(status) }
}

fn main() -> ExitCode {
    let mut args = std::env::args().skip(1);
    let mut binary = PathBuf::from("target/debug/hades");
    let mut report_path: Option<PathBuf> = None;
    let mut timeout = Duration::from_secs_f64(8.0);

    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--binary" => {
                if let Some(value) = args.next() {
                    binary = PathBuf::from(value);
                }
            }
            "--report" => {
                if let Some(value) = args.next() {
                    report_path = Some(PathBuf::from(value));
                }
            }
            "--timeout" => {
                if let Some(value) = args.next() {
                    timeout = Duration::from_secs_f64(value.parse().unwrap_or(8.0));
                }
            }
            _ => {}
        }
    }

    let binary = binary.canonicalize().unwrap_or_else(|_| binary.clone());
    let mut report = json!({
        "schema_version": 1,
        "command": "replay-provider-recovery",
        "binary": binary.to_string_lossy(),
        "dimensions": {"columns": 120, "rows": 40, "emulator": "direct PTY"},
        "steps": [],
        "passed": false,
    });
    let home = std::env::temp_dir().join(format!("hades-provider-recovery-{}", std::process::id()));
    let _ = std::fs::create_dir_all(&home);
    let (port, state, server_thread) = match start_server() {
        Ok(server) => server,
        Err(error) => {
            report["failure"] = json!({"message": format!("loopback server failed: {error}")});
            return write_report(&report, report_path.as_deref(), 1);
        }
    };
    let endpoint = format!("http://127.0.0.1:{port}/v1");

    let mut status = 0u8;
    if !binary.is_file() {
        report["failure"] = json!({"message": format!("binary not found: {}", binary.display())});
        status = 1;
    } else {
        let result = run_setup(&binary, &home, &endpoint).and_then(|setup| {
            let mut steps = vec![setup];
            for case in CASES {
                steps.push(run_case(&binary, &home, &state, case, timeout)?);
            }
            if home.join("config.yaml").exists() {
                return Err(
                    "config-boundary: Hermes config.yaml was created or changed".to_string()
                );
            }
            Ok(steps)
        });
        match result {
            Ok(steps) => {
                report["steps"] = json!(steps);
                report["boundaries"] = json!({
                    "automatic_retries": false,
                    "follow_up_is_user_submitted": true,
                    "provider": "loopback",
                    "credentials": "none",
                    "hermes_config_mutation": false,
                });
                report["passed"] = json!(true);
            }
            Err(error) => {
                report["failure"] = json!({"message": error});
                status = 1;
            }
        }
    }

    state.shutdown.store(true, Ordering::SeqCst);
    let _ = server_thread.join();
    let _ = std::fs::remove_dir_all(&home);
    let history_home =
        std::env::temp_dir().join(format!("hades-pty-history-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&history_home);
    write_report(&report, report_path.as_deref(), status)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_head_extracts_request_fields() {
        let head = b"POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: 5\r\n\r\n";
        let parsed = parse_head(head).expect("parse");
        assert_eq!(parsed.method, "POST");
        assert_eq!(parsed.path, "/v1/chat/completions");
        assert_eq!(parsed.content_type, "application/json");
        assert!(!parsed.authorization_present);
        assert_eq!(parsed.content_length, 5);
    }

    #[test]
    fn parse_head_detects_authorization_header() {
        let head =
            b"POST /v1/chat/completions HTTP/1.1\r\nAuthorization: Bearer sk-tes...gth: 0\r\n\r\n";
        let parsed = parse_head(head).expect("parse");
        assert!(parsed.authorization_present);
    }

    #[test]
    fn sse_payload_matches_python_compact_separators() {
        assert_eq!(role_delta(), b"data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n");
        assert_eq!(
            content_delta(RECOVERED_ANSWER),
            b"data: {\"choices\":[{\"delta\":{\"content\":\"Recovered answer.\"}}]}\n\n"
        );
        assert_eq!(
            finish_delta(),
            b"data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\n"
        );
    }

    fn post_request(port: u16, body: &[u8], case: &str, state: &ServerState) -> Vec<u8> {
        reset(state, case);
        let mut stream = TcpStream::connect(("127.0.0.1", port)).expect("connect");
        let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
        let request = format!(
            "POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n",
            body.len()
        );
        stream.write_all(request.as_bytes()).expect("write head");
        stream.write_all(body).expect("write body");
        let mut response = Vec::new();
        stream.read_to_end(&mut response).expect("read response");
        response
    }

    #[test]
    fn first_request_http_error_case_returns_500() {
        let (port, state, handle) = start_server().expect("start");
        let body = br#"{"model":"vertical-model","stream":true,"messages":[{"role":"user","content":"failure probe prompt"}]}"#;
        let response = post_request(port, body, "http-error", &state);
        let text = String::from_utf8_lossy(&response).to_string();
        assert!(text.contains("HTTP/1.0 500"), "{text}");
        assert!(text.contains("synthetic provider failure"), "{text}");
        assert!(!state.recovered.load(Ordering::SeqCst));
        assert_eq!(record_count(&state), 1);
        state.shutdown.store(true, Ordering::SeqCst);
        let _ = handle.join();
    }

    #[test]
    fn first_request_malformed_sse_case_returns_bad_frame() {
        let (port, state, handle) = start_server().expect("start");
        let body = br#"{"model":"vertical-model","stream":true,"messages":[{"role":"user"}]}"#;
        let response = post_request(port, body, "malformed-sse", &state);
        let text = String::from_utf8_lossy(&response).to_string();
        assert!(text.contains("HTTP/1.0 200"), "{text}");
        assert!(text.contains("data: {not-json}"), "{text}");
        assert!(!text.contains("[DONE]"), "{text}");
        assert!(!state.recovered.load(Ordering::SeqCst));
        state.shutdown.store(true, Ordering::SeqCst);
        let _ = handle.join();
    }

    #[test]
    fn first_request_incomplete_stream_case_omits_done() {
        let (port, state, handle) = start_server().expect("start");
        let body = br#"{"model":"vertical-model","stream":true,"messages":[{"role":"user"}]}"#;
        let response = post_request(port, body, "incomplete-stream", &state);
        let text = String::from_utf8_lossy(&response).to_string();
        assert!(text.contains(PARTIAL_ANSWER), "{text}");
        assert!(!text.contains("[DONE]"), "{text}");
        assert!(!state.recovered.load(Ordering::SeqCst));
        state.shutdown.store(true, Ordering::SeqCst);
        let _ = handle.join();
    }

    #[test]
    fn follow_up_request_streams_full_recovery_response() {
        let (port, state, handle) = start_server().expect("start");
        let body = br#"{"model":"vertical-model","stream":true,"messages":[{"role":"user","content":"recovery follow-up"}]}"#;
        // A case not in the failure set: request 1 takes the recovered path.
        let response = post_request(port, body, "recovered", &state);
        let text = String::from_utf8_lossy(&response).to_string();
        assert!(text.contains("HTTP/1.0 200"), "{text}");
        assert!(text.contains(RECOVERED_ANSWER), "{text}");
        assert!(text.contains("[DONE]"), "{text}");
        assert!(state.recovered.load(Ordering::SeqCst));
        let record = &state.records.lock().unwrap()[0];
        assert_eq!(record.method, "POST");
        assert_eq!(record.path, CHAT_PATH);
        assert_eq!(record.content_type, "application/json");
        assert!(!record.authorization_present);
        assert_eq!(record.body["model"], "vertical-model");
        state.shutdown.store(true, Ordering::SeqCst);
        let _ = handle.join();
    }

    #[test]
    fn sensitive_strip_list_covers_provider_and_secret_names() {
        let names = sensitive_strip_list();
        for required in ["HADES_PROVIDER_BASE_URL", "HADES_MODEL", "HADES_PROVIDER_API_KEY"] {
            assert!(names.iter().any(|name| name == required), "missing {required}: {names:?}");
        }
    }
}
