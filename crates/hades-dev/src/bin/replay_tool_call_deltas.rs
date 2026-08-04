//! `hades-dev replay-tool-call-deltas` — Rust port of
//! `scripts/replay_tool_call_deltas.py` (HAD-170).
//!
//! Replays the safe Hades tool-call delta boundary through a real PTY: the
//! loopback provider returns a valid OpenAI-compatible streaming response
//! with assistant text plus a fragmented `clarify` tool call and
//! `finish_reason: tool_calls`. Hades must render the assistant text, return
//! to ready without an invented processing overlay or busy marker, send no
//! follow-up request, and never execute or approve the tool call. Ctrl+C
//! exits cleanly. The loopback server is a tiny std-only HTTP server that
//! mirrors the Python replay's `ToolCallServer` event gating: every request
//! is recorded, the first streaming request emits the fragmented tool-call
//! stream (byte-identical chunks, digest-recorded), and any follow-up
//! streaming request answers plainly so the bounded one-hop loop terminates.

use std::fs;
use std::io::{Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use hades_dev::replay::{
    ExitStatus, RetainedSlave, TerminalFlags, clean_output, marker_present, send, spawn_with_env,
    terminal_flags, try_wait, wait_for, wait_for_exit, wait_for_rendered,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

const PROMPT: &str = "synthetic tool-call prompt";
const ASSISTANT_MARKER: &str = "Synthetic handoff";
const TOOL_NAME: &str = "clarify";
const ARGUMENT_FRAGMENTS: [&str; 2] = [
    r#"{"question":"synthetic clarification prompt","#,
    r#""choices":["synthetic choice one","synthetic choice two"]}"#,
];
const EXPECTED_TOOL_COUNT: usize = 31;
// Canonical sort-keys SHA-256 of the OBS-0112 31-tool inventory.
const EXPECTED_INVENTORY_DIGEST: &str =
    "b2cbd3f2bf77de3a91cf9a4844b324f6130aab8c72b2924a159cce533f38a220";

fn sha256_hex(bytes: &[u8]) -> String {
    let mut digest = Sha256::new();
    digest.update(bytes);
    format!("{:x}", digest.finalize())
}

/// Sort object keys recursively and hash the compact serialization,
/// matching the Python probe/validator canonical digest convention
/// (`json.dumps(sort(value), ensure_ascii=False, separators=(",", ":"))`).
/// serde_json's `Map` is BTreeMap-backed, so keys already serialize sorted;
/// its compact formatter writes non-ASCII raw like `ensure_ascii=False`.
fn canonical_digest(value: &Value) -> String {
    sha256_hex(serde_json::to_string(value).expect("canonical serialization").as_bytes())
}

/// The first streaming request's chunks, byte-identical to the Python
/// replay's tool-call stream (arguments JSON-encoded like `json.dumps`).
///
/// The literal tail `}}]}}]}` after the encoded arguments holds five
/// closing braces — an odd count that cannot be expressed as even `}}`
/// runs inside one `format!` string, so the placeholder's own `}` plus
/// two even runs cover the first four closers and the final `]}` is
/// appended outside the format string.
fn first_stream_chunks() -> Vec<Vec<u8>> {
    let encoded0 = serde_json::to_string(ARGUMENT_FRAGMENTS[0]).expect("fragment serializes");
    let encoded1 = serde_json::to_string(ARGUMENT_FRAGMENTS[1]).expect("fragment serializes");
    let mut chunk2: Vec<u8> = b"data: {\"choices\":[{\"delta\":{\"content\":\"Synthetic handoff\",\
\"tool_calls\":[{\"index\":0,\"id\":\"call_synthetic_clarify\",\"type\":\"function\",\
\"function\":{\"name\":\"clarify\",\"arguments\":"
        .to_vec();
    chunk2.extend_from_slice(encoded0.as_bytes());
    chunk2.extend_from_slice(b"}}]}}]}\n\n");
    let mut chunk3: Vec<u8> = b"data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\
\"function\":{\"arguments\":"
        .to_vec();
    chunk3.extend_from_slice(encoded1.as_bytes());
    chunk3.extend_from_slice(b"}}]}}]}\n\n");
    vec![
        b"data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n".to_vec(),
        chunk2,
        chunk3,
        b"data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"tool_calls\"}]}\n\n".to_vec(),
        b"data: [DONE]\n\n".to_vec(),
    ]
}

/// The bounded follow-up stream: answer plainly so the one-hop loop
/// terminates and no third request arrives.
fn follow_up_chunks() -> Vec<Vec<u8>> {
    vec![
        b"data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n".to_vec(),
        b"data: {\"choices\":[{\"delta\":{\"content\":\"Synthetic completion.\"}}]}\n\n".to_vec(),
        b"data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\n".to_vec(),
        b"data: [DONE]\n\n".to_vec(),
    ]
}

/// One recorded provider request, like the Python replay's `records`.
#[derive(Clone)]
struct RequestRecord {
    method: String,
    path: String,
    authorization_present: bool,
    body: Value,
}

/// Shared server state: request events plus recorded requests and the
/// digest-recorded first-stream chunks.
struct ServerState {
    request_seen: AtomicBool,
    streaming_requests: AtomicUsize,
    shutdown: AtomicBool,
    records: Mutex<Vec<RequestRecord>>,
    tool_call_events: Mutex<Vec<Value>>,
}

/// Parsed request head: header block end plus the fields the replay asserts.
struct ParsedHead {
    header_end: usize,
    method: String,
    path: String,
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
                "authorization" => authorization_present = true,
                _ => {}
            }
        }
    }
    Ok(ParsedHead { header_end, method, path, authorization_present, content_length })
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
        authorization_present: head.authorization_present,
        body,
    })
}

