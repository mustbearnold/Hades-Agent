//! `hades-dev replay-vertical-slice` — Rust port of
//! `scripts/replay_vertical_slice.py` (HAD-131).
//!
//! Replays the configured loopback journey end to end: `hades setup --local
//! <loopback-url> vertical-model` persists a local provider sidecar, a fresh
//! TUI process reaches ready without re-running setup, a prompt produces one
//! streamed provider request (first delta visible before completion), and
//! Ctrl+C exits 0 with the terminal restored. The local provider is a tiny
//! SSE server built on std (`SliceServer`) that mirrors the Python replay's
//! `VerticalSliceServer` event gating: first deltas flush immediately, the
//! final answer is held until the replay releases it, and every request is
//! recorded for the sanitized-boundary assertions.

use std::io::{Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use hades_dev::replay::{
    ExitStatus, RetainedSlave, TerminalFlags, clean_output, marker_present, spawn_with_env,
    terminal_flags, wait_for, wait_for_exit, wait_for_rendered,
};
use serde_json::{Value, json};

const STRIP_ENV: [&str; 3] = ["HADES_PROVIDER_BASE_URL", "HADES_MODEL", "HADES_PROVIDER_API_KEY"];

/// One recorded provider request, like the Python replay's `records`.
struct RequestRecord {
    path: String,
    content_type: String,
    authorization_present: bool,
    body: Value,
}

/// Shared server state: request/response events plus recorded requests.
struct ServerState {
    request_seen: AtomicBool,
    first_delta_sent: AtomicBool,
    release_response: AtomicBool,
    response_complete: AtomicBool,
    shutdown: AtomicBool,
    records: Mutex<Vec<RequestRecord>>,
}

/// Parsed request head: header block end plus the fields the replay asserts.
struct ParsedHead {
    header_end: usize,
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
            let _method = parts.next();
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
    Ok(ParsedHead { header_end, path, content_type, authorization_present, content_length })
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
        path: head.path,
        content_type: head.content_type,
        authorization_present: head.authorization_present,
        body,
    })
}

/// Respond with the SSE stream, mirroring the Python handler: the first two
/// deltas flush immediately, the final answer waits for `release_response`
/// (up to 3s), then the completion chunks stream with 30ms pacing.
fn write_sse(stream: &mut TcpStream, state: &ServerState) -> Result<(), String> {
    stream
        .write_all(
            b"HTTP/1.0 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n",
        )
        .map_err(|error| format!("response head write failed: {error}"))?;
    let first_chunks: [&[u8]; 2] = [
        b"data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n",
        b"data: {\"choices\":[{\"delta\":{\"content\":\"First streamed delta. \"}}]}\n\n",
    ];
    for chunk in first_chunks {
        stream.write_all(chunk).map_err(|error| format!("delta write failed: {error}"))?;
        stream.flush().map_err(|error| format!("delta flush failed: {error}"))?;
    }
    state.first_delta_sent.store(true, Ordering::SeqCst);
    let deadline = Instant::now() + Duration::from_secs(3);
    while !state.release_response.load(Ordering::SeqCst) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(10));
    }
    let final_chunks: [&[u8]; 3] = [
        b"data: {\"choices\":[{\"delta\":{\"content\":\"Final streamed answer.\"}}]}\n\n",
        b"data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\n",
        b"data: [DONE]\n\n",
    ];
    for chunk in final_chunks {
        stream.write_all(chunk).map_err(|error| format!("final chunk write failed: {error}"))?;
        stream.flush().map_err(|error| format!("final chunk flush failed: {error}"))?;
        std::thread::sleep(Duration::from_millis(30));
    }
    state.response_complete.store(true, Ordering::SeqCst);
    Ok(())
}

