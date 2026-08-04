//! `hades-dev replay-local-provider` — Rust port of
//! `scripts/replay_local_provider.py` (HAD-155).
//!
//! Replays the opt-in Hades loopback provider worker through a real PTY in
//! three cases:
//! - `local-provider-stream`: a prompt against a deterministic
//!   OpenAI-compatible SSE fixture server; asserts the sanitized local
//!   request boundary (path, content type, no Authorization, body key
//!   set, model/stream markers, message roles), the rendered synthetic
//!   answer, return to ready, and a clean Ctrl+C exit with the terminal
//!   restored.
//! - `missing-provider-config`: an unconfigured startup that reaches the
//!   "starting agent" surface, echoes the typed draft (rendered), never
//!   starts a provider request, and exits cleanly on two Ctrl+C presses.
//! - `interrupt-active-provider`: a hold provider (never responds) whose
//!   in-flight request is interrupted by Ctrl+C, then a second Ctrl+C
//!   exits cleanly.
//!
//! All post-startup typed/streamed text markers are matched on the
//! RENDERED screen (`wait_for_rendered`) because the animated startup logo
//! emits interleaved sparse-redraw cell writes that fragment raw bytes;
//! startup markers stay on raw `wait_for` (the first full-frame write is
//! contiguous), mirroring the Python replay.