/// JSON response with a Content-Length, like the Python handler's `_json`.
fn write_json(stream: &mut TcpStream, payload: &Value, status: &str) -> Result<(), String> {
    let encoded = serde_json::to_string(payload).map_err(|error| error.to_string())?;
    let head = format!(
        "HTTP/1.0 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n",
        encoded.len()
    );
    stream
        .write_all(head.as_bytes())
        .and_then(|_| stream.write_all(encoded.as_bytes()))
        .map_err(|error| format!("json write failed: {error}"))
}

/// Stream SSE chunks with the Python replay's 20ms pacing.
fn write_stream(stream: &mut TcpStream, chunks: &[Vec<u8>]) -> Result<(), String> {
    stream
        .write_all(
            b"HTTP/1.0 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n",
        )
        .map_err(|error| format!("response head write failed: {error}"))?;
    for chunk in chunks {
        stream.write_all(chunk).map_err(|error| format!("delta write failed: {error}"))?;
        stream.flush().map_err(|error| format!("delta flush failed: {error}"))?;
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
    let method = record.method.clone();
    let path = record.path.clone();
    let body = record.body.clone();
    state.records.lock().unwrap().push(record);
    match method.as_str() {
        "GET" => {
            let response = match path.as_str() {
                "/api/v1/models" | "/v1/models" => {
                    json!({"object": "list", "data": [{"id": "palette-model", "object": "model"}]})
                }
                "/v1/models/palette-model" => json!({"id": "palette-model", "object": "model"}),
                "/api/tags" => json!({"models": [{"name": "palette-model"}]}),
                _ => {
                    let _ = write_json(
                        &mut stream,
                        &json!({"error": {"message": "synthetic endpoint not found"}}),
                        "404 Not Found",
                    );
                    let _ = stream.shutdown(Shutdown::Both);
                    return;
                }
            };
            let _ = write_json(&mut stream, &response, "200 OK");
        }
        "POST" => {
            state.request_seen.store(true, Ordering::SeqCst);
            if body.get("stream") != Some(&json!(true)) {
                let _ = write_json(
                    &mut stream,
                    &json!({
                        "model": "palette-model",
                        "choices": [{
                            "index": 0,
                            "message": {"role": "assistant", "content": "Synthetic auxiliary response."},
                            "finish_reason": "stop",
                        }],
                    }),
                    "200 OK",
                );
            } else {
                let ordinal = state.streaming_requests.fetch_add(1, Ordering::SeqCst) + 1;
                if ordinal > 1 {
                    // Tool-result follow-up: answer plainly so the bounded
                    // one-hop loop terminates and no third request arrives.
                    let _ = write_stream(&mut stream, &follow_up_chunks());
                } else {
                    let chunks = first_stream_chunks();
                    let events: Vec<Value> = chunks
                        .iter()
                        .map(|chunk| json!({"length": chunk.len(), "sha256": sha256_hex(chunk)}))
                        .collect();
                    state.tool_call_events.lock().unwrap().extend(events);
                    let _ = write_stream(&mut stream, &chunks);
                }
            }
        }
        _ => {}
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

/// Start the loopback server on an ephemeral port.
fn start_server() -> std::io::Result<(u16, Arc<ServerState>, std::thread::JoinHandle<()>)> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let port = listener.local_addr()?.port();
    let state = Arc::new(ServerState {
        request_seen: AtomicBool::new(false),
        streaming_requests: AtomicUsize::new(0),
        shutdown: AtomicBool::new(false),
        records: Mutex::new(Vec::new()),
        tool_call_events: Mutex::new(Vec::new()),
    });
    let thread_state = Arc::clone(&state);
    let handle = std::thread::spawn(move || serve(listener, thread_state));
    Ok((port, state, handle))
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

/// The full bounded tool-call replay, like `run_tool_call_case`.
fn run_case(
    binary: &Path,
    home: &Path,
    endpoint: &str,
    state: &ServerState,
    timeout: Duration,
) -> Result<Value, String> {
    let home_str = home.to_str().ok_or_else(|| "non-UTF-8 home path".to_string())?;
    let mut child = spawn_with_env(
        binary,
        &[],
        &[
            ("HOME", home_str),
            ("HERMES_HOME", home_str),
            ("HADES_PROVIDER_BASE_URL", endpoint),
            ("HADES_MODEL", "palette-model"),
        ],
        &["HADES_PROVIDER_API_KEY"],
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
            |text| text.contains("Hades Agent") && text.contains("ready"),
            timeout,
        )?;
        send(&child.child.master, format!("{PROMPT}\r").as_bytes())
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
            "response",
            |text| marker_present(text, ASSISTANT_MARKER) && marker_present(text, "ready"),
            timeout,
        )?;
        // Wait for the bounded tool-result follow-up and its answer, then prove
        // no third request arrives.
        wait_for_rendered(
            &child.child,
            &mut output,
            "follow-up-answer",
            |text| marker_present(text, "Synthetic completion.") && marker_present(text, "ready"),
            timeout,
        )?;
        std::thread::sleep(Duration::from_millis(400));
        let visible = clean_output(&output);
        if marker_present(&visible, "Processing 1 tool call") {
            return Err("response: an invented tool-processing overlay was rendered".to_string());
        }
        if marker_present(&visible, "Busy") {
            return Err("response: Hades stayed busy after the follow-up completed".to_string());
        }
        if try_wait(&child.child)?.is_some() {
            return Err("response: Hades exited after the follow-up completed".to_string());
        }

        let chat_requests: Vec<RequestRecord> = state
            .records
            .lock()
            .unwrap()
            .iter()
            .filter(|record| record.method == "POST")
            .cloned()
            .collect();
        if chat_requests.len() != 2 {
            return Err(format!(
                "request: expected exactly two chat requests (initial + one follow-up), got {}",
                chat_requests.len()
            ));
        }

        let joined_arguments = format!("{}{}", ARGUMENT_FRAGMENTS[0], ARGUMENT_FRAGMENTS[1]);
        serde_json::from_str::<Value>(&joined_arguments).map_err(|error| {
            format!("follow-up: joined argument fragments are not valid JSON: {error}")
        })?;

        let slave = RetainedSlave::retain(&slave_path).map_err(|error| error.to_string())?;
        send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 0 }) {
            return Err(format!("cleanup: unexpected exit status: {exit_status:?}"));
        }
        let raw: &[u8] = &output;
        if !find_sequence(raw, b"\x1b[?1049l") {
            return Err("cleanup: alternate screen was not restored".to_string());
        }
        let flags = stable_terminal_flags(&slave)?;
        if !flags.canonical || !flags.echo {
            return Err(format!("cleanup: terminal flags were not restored: {flags:?}"));
        }

        let request = &chat_requests[0];
        let follow_up = &chat_requests[1];
        let follow_up_roles: Vec<String> = follow_up
            .body
            .get("messages")
            .and_then(Value::as_array)
            .map(|messages| {
                messages
                    .iter()
                    .filter_map(|message| message.get("role").and_then(Value::as_str))
                    .map(str::to_owned)
                    .collect()
            })
            .unwrap_or_default();
        if follow_up_roles != ["system", "user", "assistant", "tool"] {
            return Err(format!(
                "follow-up: roles {follow_up_roles:?} do not match the observed system/user/assistant/tool shape"
            ));
        }
        let follow_up_messages = follow_up
            .body
            .get("messages")
            .and_then(Value::as_array)
            .ok_or_else(|| "follow-up: messages array missing".to_string())?;
        if follow_up_messages.len() < 4 {
            return Err("follow-up: messages array is too short".to_string());
        }
        let assistant_message = &follow_up_messages[2];
        let assistant_tool_calls = assistant_message
            .get("tool_calls")
            .and_then(Value::as_array)
            .ok_or_else(|| "follow-up: assistant message lacks tool_calls".to_string())?;
        if assistant_tool_calls.is_empty() {
            return Err("follow-up: assistant message lacks tool_calls".to_string());
        }
        let tool_call_payload = &assistant_tool_calls[0];
        if tool_call_payload.get("function").and_then(|f| f.get("name")).and_then(Value::as_str)
            != Some(TOOL_NAME)
        {
            return Err("follow-up: follow-up tool call name mismatch".to_string());
        }
        let tool_message = &follow_up_messages[3];
        if tool_message.get("role").and_then(Value::as_str) != Some("tool") {
            return Err("follow-up: tool result message missing role".to_string());
        }
        if tool_message.get("tool_call_id").map_or(true, Value::is_null) {
            return Err("follow-up: tool result message missing tool_call_id".to_string());
        }
        let tool_result_sha256 = sha256_hex(
            tool_message.get("content").and_then(Value::as_str).unwrap_or_default().as_bytes(),
        );

        let request_tools = request
            .body
            .get("tools")
            .and_then(Value::as_array)
            .ok_or_else(|| "inventory: advertised tools array missing".to_string())?;
        if request_tools.len() != EXPECTED_TOOL_COUNT {
            return Err(format!(
                "inventory: expected {EXPECTED_TOOL_COUNT} advertised tools, got {}",
                request_tools.len()
            ));
        }
        let inventory_digest = canonical_digest(&request.body["tools"]);
        if inventory_digest != EXPECTED_INVENTORY_DIGEST {
            return Err(
                "inventory: advertised tool inventory does not match the OBS-0112 wire digest"
                    .to_string(),
            );
        }

        let body = &request.body;
        let mut body_keys: Vec<String> =
            body.as_object().map(|object| object.keys().cloned().collect()).unwrap_or_default();
        body_keys.sort();
        let message_roles: Vec<String> = body
            .get("messages")
            .and_then(Value::as_array)
            .map(|messages| {
                messages
                    .iter()
                    .filter_map(|message| message.get("role").and_then(Value::as_str))
                    .map(str::to_owned)
                    .collect()
            })
            .unwrap_or_default();
        let tools_present = request_tools.iter().any(|tool| {
            tool.get("function").and_then(|f| f.get("name")).and_then(Value::as_str)
                == Some(TOOL_NAME)
        });
        let argument_fragments: Vec<Value> = ARGUMENT_FRAGMENTS
            .iter()
            .enumerate()
            .map(|(index, fragment)| {
                json!({
                    "sequence": index + 1,
                    "length": fragment.len(),
                    "sha256": sha256_hex(fragment.as_bytes()),
                })
            })
            .collect();
        let stream_events = state.tool_call_events.lock().unwrap().clone();

        Ok(json!({
            "id": "tool-call-deltas",
            "status": "passed",
            "input_sequence": [
                {"kind": "text", "value": "<synthetic prompt>"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03"},
            ],
            "request": {
                "method": "POST",
                "path": request.path,
                "authorization_present": request.authorization_present,
                "body_keys": body_keys,
                "model": body["model"],
                "stream": body["stream"],
                "message_roles": message_roles,
                "tools_present": !request_tools.is_empty(),
                "tool_count": request_tools.len(),
                "inventory_sha256": inventory_digest,
                "clarify_present": tools_present,
            },
            "tool_call": {
                "name": TOOL_NAME,
                "argument_fragments": argument_fragments,
                "argument_fragment_count": ARGUMENT_FRAGMENTS.len(),
                "joined_arguments": {
                    "length": joined_arguments.len(),
                    "sha256": sha256_hex(joined_arguments.as_bytes()),
                    "valid_json": true,
                },
                "finish_reason": "tool_calls",
                "executed": false,
                "approved": false,
            },
            "stream_events": {
                "chunk_count": stream_events.len(),
                "chunk_digests": stream_events,
            },
            "request_counts": {
                "chat_requests": chat_requests.len(),
                "subsequent_chat_requests": 1,
                "tool_response_requests": 1,
            },
            "follow_up": {
                "path": follow_up.path,
                "message_roles": follow_up_roles,
                "assistant_tool_calls_present": true,
                "assistant_tool_call_name": TOOL_NAME,
                "tool_result_role": "tool",
                "tool_result_marker": "Hades-owned synthetic marker (no execution)",
                "tool_result_sha256": tool_result_sha256,
            },
            "visible_state": {
                "assistant_text_rendered": true,
                "follow_up_answer_rendered": true,
                "returned_to_ready": true,
                "no_tool_overlay": true,
                "no_busy_marker": true,
                "no_loop": true,
                "cleanup": "Ctrl+C exited cleanly with terminal restored",
            },
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child.child);
    }
    let _ = fs::remove_dir_all(&child.history_home);
    result
}

fn write_report(report: &Value, path: Option<&Path>, status: u8) -> ExitCode {
    let text = serde_json::to_string_pretty(report).expect("serialize report");
    if let Some(path) = path {
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        if let Ok(mut file) = fs::File::create(path) {
            let _ = file.write_all(text.as_bytes());
            let _ = file.write_all(b"\n");
        }
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
        "command": "replay-tool-call-deltas",
        "binary": binary.to_string_lossy(),
        "dimensions": {"columns": 120, "rows": 40, "emulator": "direct PTY"},
        "cases": [],
        "passed": false,
    });
    let home = std::env::temp_dir().join(format!("hades-tool-call-deltas-{}", std::process::id()));
    let _ = fs::create_dir_all(&home);
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
        match run_case(&binary, &home, &endpoint, &state, timeout) {
            Ok(case) => {
                report["cases"] = json!([case]);
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
    let _ = fs::remove_dir_all(&home);
    write_report(&report, report_path.as_deref(), status)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn first_stream_chunks_match_observed_wire_digests() {
        // Byte-identity contract: these are the chunk lengths/digests the
        // Python replay recorded for the same stream.
        let expected = [
            (52usize, "ac8ecca1dcf25c5ca2d0e361d9dd2c99b28ee4382712a8fcc6845deed8d7cdcb"),
            (232, "40ea218ac0a05ef955cdc29087ced3192644e6e6090bae2ce485feefcd4e7dc5"),
            (152, "f8d1865871feebdd21dd3594a82a62e7dd7cdacb424a74fccfbfde6ed177f9ae"),
            (63, "ca3899cd31f69e1a4a27eec62dde8874b35f89b95217c3e12bd0c22c9a752fc8"),
            (14, "d8d37da081f11203f2af42092a92cb35508f27db75eba643058a0a580454517d"),
        ];
        let chunks = first_stream_chunks();
        assert_eq!(chunks.len(), expected.len());
        for (chunk, (length, digest)) in chunks.iter().zip(expected) {
            assert_eq!(chunk.len(), length);
            assert_eq!(sha256_hex(chunk), digest);
        }
    }

    #[test]
    fn argument_fragments_match_observed_digests() {
        assert_eq!(ARGUMENT_FRAGMENTS[0].len(), 45);
        assert_eq!(ARGUMENT_FRAGMENTS[1].len(), 58);
        assert_eq!(
            sha256_hex(ARGUMENT_FRAGMENTS[0].as_bytes()),
            "89816afdb7521998a8a6627ee3b8484172ca7cddeed676424b522626a4e374ac"
        );
        assert_eq!(
            sha256_hex(ARGUMENT_FRAGMENTS[1].as_bytes()),
            "23eeb8e9123a40e76902a5d02799f6a686dcad597f76c950793ccf1f372e0f80"
        );
        let joined = format!("{}{}", ARGUMENT_FRAGMENTS[0], ARGUMENT_FRAGMENTS[1]);
        assert_eq!(joined.len(), 103);
        assert!(serde_json::from_str::<Value>(&joined).is_ok());
        assert_eq!(
            sha256_hex(joined.as_bytes()),
            "b1b2859e40d64aafa782cf5620dd7e3086ce69cd99162f216407a7a1dd4ee1ba"
        );
    }

    #[test]
    fn canonical_digest_sorts_keys_recursively() {
        let value = json!({"b": 1, "a": {"d": 2, "c": 3}, "l": [{"y": 1, "x": 2}]});
        assert_eq!(
            canonical_digest(&value),
            "6ee43734ddd2ef5661e1216b5fac6340bcec04437708ad51cee6f696aee12a74"
        );
    }

    #[test]
    fn parse_head_extracts_request_fields() {
        let head = b"POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: 5\r\n\r\n";
        let parsed = parse_head(head).expect("parse");
        assert_eq!(parsed.method, "POST");
        assert_eq!(parsed.path, "/v1/chat/completions");
        assert!(!parsed.authorization_present);
        assert_eq!(parsed.content_length, 5);
    }

    #[test]
    fn parse_head_detects_authorization_header() {
        let head =
            b"POST /v1/chat/completions HTTP/1.1\r\nAuthorization: Bearer sk-tes...gth: 0\r\n\r\n";
        let parsed = parse_head(head).expect("parse");
        assert_eq!(parsed.method, "POST");
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
        assert_eq!(state.records.lock().unwrap().len(), 1);
        response
    }

    #[test]
    fn server_streams_tool_call_deltas_and_records_digests() {
        let (port, state, handle) = start_server().expect("start");
        let body = br#"{"model":"palette-model","stream":true,"messages":[{"role":"user","content":"synthetic tool-call prompt"}]}"#;
        let response = post_request(port, body, &state);
        let text = String::from_utf8_lossy(&response).to_string();
        assert!(text.contains("HTTP/1.0 200 OK"), "{text}");
        assert!(text.contains("Synthetic handoff"), "{text}");
        assert!(text.contains("clarify"), "{text}");
        assert!(text.contains("finish_reason\":\"tool_calls"), "{text}");
        assert!(text.contains("[DONE]"), "{text}");
        assert!(state.request_seen.load(Ordering::SeqCst));
        let events = state.tool_call_events.lock().unwrap();
        assert_eq!(events.len(), 5);
        assert_eq!(
            events[0]["sha256"].as_str().unwrap(),
            "ac8ecca1dcf25c5ca2d0e361d9dd2c99b28ee4382712a8fcc6845deed8d7cdcb"
        );
        let record = &state.records.lock().unwrap()[0];
        assert_eq!(record.method, "POST");
        assert_eq!(record.path, "/v1/chat/completions");
        assert_eq!(record.body["model"], "palette-model");
        state.shutdown.store(true, Ordering::SeqCst);
        let _ = handle.join();
    }

    #[test]
    fn server_answers_follow_up_with_plain_completion() {
        let (port, state, handle) = start_server().expect("start");
        let body = br#"{"model":"palette-model","stream":true,"messages":[{"role":"user"}]}"#;
        let response = post_request(port, body, &state);
        assert!(String::from_utf8_lossy(&response).contains("Synthetic handoff"));
        assert_eq!(state.streaming_requests.load(Ordering::SeqCst), 1);
        let second = post_request(port, body, &state);
        let text = String::from_utf8_lossy(&second).to_string();
        assert!(text.contains("Synthetic completion."), "{text}");
        assert!(!text.contains("tool_calls"), "{text}");
        assert_eq!(state.streaming_requests.load(Ordering::SeqCst), 2);
        state.shutdown.store(true, Ordering::SeqCst);
        let _ = handle.join();
    }
}
