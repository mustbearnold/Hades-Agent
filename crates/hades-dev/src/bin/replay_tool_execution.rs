//! `hades-dev replay-tool-execution` — Rust direct-PTY replay of the Hades
//! multi-hop tool loop (spec 011, OBS-0120).
//!
//! Replays the observed S4 scenario through a real PTY: the loopback provider
//! asks Hades to execute a `terminal` tool call whose only side effect writes
//! into the probe-owned sandbox (`mkdir -p <sandbox>/hopdir && echo hop-one >
//! <sandbox>/hopdir/hop.txt`), then a `read_file` tool call on the written
//! file, then a plain completion — two hops then termination. Hades must
//! execute both tools against the explicit `HADES_SANDBOX` root, feed the
//! executed results back through the follow-up requests in the observed
//! `system,user,assistant,tool` shape, and terminate when the follow-up
//! stream carries no tool calls. The report carries only path-free
//! normalized facts so the Python replay (`scripts/replay_tool_execution.py`)
//! and this binary compare identically under `check_replay_parity.py`.
//!
//! The executed tool results are asserted byte-exact against the reference
//! digests: the terminal result is `{"output": "", "exit_code": 0,
//! "error": null}` (45 bytes, digest `708054e2…` from OBS-0117/0120) and the
//! read_file result is the 121-byte `fb3accfc…` digest from OBS-0120.

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

const PROMPT: &str = "synthetic multi-hop prompt";
const TERMINAL_MARKER: &str = "Synthetic multi-hop terminal call";
const READ_MARKER: &str = "Synthetic multi-hop read call";
const COMPLETION_TEXT: &str = "Synthetic completion.";
const EXPECTED_TOOL_COUNT: usize = 31;
// Canonical sort-keys SHA-256 of the OBS-0112 31-tool inventory.
const EXPECTED_INVENTORY_DIGEST: &str =
    "b2cbd3f2bf77de3a91cf9a4844b324f6130aab8c72b2924a159cce533f38a220";
// OBS-0117/0120 byte-exact tool-result digests (path-free, stable across runs).
const TERMINAL_RESULT_DIGEST: &str =
    "708054e20f8345e96aa29aa3d3ae50e6245e6723619f1f57c1486f2c2ef9c451";
const READ_RESULT_DIGEST: &str = "fb3accfce3bc199b09eebb2e2e03ea41ff7467e0f76fc5e75ce6849fa6ff856f";
// OBS-0120 sandbox side effect: `echo hop-one > .../hop.txt` (trailing newline).
const HOP_CONTENT: &str = "hop-one\n";
const HOP_DIGEST: &str = "8dafa0ec68b138aeb867e95010596f555ee72018ca35ae8ee8d4fdca3c55b030";

fn sha256_hex(bytes: &[u8]) -> String {
    let mut digest = Sha256::new();
    digest.update(bytes);
    format!("{:x}", digest.finalize())
}

/// Sort object keys recursively and hash the compact serialization,
/// matching the Python probe/validator canonical digest convention.
/// serde_json's `Map` is BTreeMap-backed, so keys already serialize sorted;
/// its compact formatter writes non-ASCII raw like `ensure_ascii=False`.
fn canonical_digest(value: &Value) -> String {
    sha256_hex(serde_json::to_string(value).expect("canonical serialization").as_bytes())
}

fn tool_call_chunks(marker: &str, tool: &str, call_id: &str, arguments: &str) -> Vec<Vec<u8>> {
    let encoded = serde_json::to_string(arguments).expect("arguments serialize");
    vec![
        b"data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n".to_vec(),
        format!(
            "data: {{\"choices\":[{{\"delta\":{{\"content\":\"{marker}\",\
             \"tool_calls\":[{{\"index\":0,\"id\":\"{call_id}\",\"type\":\"function\",\
             \"function\":{{\"name\":\"{tool}\",\"arguments\":{encoded}}}}}]}}}}]}}\n\n"
        )
        .into_bytes(),
        b"data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"tool_calls\"}]}\n\n".to_vec(),
        b"data: [DONE]\n\n".to_vec(),
    ]
}