use std::io::{Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use hades_dev::hold_provider::HoldProvider;
use hades_dev::replay::{
    ExitStatus, ReplayChild, RetainedSlave, TerminalFlags, clean_output, marker_present,
    spawn_with_env, terminal_flags, wait_for, wait_for_exit, wait_for_rendered,
};
use serde_json::{Value, json};

const STARTUP_MARKERS_STREAM: [&str; 2] = ["Hades Agent", "ready"];
const STARTUP_MARKERS_UNCONFIGURED: [&str; 2] = ["Hades Agent", "starting agent"];

/// One recorded provider request, like the Python replay's `records`.
struct RequestRecord {
    path: String,
    content_type: String,
    authorization_present: bool,
    body: Value,
}

/// Shared stream-server state: the request event plus recorded requests.
struct StreamState {
    request_seen: AtomicBool,
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

/// Respond with the fixed SSE stream, mirroring the Python handler's
/// non-blocking chunk sequence (4 events, 20ms pacing).
fn write_sse(stream: &mut TcpStream) -> Result<(), String> {
    stream
        .write_all(
            b"HTTP/1.0 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n",
        )
        .map_err(|error| format!("response head write failed: {error}"))?;
    let chunks: [&[u8]; 4] = [
        b"data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n",
        b"data: {\"choices\":[{\"delta\":{\"content\":\"Synthetic loopback response.\"}}]}\n\n",
        b"data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\n",
        b"data: [DONE]\n\n",
    ];
    for chunk in chunks {
        stream.write_all(chunk).map_err(|error| format!("chunk write failed: {error}"))?;
        stream.flush().map_err(|error| format!("chunk flush failed: {error}"))?;
        std::thread::sleep(Duration::from_millis(20));
    }
    Ok(())
}

fn handle_connection(mut stream: TcpStream, state: Arc<StreamState>) {
    let _ = stream.set_nodelay(true);
    let record = match read_request(&mut stream) {
        Ok(record) => record,
        Err(_) => return,
    };
    state.records.lock().unwrap().push(record);
    state.request_seen.store(true, Ordering::SeqCst);
    let _ = write_sse(&mut stream);
    let _ = stream.shutdown(Shutdown::Both);
}

/// Accept loop on a non-blocking listener; exits on the shutdown flag.
fn serve(listener: TcpListener, state: Arc<StreamState>) {
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
fn start_server() -> std::io::Result<(u16, Arc<StreamState>, std::thread::JoinHandle<()>)> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let port = listener.local_addr()?.port();
    let state = Arc::new(StreamState {
        request_seen: AtomicBool::new(false),
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

/// Spawn Hades with the Python replay's exact environment: isolated home,
/// loopback provider env vars when a base URL is given, `HADES_MODEL`
/// always set to palette-model, and the API key always removed (the
/// local provider is a sanitized boundary — no credentials cross it).
fn spawn_hades(binary: &Path, home: &Path, base_url: Option<&str>) -> Result<ReplayChild, String> {
    let home_str = home.to_str().ok_or_else(|| "non-UTF-8 home path".to_string())?;
    let mut extra: Vec<(&str, &str)> =
        vec![("HOME", home_str), ("HERMES_HOME", home_str), ("HADES_MODEL", "palette-model")];
    if let Some(url) = base_url {
        extra.push(("HADES_PROVIDER_BASE_URL", url));
    }
    // NOTE: spawn_with_env applies `strip` AFTER `extra`, so the base URL
    // must not be stripped when it is set.
    let strip: &[&str] = if base_url.is_none() {
        &["HADES_PROVIDER_BASE_URL", "HADES_PROVIDER_API_KEY"]
    } else {
        &["HADES_PROVIDER_API_KEY"]
    };
    spawn_with_env(binary, &[], &extra, strip).map_err(|error| error.to_string())
}

/// A bounded replay assertion failure, mirroring `ReplayFailure`.
struct ReplayError {
    case: String,
    step: String,
    message: String,
}

impl ReplayError {
    fn as_json(&self) -> Value {
        json!({ "case": self.case, "step": self.step, "message": self.message })
    }
}

fn fail(case: &str, step: &str, message: impl Into<String>) -> ReplayError {
    ReplayError { case: case.to_owned(), step: step.to_owned(), message: message.into() }
}

/// Attach case/step context to a `wait_for`-style `Result<(), String>`.
fn wrapped(case: &str, step: &str, result: Result<(), String>) -> Result<(), ReplayError> {
    result.map_err(|message| fail(case, step, message))
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

fn assert_clean_exit(status: rustix::process::WaitStatus, case: &str) -> Result<(), ReplayError> {
    if ExitStatus::describe(status) != (ExitStatus::Exit { code: 0 }) {
        return Err(fail(case, "cleanup", "unexpected exit status"));
    }
    Ok(())
}

/// The streamed-response case: one sanitized provider request, the
/// rendered synthetic answer, return to ready, and a clean Ctrl+C exit
/// with the terminal restored.
fn run_stream_case(binary: &Path, timeout: Duration) -> Result<Value, ReplayError> {
    let case = "local-provider-stream";
    let (port, state, server_thread) = start_server()
        .map_err(|error| fail(case, "server", format!("loopback server failed: {error}")))?;
    let endpoint = format!("http://127.0.0.1:{port}/v1");
    let home =
        std::env::temp_dir().join(format!("hades-local-provider-stream-{}", std::process::id()));
    let _ = std::fs::create_dir_all(&home);
    let mut child =
        spawn_hades(binary, &home, Some(&endpoint)).map_err(|error| fail(case, "spawn", error))?;
    let mut output = Vec::new();
    let mut reaped = false;
    let slave = RetainedSlave::retain(&child.slave_path)
        .map_err(|error| fail(case, "cleanup", format!("retain slave: {error}")))?;

    let result = (|| -> Result<Value, ReplayError> {
        wrapped(
            case,
            "startup",
            wait_for(
                &child.child,
                &mut output,
                "startup",
                |text| STARTUP_MARKERS_STREAM.iter().all(|marker| text.contains(marker)),
                timeout,
            ),
        )?;
        hades_dev::replay::send(&child.child.master, b"sanitized prompt\r")
            .map_err(|error| fail(case, "input", error.to_string()))?;
        wrapped(
            case,
            "request",
            wait_for(
                &child.child,
                &mut output,
                "request",
                |_text| state.request_seen.load(Ordering::SeqCst),
                timeout,
            ),
        )?;
        wrapped(
            case,
            "response",
            wait_for_rendered(
                &child.child,
                &mut output,
                "response",
                |text| {
                    marker_present(text, "Synthetic loopback response.")
                        && marker_present(text, "ready")
                },
                timeout,
            ),
        )?;
        hades_dev::replay::send(&child.child.master, b"\x03")
            .map_err(|error| fail(case, "input", error.to_string()))?;
        let status = wait_for_exit(&child.child, &mut output, timeout)
            .map_err(|error| fail(case, "exit", error))?;
        reaped = true;
        assert_clean_exit(status, case)?;
        if !find_sequence(&output, b"\x1b[?1049l") {
            return Err(fail(case, "cleanup", "alternate screen was not restored"));
        }
        let flags = stable_terminal_flags(&slave).map_err(|error| fail(case, "cleanup", error))?;
        if !flags.canonical || !flags.echo {
            return Err(fail(
                case,
                "cleanup",
                format!("terminal flags were not restored: {flags:?}"),
            ));
        }
        let records = state.records.lock().unwrap();
        if records.len() != 1 {
            return Err(fail(
                case,
                "request",
                format!("expected one request, got {}", records.len()),
            ));
        }
        let record = &records[0];
        if record.path != "/v1/chat/completions" {
            return Err(fail(case, "request", format!("unexpected request path: {}", record.path)));
        }
        if record.content_type != "application/json" || record.authorization_present {
            return Err(fail(
                case,
                "request",
                "request headers crossed the local sanitized boundary",
            ));
        }
        let body = &record.body;
        let mut body_keys: Vec<String> =
            body.as_object().map(|object| object.keys().cloned().collect()).unwrap_or_default();
        body_keys.sort();
        let expected_keys =
            ["max_tokens", "messages", "model", "stream", "stream_options", "tools"];
        if body_keys != expected_keys {
            return Err(fail(case, "request", format!("unexpected body keys: {body_keys:?}")));
        }
        if body["model"] != "palette-model" || body["stream"] != true {
            return Err(fail(case, "request", "model/stream markers were not preserved"));
        }
        let messages = body["messages"]
            .as_array()
            .ok_or_else(|| fail(case, "request", "messages array missing"))?;
        let roles: Vec<String> = messages
            .iter()
            .filter_map(|message| message["role"].as_str().map(String::from))
            .collect();
        if roles != ["system", "user"] {
            return Err(fail(
                case,
                "request",
                format!("message role boundary was not preserved: {roles:?}"),
            ));
        }
        let tools_present = body["tools"].as_array().is_some_and(|tools| !tools.is_empty());
        Ok(json!({
            "id": case,
            "status": "passed",
            "request": {
                "method": "POST",
                "path": record.path,
                "content_type": record.content_type,
                "authorization_present": false,
                "body_keys": body_keys,
                "model": body["model"],
                "stream": body["stream"],
                "message_roles": roles,
                "tools_present": tools_present,
            },
            "response": {
                "content_type": "text/event-stream",
                "chunk_count": 3,
                "done_marker_sent": true,
                "assistant_text_marker": "Synthetic loopback response.",
            },
            "visible_state": {
                "returned_to_ready": true,
                "assistant_text_rendered": true,
                "cleanup": "Ctrl+C exited cleanly",
            },
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child.child);
    }
    state.shutdown.store(true, Ordering::SeqCst);
    let _ = server_thread.join();
    let _ = std::fs::remove_dir_all(&home);
    result
}

/// The unconfigured case: no provider env vars, "starting agent" startup,
/// the typed draft echoed on the rendered screen, no provider request, and
/// two Ctrl+C presses exit cleanly (the first clears the draft).
fn run_missing_config_case(binary: &Path, timeout: Duration) -> Result<Value, ReplayError> {
    let case = "missing-provider-config";
    let home =
        std::env::temp_dir().join(format!("hades-local-provider-missing-{}", std::process::id()));
    let _ = std::fs::create_dir_all(&home);
    let mut child = spawn_hades(binary, &home, None).map_err(|error| fail(case, "spawn", error))?;
    let mut output = Vec::new();
    let mut reaped = false;

    let result = (|| -> Result<Value, ReplayError> {
        wrapped(
            case,
            "startup",
            wait_for(
                &child.child,
                &mut output,
                "startup",
                |text| {
                    STARTUP_MARKERS_UNCONFIGURED
                        .iter()
                        .all(|marker| text.contains(marker) || marker_present(text, marker))
                },
                timeout,
            ),
        )?;
        hades_dev::replay::send(&child.child.master, b"missing endpoint\r")
            .map_err(|error| fail(case, "input", error.to_string()))?;
        wrapped(
            case,
            "draft",
            wait_for_rendered(
                &child.child,
                &mut output,
                "draft",
                |text| marker_present(text, "missing endpoint"),
                timeout,
            ),
        )?;
        // Like the Python replay, the prompt-visibility probe reads the
        // CLEANED RAW stream (not the rendered screen): the animated logo
        // fragments the draft, so this is false on the unconfigured
        // surface — and the parity report pins that value.
        let visible_text = clean_output(&output);
        if marker_present(&visible_text, "Provider error") {
            return Err(fail(case, "input", "unconfigured startup rendered a provider error"));
        }
        let prompt_visible = marker_present(&visible_text, "missing endpoint");
        hades_dev::replay::send(&child.child.master, b"\x03")
            .map_err(|error| fail(case, "input", error.to_string()))?;
        std::thread::sleep(Duration::from_millis(50));
        hades_dev::replay::send(&child.child.master, b"\x03")
            .map_err(|error| fail(case, "input", error.to_string()))?;
        let status = wait_for_exit(&child.child, &mut output, timeout)
            .map_err(|error| fail(case, "exit", error))?;
        reaped = true;
        assert_clean_exit(status, case)?;
        Ok(json!({
            "id": case,
            "status": "passed",
            "visible_state": {
                "unconfigured_startup": true,
                "prompt_visible": prompt_visible,
                "prompt_ignored": false,
                "provider_request_started": false,
                "cleanup": "two Ctrl+C presses exited cleanly",
            },
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child.child);
    }
    let _ = std::fs::remove_dir_all(&home);
    result
}

/// The interrupt case: a hold provider that never responds, Ctrl+C
/// interrupting the in-flight request ("interrupted" on the rendered
/// screen), then a second Ctrl+C exits cleanly.
fn run_interrupt_case(binary: &Path, timeout: Duration) -> Result<Value, ReplayError> {
    let case = "interrupt-active-provider";
    let mut provider = HoldProvider::start()
        .map_err(|error| fail(case, "server", format!("loopback server failed: {error}")))?;
    let environment = provider.environment();
    let endpoint = environment[0].1.clone();
    let home =
        std::env::temp_dir().join(format!("hades-local-provider-interrupt-{}", std::process::id()));
    let _ = std::fs::create_dir_all(&home);
    let mut child =
        spawn_hades(binary, &home, Some(&endpoint)).map_err(|error| fail(case, "spawn", error))?;
    let mut output = Vec::new();
    let mut reaped = false;

    let result = (|| -> Result<Value, ReplayError> {
        wrapped(
            case,
            "startup",
            wait_for(
                &child.child,
                &mut output,
                "startup",
                |text| STARTUP_MARKERS_STREAM.iter().all(|marker| text.contains(marker)),
                timeout,
            ),
        )?;
        hades_dev::replay::send(&child.child.master, b"interrupt me\r")
            .map_err(|error| fail(case, "input", error.to_string()))?;
        wrapped(
            case,
            "request",
            wait_for(
                &child.child,
                &mut output,
                "request",
                |_text| provider.request_seen(),
                timeout,
            ),
        )?;
        hades_dev::replay::send(&child.child.master, b"\x03")
            .map_err(|error| fail(case, "input", error.to_string()))?;
        // Deviation from the Python replay (raw wait_for): the interrupted
        // marker is post-startup text, so it is matched on the RENDERED
        // screen — strictly more robust, same report value.
        wrapped(
            case,
            "interrupt",
            wait_for_rendered(
                &child.child,
                &mut output,
                "interrupt",
                |text| marker_present(text, "interrupted"),
                timeout,
            ),
        )?;
        hades_dev::replay::send(&child.child.master, b"\x03")
            .map_err(|error| fail(case, "input", error.to_string()))?;
        let status = wait_for_exit(&child.child, &mut output, timeout)
            .map_err(|error| fail(case, "exit", error))?;
        reaped = true;
        assert_clean_exit(status, case)?;
        Ok(json!({
            "id": case,
            "status": "passed",
            "visible_state": {
                "request_started": true,
                "interrupt_marker": true,
                "late_response_released": false,
                "cleanup": "Ctrl+C interrupted and then exited cleanly",
            },
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child.child);
    }
    provider.finish();
    let _ = std::fs::remove_dir_all(&home);
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

/// A case runner: one replay case against the TUI binary.
type CaseRunner = fn(&Path, Duration) -> Result<Value, ReplayError>;

fn main() -> ExitCode {
    let mut args = std::env::args().skip(1);
    let mut binary = repo_root().join("target/debug/hades");
    let mut contract_path =
        repo_root().join("tests/fixtures/parity/OBS-0051-hades-local-provider-stream.json");
    let mut report_path: Option<PathBuf> = None;
    let mut timeout = Duration::from_secs_f64(8.0);

    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--binary" => {
                if let Some(value) = args.next() {
                    binary = PathBuf::from(value);
                }
            }
            "--contract" => {
                if let Some(value) = args.next() {
                    contract_path = PathBuf::from(value);
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
    let contract_path = contract_path.canonicalize().unwrap_or_else(|_| contract_path.clone());
    let mut report = json!({
        "schema_version": 1,
        "command": "replay-local-provider",
        "binary": binary.display().to_string(),
        "contract": contract_path.display().to_string(),
        "dimensions": {"columns": 120, "rows": 40, "emulator": "direct PTY"},
        "cases": [],
        "passed": false,
    });
    if !binary.is_file() {
        report["failure"] = json!({
            "case": "report",
            "step": "binary",
            "message": format!("binary not found: {}", binary.display()),
        });
        return write_report(&report, report_path.as_deref(), 1);
    }

    let runners: [CaseRunner; 3] = [run_stream_case, run_missing_config_case, run_interrupt_case];
    let mut cases: Vec<Value> = Vec::new();
    let mut failure: Option<ReplayError> = None;
    for runner in runners {
        match runner(&binary, timeout) {
            Ok(case) => cases.push(case),
            Err(error) => {
                failure = Some(error);
                break;
            }
        }
    }
    match failure {
        None => {
            report["cases"] = json!(cases);
            report["passed"] = json!(true);
            write_report(&report, report_path.as_deref(), 0)
        }
        Some(error) => {
            report["failure"] = error.as_json();
            write_report(&report, report_path.as_deref(), 1)
        }
    }
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
        let head =
            b"POST /v1/chat/completions HTTP/1.1\r\nAuthorization: Bearer sk-tes...gth: 0\r\n\r\n";
        let parsed = parse_head(head).expect("parse");
        assert!(parsed.authorization_present);
    }

    fn post_request(port: u16, body: &[u8], state: &StreamState) -> Vec<u8> {
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
        let body = br#"{"model":"palette-model","stream":true,"messages":[{"role":"system"},{"role":"user","content":"sanitized prompt"}]}"#;
        let response = post_request(port, body, &state);
        let text = String::from_utf8_lossy(&response).to_string();
        assert!(text.contains("HTTP/1.0 200 OK"), "{text}");
        assert!(text.contains("Synthetic loopback response."), "{text}");
        assert!(text.contains("finish_reason"), "{text}");
        assert!(text.contains("[DONE]"), "{text}");
        assert!(state.request_seen.load(Ordering::SeqCst));
        let record = &state.records.lock().unwrap()[0];
        assert_eq!(record.path, "/v1/chat/completions");
        assert_eq!(record.content_type, "application/json");
        assert!(!record.authorization_present);
        assert_eq!(record.body["model"], "palette-model");
        assert_eq!(record.body["stream"], true);
        state.shutdown.store(true, Ordering::SeqCst);
        let _ = handle.join();
    }
}
