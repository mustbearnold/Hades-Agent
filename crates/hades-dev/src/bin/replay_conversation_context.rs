//! `hades-dev replay-conversation-context` — Rust port of
//! `scripts/replay_conversation_context.py` (HAD-152).
//!
//! Replays the Hades conversation-context contract against a loopback SSE
//! provider: `hades setup --local <loopback-url> vertical-model` persists a
//! sidecar, a fresh TUI process completes two successful turns (each request
//! carries the full accumulated context), a third turn streams a partial
//! answer then ends without `[DONE]` (the failed turn is shown as a
//! diagnostic and excluded from the follow-up), the follow-up turn recovers
//! with the two successful turns preserved, and Ctrl+C exits 0 with the
//! terminal restored. The local provider is a tiny std-only HTTP server
//! (`ContextServer`) that mirrors the Python replay's per-request-number
//! behavior: requests 1/2/4 stream full answers, request 3 streams a
//! partial diagnostic and closes without completion, and every request is
//! recorded for the sanitized-boundary and context-accumulation assertions.

use std::io::{Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::time::Duration;

use hades_dev::replay::{
    ExitStatus, RetainedSlave, TerminalFlags, marker_present, spawn_with_env, terminal_flags,
    wait_for, wait_for_exit, wait_for_rendered,
};
use serde_json::{Value, json};

const CHAT_PATH: &str = "/v1/chat/completions";
const SYSTEM_PROMPT: &str = "You are Hades Agent. Respond concisely to the user.";
const FIRST_PROMPT: &str = "first context prompt";
const FIRST_ANSWER: &str = "First context answer.";
const SECOND_PROMPT: &str = "second context prompt";
const SECOND_ANSWER: &str = "Second context answer.";
const FAILED_PROMPT: &str = "failed context prompt";
const PARTIAL_ANSWER: &str = "Failed partial diagnostic.";
const FOLLOW_UP: &str = "recovered context prompt";
const RECOVERED_ANSWER: &str = "Recovered context answer.";
/// Env-var name parts stripped from the child environment, like
/// `SENSITIVE_ENV_PARTS` (so no credential leaks across the sanitized
/// boundary).
const SENSITIVE_ENV_PARTS: [&str; 6] =
    ["API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY", "ACCESS_KEY"];

/// One recorded provider request, like the Python replay's `records`.
#[derive(Clone)]
struct RequestRecord {
    method: String,
    path: String,
    content_type: String,
    authorization_present: bool,
    body: Value,
}

/// Shared server state: recorded requests plus the completed-turn count.
struct ServerState {
    records: Mutex<Vec<RequestRecord>>,
    completed: AtomicUsize,
    shutdown: AtomicBool,
}

impl ServerState {
    fn record_count(&self) -> usize {
        self.records.lock().unwrap().len()
    }

    fn completion_count(&self) -> usize {
        self.completed.load(Ordering::SeqCst)
    }

    fn snapshot(&self) -> Vec<RequestRecord> {
        self.records.lock().unwrap().clone()
    }
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

/// Read one request: head plus the Content-Length body. The body is parsed
/// as JSON; unparseable bodies record as `{}`, like the Python handler.
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
    let body = serde_json::from_slice(&body_bytes).unwrap_or_else(|_| json!({}));
    Ok(RequestRecord {
        method: head.method,
        path: head.path,
        content_type: head.content_type,
        authorization_present: head.authorization_present,
        body,
    })
}

/// One SSE data chunk, compact-JSON like `sse_payload`.
fn sse_payload(payload: &Value) -> Vec<u8> {
    format!("data: {}\n\n", serde_json::to_string(payload).unwrap_or_default()).into_bytes()
}

fn sse_role_delta() -> Vec<u8> {
    sse_payload(&json!({"choices": [{"delta": {"role": "assistant"}}]}))
}

fn sse_content_delta(content: &str) -> Vec<u8> {
    sse_payload(&json!({"choices": [{"delta": {"content": content}}]}))
}

fn sse_finish() -> Vec<u8> {
    sse_payload(&json!({"choices": [{"delta": {}, "finish_reason": "stop"}]}))
}

fn sse_done() -> Vec<u8> {
    b"data: [DONE]\n\n".to_vec()
}

/// Respond with the SSE stream for one request, mirroring the Python
/// handler: requests 1/2/4 stream a full answer with 20ms pacing, request 3
/// streams only the role delta plus a partial diagnostic and closes without
/// `[DONE]` or `finish_reason` (the failed-turn contract).
fn write_sse(stream: &mut TcpStream, request_number: usize) -> Result<(), String> {
    if request_number == 3 {
        for chunk in [sse_role_delta(), sse_content_delta(PARTIAL_ANSWER)] {
            stream.write_all(&chunk).map_err(|error| format!("delta write failed: {error}"))?;
            stream.flush().map_err(|error| format!("delta flush failed: {error}"))?;
        }
        return Ok(());
    }
    let answer = match request_number {
        1 => FIRST_ANSWER,
        2 => SECOND_ANSWER,
        4 => RECOVERED_ANSWER,
        _ => return Err("unexpected request number".to_string()),
    };
    for chunk in [sse_role_delta(), sse_content_delta(answer), sse_finish(), sse_done()] {
        stream.write_all(&chunk).map_err(|error| format!("chunk write failed: {error}"))?;
        stream.flush().map_err(|error| format!("chunk flush failed: {error}"))?;
        std::thread::sleep(Duration::from_millis(20));
    }
    Ok(())
}

fn handle_connection(mut stream: TcpStream, state: Arc<ServerState>) {
    let _ = stream.set_nodelay(true);
    let record = match read_request(&mut stream) {
        Ok(record) => record,
        Err(_) => return,
    };
    let request_number = {
        let mut records = state.records.lock().unwrap();
        records.push(record.clone());
        records.len()
    };
    if record.path != CHAT_PATH {
        let _ = stream.write_all(
            b"HTTP/1.0 404 Not Found\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n",
        );
        let _ = stream.shutdown(Shutdown::Both);
        return;
    }
    stream
        .write_all(
            b"HTTP/1.0 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\nConnection: close\r\n\r\n",
        )
        .map_err(|error| format!("response head write failed: {error}"))
        .ok();
    if write_sse(&mut stream, request_number).is_err() {
        // A 5th+ request (no mapped answer) gets an error status instead.
        let _ = stream.write_all(
            b"HTTP/1.0 500 Internal Server Error\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n",
        );
        let _ = stream.shutdown(Shutdown::Both);
        return;
    }
    if request_number != 3 {
        state.completed.fetch_add(1, Ordering::SeqCst);
    }
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

/// Start the loopback SSE server on an ephemeral port.
fn start_server() -> std::io::Result<(u16, Arc<ServerState>, std::thread::JoinHandle<()>)> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let port = listener.local_addr()?.port();
    let state = Arc::new(ServerState {
        records: Mutex::new(Vec::new()),
        completed: AtomicUsize::new(0),
        shutdown: AtomicBool::new(false),
    });
    let thread_state = Arc::clone(&state);
    let handle = std::thread::spawn(move || serve(listener, thread_state));
    Ok((port, state, handle))
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
        return Err(format!("setup: setup command failed: {}", text.trim()));
    }
    for marker in ["Hades local setup complete", "Provider: loopback", "Model: vertical-model"] {
        if !text.contains(marker) {
            return Err(format!("setup: missing setup marker: {marker}"));
        }
    }
    let sidecar = home.join("hades-local-provider.conf");
    let contents = std::fs::read_to_string(&sidecar)
        .map_err(|error| format!("setup: local provider sidecar was not created: {error}"))?;
    if !contents.contains("vertical-model") || contents.contains("api_key") {
        return Err("setup: sidecar was not sanitized".to_string());
    }
    if home.join("config.yaml").exists() {
        return Err("setup: setup overwrote or created Hermes config.yaml".to_string());
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

/// Environment keys to strip from the TUI child, like `spawn_isolated`:
/// every variable whose name contains a sensitive part, plus the three
/// provider overrides (which could redirect the child away from the
/// loopback server).
fn sensitive_strip_list() -> Vec<String> {
    let mut keys: Vec<String> = std::env::vars()
        .filter(|(key, _)| {
            let upper = key.to_ascii_uppercase();
            SENSITIVE_ENV_PARTS.iter().any(|part| upper.contains(part))
        })
        .map(|(key, _)| key)
        .collect();
    for key in ["HADES_PROVIDER_BASE_URL", "HADES_MODEL", "HADES_PROVIDER_API_KEY"] {
        keys.push(key.to_string());
    }
    keys
}

/// The `(role, content)` pairs of a recorded request body, like
/// `messages(record)`.
fn request_messages(body: &Value) -> Vec<[String; 2]> {
    body.get("messages")
        .and_then(Value::as_array)
        .map(|messages| {
            messages
                .iter()
                .map(|message| {
                    let role =
                        message.get("role").and_then(Value::as_str).unwrap_or_default().to_string();
                    let content = message
                        .get("content")
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                        .to_string();
                    [role, content]
                })
                .collect()
        })
        .unwrap_or_default()
}

/// The chat step: fresh TUI process against the persisted sidecar, two
/// completed turns, one failed partial turn (no automatic follow-up), a
/// recovered follow-up turn, and a clean Ctrl+C exit, like `run_chat`.
fn run_chat(
    binary: &Path,
    home: &Path,
    state: &ServerState,
    timeout: Duration,
) -> Result<Value, String> {
    let home_str = home.to_str().ok_or_else(|| "non-UTF-8 home path".to_string())?;
    let real_home = std::env::var("HOME").unwrap_or_default();
    let strip_owned = sensitive_strip_list();
    let strip: Vec<&str> = strip_owned.iter().map(String::as_str).collect();
    let mut child = spawn_with_env(
        binary,
        &[],
        &[("HERMES_HOME", home_str), ("HOME", real_home.as_str())],
        &strip,
    )
    .map_err(|error| error.to_string())?;
    let mut output = Vec::new();
    let mut reaped = false;
    let slave_path = child.slave_path.clone();

    let result = (|| -> Result<Value, String> {
        wait_for(
            &child.child,
            &mut output,
            "startup",
            |text| text.contains("Hades Agent") && marker_present(text, "ready"),
            timeout,
        )?;
        // Retain the slave descriptor early so termios state survives exit,
        // like `retain_slave_descriptor` at spawn time.
        let slave = RetainedSlave::retain(&slave_path).map_err(|error| error.to_string())?;

        hades_dev::replay::send(&child.child.master, format!("{FIRST_PROMPT}\r").as_bytes())
            .map_err(|error| error.to_string())?;
        wait_for(
            &child.child,
            &mut output,
            "first-request",
            |_text| state.record_count() >= 1,
            timeout,
        )?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "first-completion",
            |text| {
                state.completion_count() >= 1
                    && marker_present(text, FIRST_ANSWER)
                    && marker_present(text, "ready")
            },
            timeout,
        )?;

        hades_dev::replay::send(&child.child.master, format!("{SECOND_PROMPT}\r").as_bytes())
            .map_err(|error| error.to_string())?;
        wait_for(
            &child.child,
            &mut output,
            "second-request",
            |_text| state.record_count() >= 2,
            timeout,
        )?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "second-completion",
            |text| state.completion_count() >= 2 && marker_present(text, SECOND_ANSWER),
            timeout,
        )?;

        hades_dev::replay::send(&child.child.master, format!("{FAILED_PROMPT}\r").as_bytes())
            .map_err(|error| error.to_string())?;
        wait_for(
            &child.child,
            &mut output,
            "failed-request",
            |_text| state.record_count() >= 3,
            timeout,
        )?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "failed-partial",
            |text| marker_present(text, PARTIAL_ANSWER),
            timeout,
        )?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "failed-visible",
            |text| marker_present(text, "Provider error:"),
            timeout,
        )?;
        // Give any (forbidden) automatic follow-up request time to appear.
        std::thread::sleep(Duration::from_millis(200));
        output.extend_from_slice(&hades_dev::pty::read_available(&child.child.master));
        if state.record_count() != 3 {
            return Err(format!(
                "failed-no-automatic-follow-up: incomplete turn caused an automatic request (count={})",
                state.record_count()
            ));
        }

        hades_dev::replay::send(&child.child.master, FOLLOW_UP.as_bytes())
            .map_err(|error| error.to_string())?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "follow-up-edit",
            |text| marker_present(text, FOLLOW_UP) && !marker_present(text, "Provider error:"),
            timeout,
        )?;
        hades_dev::replay::send(&child.child.master, b"\r").map_err(|error| error.to_string())?;
        wait_for(
            &child.child,
            &mut output,
            "follow-up-request",
            |_text| state.record_count() >= 4,
            timeout,
        )?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "follow-up-completion",
            |text| state.completion_count() >= 3 && marker_present(text, RECOVERED_ANSWER),
            timeout,
        )?;

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 0 }) {
            return Err(format!("cleanup: unexpected exit status: {exit_status:?}"));
        }
        let raw: &[u8] = &output;
        let flags = stable_terminal_flags(&slave)?;
        if !find_sequence(raw, b"\x1b[?1049l") || !flags.canonical || !flags.echo {
            return Err(format!("cleanup: terminal restoration failed: {flags:?}"));
        }

        let records = state.snapshot();
        if records.len() != 4 {
            return Err(format!("request-count: expected four requests, got {}", records.len()));
        }
        let expected: Vec<Vec<[String; 2]>> = vec![
            vec![
                ["system".to_string(), SYSTEM_PROMPT.to_string()],
                ["user".to_string(), FIRST_PROMPT.to_string()],
            ],
            vec![
                ["system".to_string(), SYSTEM_PROMPT.to_string()],
                ["user".to_string(), FIRST_PROMPT.to_string()],
                ["assistant".to_string(), FIRST_ANSWER.to_string()],
                ["user".to_string(), SECOND_PROMPT.to_string()],
            ],
            vec![
                ["system".to_string(), SYSTEM_PROMPT.to_string()],
                ["user".to_string(), FIRST_PROMPT.to_string()],
                ["assistant".to_string(), FIRST_ANSWER.to_string()],
                ["user".to_string(), SECOND_PROMPT.to_string()],
                ["assistant".to_string(), SECOND_ANSWER.to_string()],
                ["user".to_string(), FAILED_PROMPT.to_string()],
            ],
            vec![
                ["system".to_string(), SYSTEM_PROMPT.to_string()],
                ["user".to_string(), FIRST_PROMPT.to_string()],
                ["assistant".to_string(), FIRST_ANSWER.to_string()],
                ["user".to_string(), SECOND_PROMPT.to_string()],
                ["assistant".to_string(), SECOND_ANSWER.to_string()],
                ["user".to_string(), FOLLOW_UP.to_string()],
            ],
        ];
        let actual: Vec<Vec<[String; 2]>> =
            records.iter().map(|record| request_messages(&record.body)).collect();
        if actual != expected {
            return Err(format!("request-context: unexpected conversation context: {actual:?}"));
        }
        for record in &records {
            if record.method != "POST"
                || record.path != CHAT_PATH
                || record.content_type != "application/json"
                || record.authorization_present
                || record.body.get("model").and_then(Value::as_str) != Some("vertical-model")
                || record.body.get("stream").and_then(Value::as_bool) != Some(true)
            {
                return Err(
                    "request-boundary: request crossed the local sanitized boundary".to_string()
                );
            }
        }

        Ok(json!({
            "status": "passed",
            "successful_turns_preserved": true,
            "failed_partial_turn_visible": true,
            "failed_turn_excluded_from_follow_up": true,
            "automatic_requests": 0,
            "requests": records.iter().map(|record| json!({
                "method": record.method,
                "path": record.path,
                "content_type": record.content_type,
                "authorization_present": record.authorization_present,
                "model": record.body.get("model"),
                "messages": request_messages(&record.body),
                "stream": record.body.get("stream"),
            })).collect::<Vec<_>>(),
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
    let _ = std::fs::remove_dir_all(&child.history_home);
    result
}

/// Read PTY flags across the short post-exit ioctl race (retry on errno 25
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
        "command": "replay-conversation-context",
        "binary": binary.to_string_lossy(),
        "dimensions": {"columns": 120, "rows": 40, "emulator": "direct PTY"},
        "steps": [],
        "passed": false,
    });
    let home =
        std::env::temp_dir().join(format!("hades-conversation-context-{}", std::process::id()));
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
        match run_setup(&binary, &home, &endpoint).and_then(|setup| {
            let chat = run_chat(&binary, &home, &state, timeout)?;
            Ok(json!([setup, chat]))
        }) {
            Ok(steps) => {
                report["steps"] = steps;
                if home.join("config.yaml").exists() {
                    report["failure"] = json!({"message":
                        "config-boundary: Hermes config.yaml was created or changed"});
                    status = 1;
                } else {
                    report["boundaries"] = json!({
                        "provider": "loopback",
                        "credentials": "none",
                        "hermes_config_mutation": false,
                        "successful_context": "completed turns only",
                        "failed_context": "diagnostic display only",
                    });
                    report["passed"] = json!(true);
                }
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

    fn post_request(port: u16, body: &[u8], state: &ServerState) -> Vec<u8> {
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
        // The handler records before responding, so the state is settled
        // once the response is complete.
        assert!(state.record_count() >= 1);
        response
    }

    #[test]
    fn server_streams_full_answer_for_first_request() {
        let (port, state, handle) = start_server().expect("start");
        let body = br#"{"model":"vertical-model","stream":true,"messages":[{"role":"system"},{"role":"user","content":"first context prompt"}]}"#;
        let response = post_request(port, body, &state);
        let text = String::from_utf8_lossy(&response).to_string();
        assert!(text.contains("HTTP/1.0 200 OK"), "{text}");
        assert!(text.contains("First context answer."), "{text}");
        assert!(text.contains("finish_reason"), "{text}");
        assert!(text.contains("[DONE]"), "{text}");
        assert_eq!(state.completion_count(), 1);
        let record = &state.snapshot()[0];
        assert_eq!(record.method, "POST");
        assert_eq!(record.path, "/v1/chat/completions");
        assert_eq!(record.content_type, "application/json");
        assert!(!record.authorization_present);
        assert_eq!(record.body["model"], "vertical-model");
        assert_eq!(record.body["stream"], true);
        state.shutdown.store(true, Ordering::SeqCst);
        let _ = handle.join();
    }

    #[test]
    fn server_sends_partial_stream_without_done_for_third_request() {
        let (port, state, handle) = start_server().expect("start");
        let body = br#"{"model":"vertical-model","stream":true,"messages":[{"role":"user"}]}"#;
        for _ in 0..2 {
            post_request(port, body, &state);
        }
        let response = post_request(port, body, &state);
        let text = String::from_utf8_lossy(&response).to_string();
        assert!(text.contains("Failed partial diagnostic."), "{text}");
        assert!(!text.contains("finish_reason"), "{text}");
        assert!(!text.contains("[DONE]"), "{text}");
        // The partial turn never completes.
        assert_eq!(state.completion_count(), 2);
        assert_eq!(state.record_count(), 3);
        state.shutdown.store(true, Ordering::SeqCst);
        let _ = handle.join();
    }

    #[test]
    fn server_answers_recovered_answer_for_fourth_request() {
        let (port, state, handle) = start_server().expect("start");
        let body = br#"{"model":"vertical-model","stream":true,"messages":[{"role":"user"}]}"#;
        for _ in 0..3 {
            post_request(port, body, &state);
        }
        let response = post_request(port, body, &state);
        let text = String::from_utf8_lossy(&response).to_string();
        assert!(text.contains("Recovered context answer."), "{text}");
        assert!(text.contains("[DONE]"), "{text}");
        assert_eq!(state.completion_count(), 3);
        state.shutdown.store(true, Ordering::SeqCst);
        let _ = handle.join();
    }

    #[test]
    fn request_messages_extracts_role_content_pairs() {
        let body = json!({
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": FIRST_PROMPT},
            ]
        });
        let messages = request_messages(&body);
        assert_eq!(
            messages,
            vec![
                ["system".to_string(), SYSTEM_PROMPT.to_string()],
                ["user".to_string(), FIRST_PROMPT.to_string()],
            ]
        );
    }
}
