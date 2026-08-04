//! `hades-dev replay-configured-surfaces` — Rust port of
//! `scripts/replay_configured_surfaces.py` (HAD-151).
//!
//! Replays the configured Hades journey through its primary interaction
//! surfaces: the `hades setup --local` sidecar, slash completion, the
//! model picker and sessions overlays, same-process history up/down
//! navigation, persisted-history recall in a fresh process, and the
//! Ctrl+V clipboard path with a synthetic xclip provider. Four provider
//! requests total, every one recorded by the loopback VerticalSlice-style
//! SSE server. The server machinery is the Rust port of the Python
//! `VerticalSliceServer` (first deltas flush immediately; here
//! `release_response` is set up front, mirroring the Python replay, so the
//! final answer streams without holding).

use std::fs;
use std::io::{Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use hades_dev::replay::{
    ExitStatus, ReplayChild, RetainedSlave, TerminalFlags, marker_present, spawn_with_env,
    terminal_flags, wait_for, wait_for_exit, wait_for_rendered,
};
use serde_json::{Value, json};

/// Environment sanitization, mirroring `main()` in the Python replay: the
/// three provider vars plus the display/remote-session vars the Python
/// pops from the environment before spawning any child.
const STRIP_ENV: [&str; 11] = [
    "HADES_PROVIDER_BASE_URL",
    "HADES_MODEL",
    "HADES_PROVIDER_API_KEY",
    "WAYLAND_DISPLAY",
    "WSL_INTEROP",
    "WSL_DISTRO_NAME",
    "SSH_TTY",
    "SSH_CONNECTION",
    "SSH_CLIENT",
    "TMUX",
    "STY",
];

// ---------------------------------------------------------------------------
// Loopback SSE server (Rust port of the Python `VerticalSliceServer`).
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Replay steps.
// ---------------------------------------------------------------------------

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .expect("hades-dev crate is two levels under the repo root")
        .to_path_buf()
}

/// Write the synthetic xclip provider, like `make_fake_clipboard`: a shell
/// script that ignores its arguments and prints the clipboard payload.
fn make_fake_clipboard(directory: &Path) -> Result<(), String> {
    fs::create_dir_all(directory).map_err(|error| error.to_string())?;
    let command = directory.join("xclip");
    fs::write(&command, "#!/bin/sh\nprintf '%s\\n' 'configured clipboard payload'\n")
        .map_err(|error| error.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions =
            fs::metadata(&command).map_err(|error| error.to_string())?.permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&command, permissions).map_err(|error| error.to_string())?;
    }
    Ok(())
}

/// The setup step: run `hades setup --local <loopback-url> vertical-model`
/// and assert the sanitized sidecar contract, like `run_setup`.
fn run_setup(binary: &Path, home: &Path, endpoint: &str, fake_path: &str) -> Result<Value, String> {
    let home_str = home.to_str().ok_or_else(|| "non-UTF-8 home path".to_string())?;
    let output = Command::new(binary)
        .args(["setup", "--local", endpoint, "vertical-model"])
        .current_dir(repo_root())
        .env("HERMES_HOME", home_str)
        .env("PATH", fake_path)
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

/// Spawn the TUI against the persisted sidecar with the fake-bin PATH,
/// like `spawn_tui` (ambient HOME, HERMES_HOME pointed at the replay home).
fn spawn_tui(binary: &Path, home: &Path, fake_path: &str) -> Result<ReplayChild, String> {
    let real_home = std::env::var("HOME").unwrap_or_default();
    let home_str = home.to_str().ok_or_else(|| "non-UTF-8 home path".to_string())?;
    spawn_with_env(
        binary,
        &[],
        &[("HOME", real_home.as_str()), ("HERMES_HOME", home_str), ("PATH", fake_path)],
        &STRIP_ENV,
    )
    .map_err(|error| error.to_string())
}

/// Wait until `count` requests have been recorded AND the streamed answer
/// rendered and the server completed the response, like `wait_for_request`.
fn wait_for_request(
    child: &hades_dev::pty::PtyChild,
    output: &mut Vec<u8>,
    state: &ServerState,
    count: usize,
    timeout: Duration,
) -> Result<(), String> {
    wait_for(
        child,
        output,
        &format!("request-{count}"),
        |_text| state.records.lock().unwrap().len() >= count,
        timeout,
    )?;
    wait_for_rendered(
        child,
        output,
        &format!("response-{count}"),
        |text| marker_present(text, "Final streamed answer."),
        timeout,
    )?;
    let deadline = Instant::now() + timeout;
    while !state.response_complete.load(Ordering::SeqCst) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(10));
    }
    if !state.response_complete.load(Ordering::SeqCst) {
        return Err(format!("response-{count}: local response did not complete"));
    }
    // Let the event loop consume the completion boundary before the next key.
    std::thread::sleep(Duration::from_millis(150));
    Ok(())
}