fn completion_chunks(text: &str) -> Vec<Vec<u8>> {
    vec![
        b"data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n".to_vec(),
        format!("data: {{\"choices\":[{{\"delta\":{{\"content\":\"{text}\"}}}}]}}\n\n")
            .into_bytes(),
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

/// Shared server state: recorded requests plus the streaming ordinal.
struct ServerState {
    streaming_requests: AtomicUsize,
    shutdown: AtomicBool,
    records: Mutex<Vec<RequestRecord>>,
}

/// Parsed request head: header block end plus the fields the replay asserts.
struct ParsedHead {
    header_end: usize,
    method: String,
    path: String,
    authorization_present: bool,
    content_length: usize,
}

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

fn handle_connection(
    mut stream: TcpStream,
    state: Arc<ServerState>,
    script: Arc<Vec<Vec<Vec<u8>>>>,
) {
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
                let chunks: &[Vec<u8>] =
                    if ordinal <= script.len() { &script[ordinal - 1] } else { &[] };
                if chunks.is_empty() {
                    let _ = write_json(
                        &mut stream,
                        &json!({"error": {"message": "synthetic script exhausted"}}),
                        "500 Internal Server Error",
                    );
                } else {
                    let _ = write_stream(&mut stream, chunks);
                }
            }
        }
        _ => {}
    }
    let _ = stream.shutdown(Shutdown::Both);
}

fn serve(listener: TcpListener, state: Arc<ServerState>, script: Arc<Vec<Vec<Vec<u8>>>>) {
    let _ = listener.set_nonblocking(true);
    loop {
        if state.shutdown.load(Ordering::SeqCst) {
            break;
        }
        match listener.accept() {
            Ok((stream, _)) => {
                let state = Arc::clone(&state);
                let script = Arc::clone(&script);
                std::thread::spawn(move || handle_connection(stream, state, script));
            }
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                std::thread::sleep(Duration::from_millis(20));
            }
            Err(_) => break,
        }
    }
}

fn start_server(
    script: Vec<Vec<Vec<u8>>>,
) -> std::io::Result<(u16, Arc<ServerState>, std::thread::JoinHandle<()>)> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    let port = listener.local_addr()?.port();
    let state = Arc::new(ServerState {
        streaming_requests: AtomicUsize::new(0),
        shutdown: AtomicBool::new(false),
        records: Mutex::new(Vec::new()),
    });
    let thread_state = Arc::clone(&state);
    let script = Arc::new(script);
    let thread_script = Arc::clone(&script);
    let handle = std::thread::spawn(move || serve(listener, thread_state, thread_script));
    Ok((port, state, handle))
}

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

/// Path-free structural shape of a tool-call argument payload, mirroring the
/// probe's `tool_arguments_shape` markers so reports stay run-invariant.
fn argument_shape(arguments: &str) -> Value {
    let parsed: Value = serde_json::from_str(arguments).unwrap_or(Value::Null);
    let mut shape = json!({ "valid_json": !parsed.is_null() });
    if let Some(object) = parsed.as_object() {
        let mut keys = object.keys().cloned().collect::<Vec<_>>();
        keys.sort();
        shape["top_level_keys"] = json!(keys);
        let value_kinds = object
            .iter()
            .map(|(key, value)| {
                let kind = match value {
                    Value::Null => "NoneType",
                    Value::Bool(_) => "bool",
                    Value::Number(_) => "int",
                    Value::String(_) => "str",
                    Value::Array(_) => "list",
                    Value::Object(_) => "dict",
                };
                (key.clone(), Value::String(kind.to_owned()))
            })
            .collect::<serde_json::Map<_, _>>();
        shape["value_kinds"] = Value::Object(value_kinds);
        if let Some(command) = object.get("command").and_then(Value::as_str) {
            let lowered = command.to_ascii_lowercase();
            shape["markers"] = json!({
                "contains_mkdir": lowered.contains("mkdir"),
                "contains_echo": lowered.contains("echo"),
                "contains_redirection": command.contains('>'),
                "contains_chain": command.contains("&&"),
                "contains_expected_basename": command.contains("hop.txt"),
            });
        } else if let Some(path) = object.get("path").and_then(Value::as_str) {
            shape["markers"] = json!({
                "path_ends_with_expected_basename": path.ends_with("hop.txt"),
            });
        }
    }
    shape
}

