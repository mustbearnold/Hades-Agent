//! `hades-dev replay-local-provider-timing` — Rust port of
//! `scripts/replay_local_provider_timing.py` (HAD-156).
//!
//! Replays incremental provider deltas and Ctrl+C cancellation through a
//! direct PTY: the delayed loopback server writes a first delta, HOLDS
//! until release, then writes the second delta + finish + DONE. Two cases:
//! delayed-delta-order (both deltas render in order, clean exit) and
//! interrupt-before-completion (Ctrl+C between deltas cancels the socket;
//! the second delta must never render, then a second Ctrl+C exits).

use std::fs;
use std::io::{Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use hades_dev::pty::read_available;
use hades_dev::replay::{
    ExitStatus, ReplayChild, marker_present, spawn_with_env, try_wait, wait_for, wait_for_exit,
    wait_for_rendered,
};
use serde_json::{Value, json};

const COLUMNS: u16 = 120;
const ROWS: u16 = 40;
const FIRST_DELTA: &str = "HADES_DELAY_FIRST";
const SECOND_DELTA: &str = "HADES_DELAY_SECOND";

struct DelayedState {
    request_seen: AtomicBool,
    first_sent: AtomicBool,
    release_second: AtomicBool,
    handler_done: AtomicBool,
    connection_closed: AtomicBool,
    shutdown: AtomicBool,
    records: std::sync::Mutex<Vec<RequestRecord>>,
    writes: std::sync::Mutex<Vec<Value>>,
}

#[derive(Clone)]
struct RequestRecord {
    path: String,
    content_type: String,
    authorization_present: bool,
    body: Value,
}

struct DelayedProvider {
    port: u16,
    state: Arc<DelayedState>,
    handle: Option<std::thread::JoinHandle<()>>,
}

impl DelayedProvider {
    fn start() -> std::io::Result<Self> {
        let listener = TcpListener::bind(("127.0.0.1", 0))?;
        let port = listener.local_addr()?.port();
        let state = Arc::new(DelayedState {
            request_seen: AtomicBool::new(false),
            first_sent: AtomicBool::new(false),
            release_second: AtomicBool::new(false),
            handler_done: AtomicBool::new(false),
            connection_closed: AtomicBool::new(false),
            shutdown: AtomicBool::new(false),
            records: std::sync::Mutex::new(Vec::new()),
            writes: std::sync::Mutex::new(Vec::new()),
        });
        let thread_state = Arc::clone(&state);
        let handle = std::thread::spawn(move || serve(listener, thread_state));
        Ok(Self { port, state, handle: Some(handle) })
    }

    fn environment(&self) -> Vec<(&'static str, String)> {
        vec![
            ("HADES_PROVIDER_BASE_URL", format!("http://127.0.0.1:{}/v1", self.port)),
            ("HADES_MODEL", "palette-model".to_string()),
            ("HADES_PROVIDER_API_KEY", String::new()),
        ]
    }

    fn finish(&mut self) {
        self.state.release_second.store(true, Ordering::SeqCst);
        self.state.shutdown.store(true, Ordering::SeqCst);
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

fn parse_head(buf: &[u8]) -> Result<(usize, String, String, bool, usize), String> {
    let text = String::from_utf8_lossy(buf);
    let mut path = String::new();
    let mut content_type = String::new();
    let mut authorization_present = false;
    let mut content_length = 0usize;
    for line in text.split('\n') {
        let line = line.strip_suffix('\r').unwrap_or(line);
        if line.is_empty() {
            continue;
        }
        if path.is_empty() {
            let mut parts = line.split_whitespace();
            let _method = parts.next();
            if let Some(part) = parts.next() {
                path = part.to_string();
            }
            continue;
        }
        if let Some((key, value)) = line.split_once(':') {
            match key.trim().to_ascii_lowercase().as_str() {
                "content-length" => content_length = value.trim().parse().unwrap_or(0),
                "content-type" => content_type = value.trim().to_string(),
                "authorization" => authorization_present = true,
                _ => {}
            }
        }
    }
    let header_end = buf
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or_else(|| "missing header boundary".to_owned())?;
    Ok((header_end, path, content_type, authorization_present, content_length))
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
    let (header_end, path, content_type, authorization_present, content_length) = head;
    let mut body_bytes: Vec<u8> = buf[header_end + 4..].to_vec();
    while body_bytes.len() < content_length {
        let count =
            stream.read(&mut tmp).map_err(|error| format!("request body read failed: {error}"))?;
        if count == 0 {
            break;
        }
        body_bytes.extend_from_slice(&tmp[..count]);
    }
    body_bytes.truncate(content_length);
    let body = serde_json::from_slice(&body_bytes).unwrap_or(Value::Null);
    Ok(RequestRecord { path, content_type, authorization_present, body })
}

fn write_chunk(
    stream: &mut TcpStream,
    state: &DelayedState,
    index: usize,
    marker: &str,
    payload: &[u8],
) -> bool {
    let sent = stream.write_all(payload).is_ok() && stream.flush().is_ok();
    if !sent {
        // Mirror the Python handler: a failed write surfaces as the
        // connection-closed record (index 99), not the write itself.
        state.writes.lock().unwrap().push(json!({
            "index": 99,
            "marker": "connection-closed",
            "sent": false,
            "error": "BrokenPipeError",
        }));
        return false;
    }
    state.writes.lock().unwrap().push(json!({
        "index": index,
        "marker": marker,
        "sent": true,
    }));
    true
}

fn handle_connection(mut stream: TcpStream, state: Arc<DelayedState>) {
    let _ = stream.set_nodelay(true);
    let record = match read_request(&mut stream) {
        Ok(record) => record,
        Err(_) => return,
    };
    state.records.lock().unwrap().push(record);
    state.request_seen.store(true, Ordering::SeqCst);

    let head = b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\nConnection: close\r\n\r\n";
    if stream.write_all(head).is_err() {
        state.connection_closed.store(true, Ordering::SeqCst);
        state.writes.lock().unwrap().push(json!({
            "index": 99,
            "marker": "connection-closed",
            "sent": false,
            "error": "write head failed",
        }));
        state.handler_done.store(true, Ordering::SeqCst);
        return;
    }
    write_chunk(
        &mut stream,
        &state,
        0,
        "role",
        b"data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n",
    );
    let first =
        format!("data: {{\"choices\":[{{\"delta\":{{\"content\":\"{FIRST_DELTA}\"}}}}]}}\n\n");
    write_chunk(&mut stream, &state, 1, FIRST_DELTA, first.as_bytes());
    state.first_sent.store(true, Ordering::SeqCst);

    // Hold the second delta until release (bounded like the Python 5s).
    let deadline = Instant::now() + Duration::from_secs(5);
    while !state.release_second.load(Ordering::SeqCst) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(10));
    }

    let second =
        format!("data: {{\"choices\":[{{\"delta\":{{\"content\":\"{SECOND_DELTA}\"}}}}]}}\n\n");
    let ok = write_chunk(&mut stream, &state, 2, SECOND_DELTA, second.as_bytes())
        && write_chunk(
            &mut stream,
            &state,
            3,
            "finish",
            b"data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\n",
        )
        && write_chunk(&mut stream, &state, 4, "DONE", b"data: [DONE]\n\n");
    if !ok {
        state.connection_closed.store(true, Ordering::SeqCst);
    }
    let _ = stream.shutdown(Shutdown::Both);
    state.handler_done.store(true, Ordering::SeqCst);
}

fn serve(listener: TcpListener, state: Arc<DelayedState>) {
    let _ = listener.set_nonblocking(true);
    loop {
        if state.shutdown.load(Ordering::SeqCst) {
            break;
        }
        match listener.accept() {
            Ok((stream, _)) => {
                let thread_state = Arc::clone(&state);
                std::thread::spawn(move || handle_connection(stream, thread_state));
            }
            Err(_) => std::thread::sleep(Duration::from_millis(10)),
        }
    }
}

fn spawn_tui(binary: &Path, base_url: &str) -> Result<ReplayChild, String> {
    let home = std::env::temp_dir().join(format!("hades-timing-{}", std::process::id()));
    fs::create_dir_all(&home).map_err(|error| error.to_string())?;
    let extra: [(&str, &str); 4] = [
        ("HADES_PROVIDER_BASE_URL", base_url),
        ("HADES_MODEL", "palette-model"),
        ("HOME", home.to_str().ok_or_else(|| "non-utf8 home".to_owned())?),
        ("HERMES_HOME", home.to_str().ok_or_else(|| "non-utf8 home".to_owned())?),
    ];
    let child = spawn_with_env(binary, &[], &extra, &["HADES_PROVIDER_API_KEY"])
        .map_err(|error| error.to_string())?;
    Ok(child)
}

fn assert_request_boundary(record: &RequestRecord) -> Result<(), String> {
    let body = &record.body;
    if record.path != "/v1/chat/completions" || record.content_type != "application/json" {
        return Err("request boundary was not preserved".to_owned());
    }
    if record.authorization_present {
        return Err("unexpected authorization crossed the sanitized replay boundary".to_owned());
    }
    let keys = body
        .as_object()
        .map(|map| {
            let mut keys: Vec<&str> = map.keys().map(String::as_str).collect();
            keys.sort();
            keys
        })
        .unwrap_or_default();
    if keys != ["max_tokens", "messages", "model", "stream", "stream_options", "tools"] {
        return Err(format!("unexpected body keys: {keys:?}"));
    }
    if body["model"] != "palette-model" || body["stream"] != true {
        return Err("model/stream markers were not preserved".to_owned());
    }
    let roles: Vec<&str> = body["messages"]
        .as_array()
        .map(|messages| {
            messages
                .iter()
                .filter_map(|message| message.get("role").and_then(Value::as_str))
                .collect()
        })
        .unwrap_or_default();
    if roles != ["system", "user"] {
        return Err("message role boundary was not preserved".to_owned());
    }
    Ok(())
}

fn run_case(binary: &Path, interrupt: bool, timeout: Duration) -> Result<Value, String> {
    let case = if interrupt { "interrupt-before-completion" } else { "delayed-delta-order" };
    let mut server = DelayedProvider::start().map_err(|error| error.to_string())?;
    let base_url = format!("http://127.0.0.1:{}/v1", server.port);
    let mut child = spawn_tui(binary, &base_url)?;
    let mut output = Vec::new();
    let mut reaped = false;

    let result = (|| -> Result<Value, String> {
        wait_for(
            &child.child,
            &mut output,
            &format!("{case}: startup"),
            |text| marker_present(text, "Hades Agent") && marker_present(text, "ready"),
            timeout,
        )?;
        hades_dev::replay::send(&child.child.master, b"stream timing probe\r")
            .map_err(|error| error.to_string())?;
        wait_for(
            &child.child,
            &mut output,
            &format!("{case}: request"),
            |_| server.state.request_seen.load(Ordering::SeqCst),
            timeout,
        )?;
        wait_for(
            &child.child,
            &mut output,
            &format!("{case}: first-write"),
            |_| server.state.first_sent.load(Ordering::SeqCst),
            timeout,
        )?;
        wait_for_rendered(
            &child.child,
            &mut output,
            &format!("{case}: first-delta"),
            |rendered| marker_present(rendered, FIRST_DELTA),
            timeout,
        )?;

        if interrupt {
            hades_dev::replay::send(&child.child.master, b"\x03")
                .map_err(|error| error.to_string())?;
            wait_for_rendered(
                &child.child,
                &mut output,
                &format!("{case}: interrupt"),
                |rendered| marker_present(rendered, "interrupted"),
                timeout,
            )?;
            std::thread::sleep(Duration::from_millis(100));
            server.state.release_second.store(true, Ordering::SeqCst);
            wait_for(
                &child.child,
                &mut output,
                &format!("{case}: connection-close"),
                |_| server.state.handler_done.load(Ordering::SeqCst),
                timeout,
            )?;
            let text = rendered_text(&output);
            if marker_present(&text, SECOND_DELTA) {
                return Err(format!(
                    "{case}: late-delta: the second provider delta rendered after Ctrl+C"
                ));
            }
            if !server.state.connection_closed.load(Ordering::SeqCst) {
                return Err(format!(
                    "{case}: connection-close: provider server did not observe the cancelled socket"
                ));
            }
            hades_dev::replay::send(&child.child.master, b"\x03")
                .map_err(|error| error.to_string())?;
        } else {
            server.state.release_second.store(true, Ordering::SeqCst);
            wait_for_rendered(
                &child.child,
                &mut output,
                &format!("{case}: second-delta"),
                |rendered| marker_present(rendered, SECOND_DELTA),
                timeout,
            )?;
            wait_for_rendered(
                &child.child,
                &mut output,
                &format!("{case}: ready"),
                |rendered| marker_present(rendered, "ready"),
                timeout,
            )?;
            hades_dev::replay::send(&child.child.master, b"\x03")
                .map_err(|error| error.to_string())?;
        }

        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 0 }) {
            return Err(format!("{case}: unexpected exit status: {exit_status:?}"));
        }
        if !find_sequence(output.as_slice(), b"\x1b[?1049l") {
            return Err(format!("{case}: cleanup: alternate screen was not restored"));
        }

        let records = server.state.records.lock().unwrap().clone();
        if records.len() != 1 {
            return Err(format!("{case}: request: expected one request, got {}", records.len()));
        }
        let record = &records[0];
        assert_request_boundary(record)?;
        let writes = server.state.writes.lock().unwrap().clone();
        let second_delta_visible = !interrupt;
        let mut input = vec![
            json!({"kind": "text", "value": "sanitized prompt"}),
            json!({"kind": "key", "value": "Enter"}),
            json!({
                "kind": "key",
                "value": "Ctrl+C",
                "meaning": if interrupt {
                    "interrupt before delayed second delta"
                } else {
                    "bounded cleanup after completion"
                },
            }),
        ];
        if interrupt {
            input.push(json!({
                "kind": "key",
                "value": "Ctrl+C",
                "meaning": "exit from ready/interrupted state",
            }));
        }
        Ok(json!({
            "id": case,
            "status": "passed",
            "input": input,
            "request": {
                "method": "POST",
                "path": record.path,
                "content_type": record.content_type,
                "authorization_present": false,
                "body_keys": record.body.as_object().map(|map| {
                    let mut keys: Vec<&str> = map.keys().map(String::as_str).collect();
                    keys.sort();
                    keys
                }).unwrap_or_default(),
                "model": record.body["model"],
                "stream": record.body["stream"],
                "message_roles": record.body["messages"].as_array().map(|messages| {
                    messages.iter().filter_map(|m| m.get("role").and_then(Value::as_str)).collect::<Vec<_>>()
                }).unwrap_or_default(),
                "tools_present": record.body["tools"].as_array().is_some_and(|tools| !tools.is_empty()),
            },
            "writes": writes,
            "visible_state": {
                "first_delta_visible": true,
                "second_delta_visible": second_delta_visible,
                "partial_response_preserved": interrupt,
                "interrupted_surface_observed": interrupt,
                "returned_to_ready": true,
                "provider_connection_closed": if interrupt {
                    server.state.connection_closed.load(Ordering::SeqCst)
                } else {
                    false
                },
                "clean_exit": true,
            },
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child.child);
    }
    server.finish();
    let _ = fs::remove_dir_all(
        &std::env::temp_dir().join(format!("hades-timing-{}", std::process::id())),
    );
    result
}

fn rendered_text(output: &[u8]) -> String {
    let mut screen = hades_dev::screen::Screen::new(COLUMNS as usize, ROWS as usize);
    screen.feed(output);
    screen.lines().join("\n")
}

fn find_sequence(haystack: &[u8], needle: &[u8]) -> bool {
    haystack.windows(needle.len()).any(|window| window == needle)
}

fn write_report(report: &Value, path: Option<&Path>, status: u8) -> ExitCode {
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
    if status == 0 { ExitCode::SUCCESS } else { ExitCode::from(status) }
}

fn main() -> ExitCode {
    let mut args = std::env::args().skip(1);
    let mut binary = PathBuf::from("target/debug/hades");
    let mut contract_path =
        PathBuf::from("tests/fixtures/parity/OBS-0053-hades-stream-timing.json");
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
        "command": "replay-local-provider-timing",
        "binary": binary.display().to_string(),
        "contract": contract_path.display().to_string(),
        "dimensions": {"columns": COLUMNS, "rows": ROWS, "emulator": "direct PTY"},
        "cases": [],
        "passed": false,
    });
    if !binary.is_file() {
        report["failure"] = json!({"case": "report", "step": "binary", "message": format!("binary not found: {}", binary.display())});
        return write_report(&report, report_path.as_deref(), 1);
    }

    let mut cases = Vec::new();
    for interrupt in [false, true] {
        match run_case(&binary, interrupt, timeout) {
            Ok(case) => cases.push(case),
            Err(error) => {
                report["failure"] = json!({"case": "report", "step": "runtime", "message": error});
                return write_report(&report, report_path.as_deref(), 1);
            }
        }
    }
    report["cases"] = json!(cases);
    report["passed"] = json!(true);
    write_report(&report, report_path.as_deref(), 0)
}