/// Assert exit 0, alternate-screen leave, and canonical/echo restoration,
/// like `assert_terminal_cleanup`.
fn assert_terminal_cleanup(
    raw: &[u8],
    slave: &RetainedSlave,
    status: rustix::process::WaitStatus,
    step: &str,
) -> Result<Value, String> {
    let exit_status = ExitStatus::describe(status);
    if exit_status != (ExitStatus::Exit { code: 0 }) {
        return Err(format!("{step}: unexpected exit status: {exit_status:?}"));
    }
    let flags = stable_terminal_flags(slave)?;
    if !find_sequence(raw, b"\x1b[?1049l") || !flags.canonical || !flags.echo {
        return Err(format!("{step}: terminal restoration failed: {flags:?}"));
    }
    Ok(json!({
        "exit": exit_status.as_json(),
        "alternate_screen_left": true,
        "terminal_restored": {"canonical": flags.canonical, "echo": flags.echo},
    }))
}

/// First TUI process: slash completion, model picker and sessions overlays
/// (none may open a provider request), two submitted prompts, same-process
/// history up/down without submission, Ctrl+C exit, persisted history file.
fn run_first_process(
    binary: &Path,
    home: &Path,
    state: &ServerState,
    fake_path: &str,
    timeout: Duration,
) -> Result<Value, String> {
    let mut child = spawn_tui(binary, home, fake_path)?;
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
        let slave = RetainedSlave::retain(&slave_path).map_err(|error| error.to_string())?;

        hades_dev::replay::send(&child.child.master, b"/he").map_err(|error| error.to_string())?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "slash-completion",
            |text| marker_present(text, "completions") && marker_present(text, "/help"),
            timeout,
        )?;
        if !state.records.lock().unwrap().is_empty() {
            return Err("slash-completion: completion opened a provider request".to_string());
        }
        hades_dev::replay::send(&child.child.master, b"\t").map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(150));
        hades_dev::replay::send(&child.child.master, b"\x1b").map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(150));
        hades_dev::replay::send(&child.child.master, b"/model")
            .map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(150));
        hades_dev::replay::send(&child.child.master, b"\r").map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(150));
        hades_dev::replay::send(&child.child.master, b"\r").map_err(|error| error.to_string())?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "model-overlay",
            |text| {
                marker_present(text, "Model picker")
                    && marker_present(text, "Select provider (step 1/2)")
            },
            timeout,
        )?;
        if !state.records.lock().unwrap().is_empty() {
            return Err("model-overlay: model overlay opened a provider request".to_string());
        }
        hades_dev::replay::send(&child.child.master, b"\x1b").map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(150));

        hades_dev::replay::send(&child.child.master, b"\x18").map_err(|error| error.to_string())?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "sessions-overlay",
            |text| marker_present(text, "Sessions") && marker_present(text, "current session"),
            timeout,
        )?;
        if !state.records.lock().unwrap().is_empty() {
            return Err("sessions-overlay: sessions overlay opened a provider request".to_string());
        }
        hades_dev::replay::send(&child.child.master, b"\x1b").map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(150));

        hades_dev::replay::send(&child.child.master, b"surface prompt one")
            .map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(150));
        hades_dev::replay::send(&child.child.master, b"\r").map_err(|error| error.to_string())?;
        wait_for_request(&child.child, &mut output, state, 1, timeout)?;
        hades_dev::replay::send(&child.child.master, b"surface prompt two")
            .map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(150));
        hades_dev::replay::send(&child.child.master, b"\r").map_err(|error| error.to_string())?;
        wait_for_request(&child.child, &mut output, state, 2, timeout)?;

        hades_dev::replay::send(&child.child.master, b"\x1b[A")
            .map_err(|error| error.to_string())?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "history-newest",
            |text| marker_present(text, "surface prompt two"),
            timeout,
        )?;
        hades_dev::replay::send(&child.child.master, b"\x1b[A")
            .map_err(|error| error.to_string())?;
        wait_for_rendered(
            &child.child,
            &mut output,
            "history-previous",
            |text| marker_present(text, "surface prompt one"),
            timeout,
        )?;
        hades_dev::replay::send(&child.child.master, b"\x1b[B")
            .map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(150));
        if state.records.lock().unwrap().len() != 2 {
            let count = state.records.lock().unwrap().len();
            return Err(format!(
                "history-navigation: history navigation submitted a request (count={count})"
            ));
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let raw: &[u8] = &output;
        let cleanup = assert_terminal_cleanup(raw, &slave, status, "first-cleanup")?;

        let history_path = home.join(".hermes_history");
        let history = std::fs::read_to_string(&history_path)
            .map_err(|_| "history-persistence: history file was not written".to_string())?;
        if !history.contains("surface prompt one") || !history.contains("surface prompt two") {
            return Err("history-persistence: submitted prompts were not persisted".to_string());
        }
        Ok(json!({
            "startup_ready": true,
            "slash_completion": {"typed_prefix": "/he", "visible": true, "applied_without_submit": true},
            "overlays": {
                "model_picker": {"opened": true, "closed_with_escape": true},
                "sessions": {"opened": true, "closed_with_escape": true},
            },
            "history": {
                "same_process_up_down": true,
                "submitted_prompt_count": 2,
                "persisted": true,
            },
            "cleanup": cleanup,
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child.child);
    }
    let _ = std::fs::remove_dir_all(&child.history_home);
    result
}

/// Second TUI process: Up restores the newest persisted prompt, a modified
/// resubmission produces exactly one more provider request.
fn run_history_restart(
    binary: &Path,
    home: &Path,
    state: &ServerState,
    fake_path: &str,
    timeout: Duration,
) -> Result<Value, String> {
    let mut child = spawn_tui(binary, home, fake_path)?;
    let mut output = Vec::new();
    let mut reaped = false;
    let slave_path = child.slave_path.clone();

    let result = (|| -> Result<Value, String> {
        wait_for(
            &child.child,
            &mut output,
            "history-restart-startup",
            |text| text.contains("Hades Agent") && marker_present(text, "ready"),
            timeout,
        )?;
        let slave = RetainedSlave::retain(&slave_path).map_err(|error| error.to_string())?;

        let before = state.records.lock().unwrap().len();
        hades_dev::replay::send(&child.child.master, b"\x1b[A")
            .map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(200));
        if state.records.lock().unwrap().len() != before {
            return Err(
                "history-restart-newest: history navigation opened a provider request".to_string()
            );
        }
        hades_dev::replay::send(&child.child.master, b"!").map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(100));
        hades_dev::replay::send(&child.child.master, b"\r").map_err(|error| error.to_string())?;
        let expected = before + 1;
        wait_for_request(&child.child, &mut output, state, expected, timeout)?;
        let recalled_prompt = {
            let records = state.records.lock().unwrap();
            records[expected - 1].body["messages"]
                .as_array()
                .and_then(|messages| messages.last())
                .and_then(|message| message["content"].as_str())
                .unwrap_or_default()
                .to_owned()
        };
        if recalled_prompt != "surface prompt two!" {
            return Err("history-restart-newest: Up did not restore the newest persisted prompt"
                .to_string());
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let raw: &[u8] = &output;
        let cleanup = assert_terminal_cleanup(raw, &slave, status, "history-restart-cleanup")?;
        Ok(json!({
            "history_available_after_restart": true,
            "history_recall_verified_by_request": true,
            "provider_requests": 1,
            "cleanup": cleanup,
        }))
    })();

    if !reaped {
        hades_dev::pty::stop(&mut child.child.child);
    }
    let _ = std::fs::remove_dir_all(&child.history_home);
    result
}