fn run_case(
    binary: &Path,
    home: &Path,
    sandbox: &Path,
    endpoint: &str,
    state: &ServerState,
    timeout: Duration,
) -> Result<Value, String> {
    let home_str = home.to_str().ok_or_else(|| "non-UTF-8 home path".to_string())?;
    let sandbox_str = sandbox.to_str().ok_or_else(|| "non-UTF-8 sandbox path".to_string())?;
    let mut child = spawn_with_env(
        binary,
        &[],
        &[
            ("HOME", home_str),
            ("HERMES_HOME", home_str),
            ("HADES_SANDBOX", sandbox_str),
            ("HADES_PROVIDER_BASE_URL", endpoint),
            ("HADES_MODEL", "palette-model"),
        ],
        // No API key: like the Python replay, the loopback fixture is
        // unauthenticated so both reports record `authorization_present:
        // false` deterministically.
        &[],
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
        wait_for_rendered(
            &child.child,
            &mut output,
            "terminal-result-follow-up",
            |text| marker_present(text, TERMINAL_MARKER) && marker_present(text, "ready"),
            timeout,
        )?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "read-result-follow-up",
            |text| marker_present(text, READ_MARKER) && marker_present(text, "ready"),
            timeout,
        )?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "completion",
            |text| marker_present(text, COMPLETION_TEXT) && marker_present(text, "ready"),
            timeout,
        )?;
        // Termination proof: the follow-up stream carried no tool calls, so
        // no fourth request may arrive.
        std::thread::sleep(Duration::from_millis(400));
        if state.streaming_requests.load(Ordering::SeqCst) != 3 {
            return Err(format!(
                "request-count: expected exactly 3 streaming chat requests, got {}",
                state.streaming_requests.load(Ordering::SeqCst)
            ));
        }
        let visible = clean_output(&output);
        if marker_present(&visible, "Busy") {
            return Err("response: Hades stayed busy after the completion".to_string());
        }
        if try_wait(&child.child)?.is_some() {
            return Err("response: Hades exited before Ctrl+C".to_string());
        }

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

        let chat_requests: Vec<RequestRecord> = state
            .records
            .lock()
            .unwrap()
            .iter()
            .filter(|record| record.method == "POST")
            .cloned()
            .collect();
        if chat_requests.len() != 3 {
            return Err(format!(
                "request-count: expected 3 chat requests (initial + two follow-ups), got {}",
                chat_requests.len()
            ));
        }
        let request = &chat_requests[0];
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

        fn message_roles(body: &Value) -> Vec<String> {
            body.get("messages")
                .and_then(Value::as_array)
                .map(|messages| {
                    messages
                        .iter()
                        .filter_map(|message| message.get("role").and_then(Value::as_str))
                        .map(str::to_owned)
                        .collect()
                })
                .unwrap_or_default()
        }

        fn verify_follow_up(
            follow_up: &RequestRecord,
            expected_roles: &[&str],
            call_name: &str,
            result_digest: &str,
        ) -> Result<Value, String> {
            let body = &follow_up.body;
            let messages = body
                .get("messages")
                .and_then(Value::as_array)
                .ok_or_else(|| "follow-up: messages array missing".to_string())?;
            let roles = message_roles(body);
            if roles != expected_roles {
                return Err(format!(
                    "follow-up: roles {roles:?} do not match the observed {expected_roles:?} shape"
                ));
            }
            let assistant_message = &messages[messages.len() - 2];
            let assistant_tool_calls = assistant_message
                .get("tool_calls")
                .and_then(Value::as_array)
                .ok_or_else(|| "follow-up: assistant message lacks tool_calls".to_string())?;
            if assistant_tool_calls
                .first()
                .and_then(|call| call.get("function"))
                .and_then(|function| function.get("name"))
                .and_then(Value::as_str)
                != Some(call_name)
            {
                return Err("follow-up: follow-up tool call name mismatch".to_string());
            }
            let tool_message = &messages[messages.len() - 1];
            if tool_message.get("role").and_then(Value::as_str) != Some("tool")
                || tool_message.get("tool_call_id").is_none_or(Value::is_null)
            {
                return Err("follow-up: tool result message missing role/tool_call_id".to_string());
            }
            let content = tool_message
                .get("content")
                .and_then(Value::as_str)
                .ok_or_else(|| "follow-up: tool result content missing".to_string())?;
            let content_digest = sha256_hex(content.as_bytes());
            if content_digest != result_digest {
                return Err(format!(
                    "follow-up: tool result digest {content_digest} does not match the observed {result_digest}"
                ));
            }
            let parsed: Value = serde_json::from_str(content).unwrap_or(Value::Null);
            let mut top_level_keys = parsed
                .as_object()
                .map(|object| object.keys().cloned().collect::<Vec<_>>())
                .unwrap_or_default();
            top_level_keys.sort();
            let id_markers = messages
                .iter()
                .map(|message| {
                    let id = message.get("tool_call_id").and_then(Value::as_str);
                    match id {
                        Some("call_synthetic_terminal") | Some("call_synthetic_read_file") => {
                            "synthetic-call-id".to_owned()
                        }
                        Some(_) => "other-id".to_owned(),
                        None => "absent".to_owned(),
                    }
                })
                .collect::<Vec<_>>();
            Ok(json!({
                "message_roles": roles,
                "message_count": messages.len(),
                "tool_result_messages": messages
                    .iter()
                    .filter(|message| message.get("role").and_then(Value::as_str) == Some("tool"))
                    .count(),
                "tool_call_id_markers": id_markers,
                "assistant_tool_call_name": call_name,
                "tool_result_sha256": content_digest,
                "tool_result_top_level_keys": top_level_keys,
            }))
        }

        let follow_up_1 = verify_follow_up(
            &chat_requests[1],
            &["system", "user", "assistant", "tool"],
            "terminal",
            TERMINAL_RESULT_DIGEST,
        )?;
        let follow_up_2 = verify_follow_up(
            &chat_requests[2],
            &["system", "user", "assistant", "tool", "assistant", "tool"],
            "read_file",
            READ_RESULT_DIGEST,
        )?;

        let hop = sandbox.join("hopdir").join("hop.txt");
        let hop_bytes = fs::read(&hop).unwrap_or_default();
        let hop_matches = hop_bytes == HOP_CONTENT.as_bytes();
        let content_sha256 = sha256_hex(&hop_bytes);
        if content_sha256 != HOP_DIGEST {
            return Err(format!(
                "sandbox-side-effect: hop.txt digest {content_sha256} does not match the observed {HOP_DIGEST}"
            ));
        }
        let side_effects = json!({
            "files": [{
                "basename": "hop.txt",
                "exists": hop.is_file(),
                "content_matches_expected": hop_matches
                    || hop_bytes == format!("{HOP_CONTENT}\n").as_bytes(),
                "content_length": hop_bytes.len(),
                "content_sha256": content_sha256,
            }],
            "match": hop_matches,
        });
        if !hop_matches {
            return Err(
                "sandbox-side-effect: the executed terminal tool did not produce the expected probe-owned sandbox file"
                    .to_string(),
            );
        }

        let terminal_arguments =
            serde_json::to_string(&json!({"command": format!("mkdir -p {} && echo hop-one > {}", sandbox.join("hopdir").display(), hop.display())}))
                .expect("terminal arguments serialize");
        let read_arguments = serde_json::to_string(&json!({"path": hop.to_string_lossy()}))
            .expect("read args serialize");

        let mut body_keys: Vec<String> = request
            .body
            .as_object()
            .map(|object| object.keys().cloned().collect())
            .unwrap_or_default();
        body_keys.sort();

        Ok(json!({
            "id": "tool-execution-multi-hop",
            "status": "passed",
            "input_sequence": [
                {"kind": "text", "value": "<synthetic prompt>"},
                {"kind": "key", "value": "Enter", "bytes_hex": "0d"},
                {"kind": "key", "value": "Ctrl+C", "bytes_hex": "03"},
            ],
            "provider_request": {
                "path": request.path,
                "authorization_present": request.authorization_present,
                "body_keys": body_keys,
                "model": request.body["model"],
                "stream": request.body["stream"],
                "message_roles": message_roles(&request.body),
                "tool_count": request_tools.len(),
                "inventory_sha256": inventory_digest,
                "terminal_present": request_tools.iter().any(|tool| {
                    tool.get("function").and_then(|f| f.get("name")).and_then(Value::as_str)
                        == Some("terminal")
                }),
                "read_file_present": request_tools.iter().any(|tool| {
                    tool.get("function").and_then(|f| f.get("name")).and_then(Value::as_str)
                        == Some("read_file")
                }),
            },
            "tool_calls": [
                {
                    "name": "terminal",
                    "call_id_marker": "synthetic-call-id",
                    "arguments": argument_shape(&terminal_arguments),
                },
                {
                    "name": "read_file",
                    "call_id_marker": "synthetic-call-id",
                    "arguments": argument_shape(&read_arguments),
                },
            ],
            "follow_up_requests": [
                {"sequence": 2, "message_roles": follow_up_1["message_roles"],
                 "message_count": follow_up_1["message_count"],
                 "tool_result_messages": follow_up_1["tool_result_messages"],
                 "tool_call_id_markers": follow_up_1["tool_call_id_markers"],
                 "assistant_tool_call_name": follow_up_1["assistant_tool_call_name"],
                 "tool_result_sha256": follow_up_1["tool_result_sha256"],
                 "tool_result_top_level_keys": follow_up_1["tool_result_top_level_keys"]},
                {"sequence": 3, "message_roles": follow_up_2["message_roles"],
                 "message_count": follow_up_2["message_count"],
                 "tool_result_messages": follow_up_2["tool_result_messages"],
                 "tool_call_id_markers": follow_up_2["tool_call_id_markers"],
                 "assistant_tool_call_name": follow_up_2["assistant_tool_call_name"],
                 "tool_result_sha256": follow_up_2["tool_result_sha256"],
                 "tool_result_top_level_keys": follow_up_2["tool_result_top_level_keys"]},
            ],
            "sandbox_side_effects": side_effects,
            "request_counts": {
                "chat_requests": chat_requests.len(),
                "streaming_requests": state.streaming_requests.load(Ordering::SeqCst),
                "subsequent_chat_requests": chat_requests.len() - 1,
                "tool_result_requests": 2,
                "auxiliary_responses": 0,
            },
            "termination": {
                "completion_text": COMPLETION_TEXT,
                "completion_served": true,
                "no_fourth_request": true,
                "clean_exit": true,
            },
            "visible_state": {
                "terminal_marker": marker_present(&visible, TERMINAL_MARKER),
                "read_file_marker": marker_present(&visible, READ_MARKER),
                "completion_rendered": marker_present(&visible, COMPLETION_TEXT),
                "returned_to_ready": marker_present(&visible, "ready"),
                "no_busy_marker": !marker_present(&visible, "Busy"),
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
        "command": "replay-tool-execution",
        "binary": binary.to_string_lossy(),
        "dimensions": {"columns": 120, "rows": 40, "emulator": "direct PTY"},
        "cases": [],
        "passed": false,
    });
    let home = std::env::temp_dir().join(format!("hades-tool-execution-{}", std::process::id()));
    let _ = fs::create_dir_all(&home);
    // Fixed-length probe-owned sandbox root (like the Python replay's
    // `mkdtemp(prefix="hades-toolexec-")`); the report never embeds it.
    let sandbox = std::env::temp_dir().join(format!("hades-toolexec-{:08x}", std::process::id()));
    let _ = fs::create_dir_all(&sandbox);
    let hopdir = sandbox.join("hopdir");
    let hop = hopdir.join("hop.txt");
    let terminal_arguments =
        serde_json::to_string(&json!({"command": format!("mkdir -p {} && echo hop-one > {}", hopdir.display(), hop.display())}))
            .expect("terminal arguments serialize");
    let read_arguments = serde_json::to_string(&json!({"path": hop.to_string_lossy()}))
        .expect("read args serialize");
    let script = vec![
        tool_call_chunks(
            TERMINAL_MARKER,
            "terminal",
            "call_synthetic_terminal",
            &terminal_arguments,
        ),
        tool_call_chunks(READ_MARKER, "read_file", "call_synthetic_read_file", &read_arguments),
        completion_chunks(COMPLETION_TEXT),
    ];

    let (port, state, server_thread) = match start_server(script) {
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
        match run_case(&binary, &home, &sandbox, &endpoint, &state, timeout) {
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
    let _ = fs::remove_dir_all(&sandbox);
    write_report(&report, report_path.as_deref(), status)
}

#[cfg(test)]
mod tests {
    use hades_tools::{Sandbox, ToolCallRecord};

    use super::*;

    /// The replay's byte-exact result expectations are the real executor's
    /// outputs for the OBS-0120 probe commands (terminal on the sandbox, then
    /// read_file on the written file).
    #[test]
    fn executed_results_match_the_obs_0120_digests() {
        let root = std::env::temp_dir().join(format!(
            "hades-replay-obs0120-{}-{:x}",
            std::process::id(),
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()
        ));
        fs::create_dir_all(&root).expect("create sandbox root");
        let sandbox = Sandbox::new(root.clone());
        let hop = root.join("hopdir").join("hop.txt");
        let command = format!(
            "mkdir -p {} && echo hop-one > {}",
            hop.parent().unwrap().display(),
            hop.display()
        );
        let terminal = sandbox
            .execute(&ToolCallRecord::new(
                "terminal",
                "call_synthetic_terminal",
                serde_json::to_string(&json!({ "command": command })).unwrap(),
            ))
            .expect("terminal executes");
        assert_eq!(sha256_hex(terminal.content().as_bytes()), TERMINAL_RESULT_DIGEST);
        assert_eq!(fs::read(&hop).expect("hop.txt written"), HOP_CONTENT.as_bytes());
        assert_eq!(sha256_hex(&fs::read(&hop).expect("hop.txt readable")), HOP_DIGEST);
        let read = sandbox
            .execute(&ToolCallRecord::new(
                "read_file",
                "call_synthetic_read_file",
                serde_json::to_string(&json!({ "path": hop.to_string_lossy() })).unwrap(),
            ))
            .expect("read_file executes");
        assert_eq!(sha256_hex(read.content().as_bytes()), READ_RESULT_DIGEST);
        let _ = fs::remove_dir_all(&root);
    }
}