fn handle_connection(mut stream: TcpStream, state: Arc<ServerState>) {
    let _ = stream.set_nodelay(true);
    let record = match read_request(&mut stream) {
        Ok(record) => record,
        Err(_) => return,
    };
    state.records.lock().unwrap().push(record);
    state.request_seen.store(true, Ordering::SeqCst);
    let _ = write_sse(&mut stream, &state);
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
        request_seen: AtomicBool::new(false),
        first_delta_sent: AtomicBool::new(false),
        release_response: AtomicBool::new(false),
        response_complete: AtomicBool::new(false),
        shutdown: AtomicBool::new(false),
        records: Mutex::new(Vec::new()),
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

/// The chat step: fresh TUI process against the persisted sidecar, one
/// streamed request, clean Ctrl+C exit, like `run_chat`.
fn run_chat(
    binary: &Path,
    home: &Path,
    state: &ServerState,
    timeout: Duration,
) -> Result<Value, String> {
    let home_str = home.to_str().ok_or_else(|| "non-UTF-8 home path".to_string())?;
    let real_home = std::env::var("HOME").unwrap_or_default();
    let mut child = spawn_with_env(
        binary,
        &[],
        &[("HERMES_HOME", home_str), ("HOME", real_home.as_str())],
        &STRIP_ENV,
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
        let startup = clean_output(&output);
        if marker_present(&startup, "starting agent") {
            return Err("startup: persisted setup did not reach ready state".to_string());
        }
        let slave = RetainedSlave::retain(&slave_path).map_err(|error| error.to_string())?;

        hades_dev::replay::send(&child.child.master, b"vertical prompt\r")
            .map_err(|error| error.to_string())?;
        wait_for(
            &child.child,
            &mut output,
            "request",
            |_text| state.request_seen.load(Ordering::SeqCst),
            timeout,
        )?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "first-delta",
            |text| marker_present(text, "First streamed delta."),
            timeout,
        )?;
        if state.response_complete.load(Ordering::SeqCst) {
            return Err("first-delta: completion arrived before first-delta readback".to_string());
        }
        state.release_response.store(true, Ordering::SeqCst);
        wait_for_rendered(
            &child.child,
            &mut output,
            "completion",
            |text| {
                state.response_complete.load(Ordering::SeqCst)
                    && marker_present(text, "Final streamed answer.")
                    && marker_present(text, "ready")
            },
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

        let records = state.records.lock().unwrap();
        if records.len() != 1 {
            return Err(format!("request: expected one request, got {}", records.len()));
        }
        let record = &records[0];
        if record.path != "/v1/chat/completions" {
            return Err(format!("request: unexpected request path: {}", record.path));
        }
        if record.content_type != "application/json" || record.authorization_present {
            return Err("request: request crossed the sanitized local boundary".to_string());
        }
        let body = &record.body;
        if body["model"] != "vertical-model" || body["stream"] != true {
            return Err("request: persisted provider/model was not used".to_string());
        }
        let messages = body["messages"]
            .as_array()
            .ok_or_else(|| "request: messages array missing".to_string())?;
        let roles: Vec<String> = messages
            .iter()
            .filter_map(|message| message["role"].as_str().map(String::from))
            .collect();
        if roles != ["system", "user"] {
            return Err(format!("request: message role boundary was not preserved: {roles:?}"));
        }
        if messages.last().and_then(|message| message["content"].as_str())
            != Some("vertical prompt")
        {
            return Err("request: prompt content was not delivered".to_string());
        }
        let mut body_keys: Vec<String> =
            body.as_object().map(|object| object.keys().cloned().collect()).unwrap_or_default();
        body_keys.sort();

        Ok(json!({
            "status": "passed",
            "fresh_process": true,
            "startup_ready": true,
            "request": {
                "method": "POST",
                "path": record.path,
                "content_type": record.content_type,
                "authorization_present": false,
                "body_keys": body_keys,
                "model": body["model"],
                "message_roles": roles,
                "prompt_marker": "vertical prompt",
                "stream": body["stream"],
            },
            "stream": {
                "first_delta_visible_before_completion": true,
                "first_delta_marker": "First streamed delta.",
                "final_delta_marker": "Final streamed answer.",
                "ready_after_completion": true,
            },
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
        "command": "replay-vertical-slice",
        "binary": binary.to_string_lossy(),
        "dimensions": {"columns": 120, "rows": 40, "emulator": "direct PTY"},
        "steps": [],
        "passed": false,
    });
    let home = std::env::temp_dir().join(format!("hades-vertical-slice-{}", std::process::id()));
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
                report["passed"] = json!(true);
            }
            Err(error) => {
                report["failure"] = json!({"message": error});
                status = 1;
            }
        }
    }

    state.release_response.store(true, Ordering::SeqCst);
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
        assert_eq!(parsed.path, "/v1/chat/completions");
        assert_eq!(parsed.content_type, "application/json");
        assert!(!parsed.authorization_present);
        assert_eq!(parsed.content_length, 5);
    }

    #[test]
    fn parse_head_detects_authorization_header() {
        let head = b"POST /v1/chat/completions HTTP/1.1\r\nAuthorization: Bearer sk-test\r\nContent-Length: 0\r\n\r\n";
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
        // The handler pushes the record before responding, so the state is
        // settled once the response is complete.
        assert!(state.records.lock().unwrap().len() == 1);
        response
    }

    #[test]
    fn server_records_request_and_streams_full_sse() {
        let (port, state, handle) = start_server().expect("start");
        // Release immediately so the stream is not held.
        state.release_response.store(true, Ordering::SeqCst);
        let body = br#"{"model":"vertical-model","stream":true,"messages":[{"role":"system"},{"role":"user","content":"vertical prompt"}]}"#;
        let response = post_request(port, body, &state);
        let text = String::from_utf8_lossy(&response).to_string();
        assert!(text.contains("HTTP/1.0 200 OK"), "{text}");
        assert!(text.contains("First streamed delta."), "{text}");
        assert!(text.contains("Final streamed answer."), "{text}");
        assert!(text.contains("[DONE]"), "{text}");
        assert!(state.request_seen.load(Ordering::SeqCst));
        assert!(state.first_delta_sent.load(Ordering::SeqCst));
        assert!(state.response_complete.load(Ordering::SeqCst));
        let record = &state.records.lock().unwrap()[0];
        assert_eq!(record.path, "/v1/chat/completions");
        assert_eq!(record.content_type, "application/json");
        assert!(!record.authorization_present);
        assert_eq!(record.body["model"], "vertical-model");
        state.shutdown.store(true, Ordering::SeqCst);
        let _ = handle.join();
    }

    #[test]
    fn server_holds_final_answer_until_release() {
        let (port, state, handle) = start_server().expect("start");
        let body = br#"{"model":"vertical-model","stream":true,"messages":[{"role":"user"}]}"#;
        let stream_state = Arc::clone(&state);
        let client = std::thread::spawn(move || post_request(port, body, &stream_state));
        // Wait for the request and the first delta to land.
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline
            && !(state.request_seen.load(Ordering::SeqCst)
                && state.first_delta_sent.load(Ordering::SeqCst))
        {
            std::thread::sleep(Duration::from_millis(10));
        }
        assert!(state.request_seen.load(Ordering::SeqCst));
        assert!(state.first_delta_sent.load(Ordering::SeqCst));
        // The final answer must still be held.
        assert!(!state.response_complete.load(Ordering::SeqCst));
        state.release_response.store(true, Ordering::SeqCst);
        let response = client.join().expect("client");
        let text = String::from_utf8_lossy(&response).to_string();
        assert!(text.contains("Final streamed answer."), "{text}");
        assert!(state.response_complete.load(Ordering::SeqCst));
        state.shutdown.store(true, Ordering::SeqCst);
        let _ = handle.join();
    }
}