/// Third TUI process: Ctrl+V inserts the synthetic clipboard payload
/// without submitting, Enter submits it as the fourth provider request.
fn run_clipboard_process(
    binary: &Path,
    home: &Path,
    state: &ServerState,
    fake_path: &str,
    timeout: Duration,
) -> Result<Value, String> {
    let mut child = spawn_tui(binary, home, fake_path)?;
    let mut output = Vec::new();
    let mut reaped = false;
    let slave_path = child.slave_path.clone();

    let result = (|| -> Result<Value, String> {
        wait_for(
            &child.child,
            &mut output,
            "clipboard-startup",
            |text| text.contains("Hades Agent") && marker_present(text, "ready"),
            timeout,
        )?;
        let slave = RetainedSlave::retain(&slave_path).map_err(|error| error.to_string())?;

        hades_dev::replay::send(&child.child.master, b"\x16").map_err(|error| error.to_string())?;
        std::thread::sleep(Duration::from_millis(300));
        if state.records.lock().unwrap().len() != 3 {
            return Err("clipboard-insert: Ctrl+V submitted before Enter".to_string());
        }
        hades_dev::replay::send(&child.child.master, b"\r").map_err(|error| error.to_string())?;
        wait_for_request(&child.child, &mut output, state, 4, timeout)?;
        let prompt = {
            let records = state.records.lock().unwrap();
            records[3].body["messages"]
                .as_array()
                .and_then(|messages| messages.last())
                .and_then(|message| message["content"].as_str())
                .unwrap_or_default()
                .to_owned()
        };
        if prompt != "configured clipboard payload" {
            return Err(
                "clipboard-request: clipboard text was not delivered to the request".to_string()
            );
        }

        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let raw: &[u8] = &output;
        let cleanup = assert_terminal_cleanup(raw, &slave, status, "clipboard-cleanup")?;
        Ok(json!({
            "clipboard": {
                "provider": "synthetic xclip",
                "inserted_without_submit": true,
                "submitted_on_enter": true,
                "request_prompt_marker": "configured clipboard payload",
            },
            "cleanup": cleanup,
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

/// Last user message content of a recorded request body, like the Python
/// `record["body"]["messages"][-1]["content"]` access.
fn last_prompt_marker(body: &Value) -> Value {
    body["messages"]
        .as_array()
        .and_then(|messages| messages.last())
        .and_then(|message| message.get("content"))
        .cloned()
        .unwrap_or(Value::Null)
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
        "command": "replay-configured-surfaces",
        "binary": binary.to_string_lossy(),
        "dimensions": {"columns": 120, "rows": 40, "emulator": "direct PTY"},
        "steps": [],
        "passed": false,
    });
    let home =
        std::env::temp_dir().join(format!("hades-configured-surfaces-{}", std::process::id()));
    let _ = std::fs::create_dir_all(&home);
    let clipboard_bin = home.join("fake-bin");
    let mut status = 0u8;

    if !binary.is_file() {
        report["failure"] = json!({"message": format!("binary not found: {}", binary.display())});
        status = 1;
    } else {
        if let Err(error) = make_fake_clipboard(&clipboard_bin) {
            report["failure"] = json!({"message": error});
            let _ = std::fs::remove_dir_all(&home);
            return write_report(&report, report_path.as_deref(), 1);
        }
        let path_value = std::env::var("PATH").unwrap_or_default();
        let mut entries = vec![clipboard_bin.as_os_str().to_owned()];
        entries.extend(std::env::split_paths(&path_value).map(std::ffi::OsString::from));
        let fake_path = match std::env::join_paths(entries) {
            Ok(path) => path.to_str().map(str::to_owned).unwrap_or_default(),
            Err(error) => {
                report["failure"] = json!({"message": format!("could not build PATH: {error}")});
                let _ = std::fs::remove_dir_all(&home);
                return write_report(&report, report_path.as_deref(), 1);
            }
        };
        let (port, state, server_thread) = match start_server() {
            Ok(server) => server,
            Err(error) => {
                report["failure"] = json!({"message": format!("loopback server failed: {error}")});
                let _ = std::fs::remove_dir_all(&home);
                return write_report(&report, report_path.as_deref(), 1);
            }
        };
        state.release_response.store(true, Ordering::SeqCst);
        let endpoint = format!("http://127.0.0.1:{port}/v1");
        let run = (|| -> Result<Vec<Value>, String> {
            let steps = vec![
                run_setup(&binary, &home, &endpoint, &fake_path)?,
                run_first_process(&binary, &home, &state, &fake_path, timeout)?,
                run_history_restart(&binary, &home, &state, &fake_path, timeout)?,
                run_clipboard_process(&binary, &home, &state, &fake_path, timeout)?,
            ];
            if home.join("config.yaml").exists() {
                return Err(
                    "config-boundary: Hermes config.yaml was created or changed".to_string()
                );
            }
            let records = state.records.lock().unwrap();
            if records.len() != 4 {
                return Err(format!(
                    "request-count: expected four requests, got {}",
                    records.len()
                ));
            }
            for record in records.iter() {
                if record.path != "/v1/chat/completions"
                    || record.content_type != "application/json"
                    || record.authorization_present
                {
                    return Err("request-boundary: a request crossed the sanitized local boundary"
                        .to_string());
                }
            }
            let summary = json!({
                "count": records.len(),
                "paths": records.iter().map(|record| record.path.clone()).collect::<Vec<_>>(),
                "models": records.iter().map(|record| record.body["model"].clone()).collect::<Vec<_>>(),
                "prompt_markers": records.iter().map(|record| last_prompt_marker(&record.body)).collect::<Vec<_>>(),
                "stream": records.iter().all(|record| record.body["stream"] == true),
            });
            drop(records);
            report["request_summary"] = summary;
            Ok(steps)
        })();
        match run {
            Ok(steps) => {
                report["steps"] = json!(steps);
                report["passed"] = json!(true);
            }
            Err(error) => {
                report["failure"] = json!({"message": error});
                status = 1;
            }
        }
        state.release_response.store(true, Ordering::SeqCst);
        state.shutdown.store(true, Ordering::SeqCst);
        let _ = server_thread.join();
    }

    let _ = std::fs::remove_dir_all(&home);
    let _ = std::fs::remove_dir_all(
        std::env::temp_dir().join(format!("hades-pty-history-{}", std::process::id())),
    );
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
        assert!(state.records.lock().unwrap().len() == 1);
        response
    }

    #[test]
    fn server_records_request_and_streams_full_sse() {
        let (port, state, handle) = start_server().expect("start");
        // The configured-surfaces replay releases responses up front.
        state.release_response.store(true, Ordering::SeqCst);
        let body = br#"{"model":"vertical-model","stream":true,"messages":[{"role":"system"},{"role":"user","content":"surface prompt one"}]}"#;
        let response = post_request(port, body, &state);
        let text = String::from_utf8_lossy(&response).to_string();
        assert!(text.contains("HTTP/1.0 200 OK"), "{text}");
        assert!(text.contains("First streamed delta."), "{text}");
        assert!(text.contains("Final streamed answer."), "{text}");
        assert!(text.contains("[DONE]"), "{text}");
        assert!(state.request_seen.load(Ordering::SeqCst));
        assert!(state.response_complete.load(Ordering::SeqCst));
        let record = &state.records.lock().unwrap()[0];
        assert_eq!(record.path, "/v1/chat/completions");
        assert_eq!(record.content_type, "application/json");
        assert!(!record.authorization_present);
        assert_eq!(record.body["model"], "vertical-model");
        assert_eq!(last_prompt_marker(&record.body), "surface prompt one");
        state.shutdown.store(true, Ordering::SeqCst);
        let _ = handle.join();
    }

    #[test]
    fn fake_clipboard_script_emits_payload() {
        let dir = std::env::temp_dir().join(format!("hades-cs-xclip-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        make_fake_clipboard(&dir).expect("write");
        let script = fs::read_to_string(dir.join("xclip")).expect("read");
        assert!(script.contains("configured clipboard payload"));
        assert!(script.starts_with("#!/bin/sh\n"));
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = fs::metadata(dir.join("xclip")).expect("meta").permissions().mode();
            assert_ne!(mode & 0o111, 0, "xclip must be executable");
        }
        let _ = fs::remove_dir_all(&dir);
    }
}
