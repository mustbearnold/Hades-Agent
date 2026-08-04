//! `hades-dev replay-osc52-clipboard` — Rust port of
//! `scripts/replay_osc52_clipboard.py` (HAD-158).
//!
//! Replays the bare-SSH OSC52-first clipboard contract (OBS-0025 and the
//! boundary/ST/multiplexer families) in a direct 120x40 PTY: Ctrl+V emits
//! the OSC52 query (`ESC]52;c;?`) then a DA1 barrier query; a usable OSC52
//! response (BEL- or ST-terminated, optionally wrapped by TMUX/STY)
//! wins before the native xclip provider; malformed/empty responses and
//! DA1-acknowledged timeouts fall back to xclip.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{Duration, Instant};

use hades_dev::pty::read_available;
use hades_dev::replay::{
    ExitStatus, ReplayChild, marker_present, spawn_with_env, try_wait, wait_for, wait_for_exit,
    wait_for_rendered,
};
use hades_dev::screen::Screen;
use serde_json::{Value, json};

const COLUMNS: u16 = 120;
const ROWS: u16 = 40;
const OSC52_QUERY: &[u8] = b"\x1b]52;c;?\x07";
const DA1_QUERY: &[u8] = b"\x1b[c";
const DA1_RESPONSE: &[u8] = b"\x1b[?62c";
const STARTUP_MARKERS: [&str; 4] =
    ["Hades Agent", "Underworld", "Available Tools", "Available Skills"];

fn rendered_text(output: &[u8]) -> String {
    let mut screen = Screen::new(COLUMNS as usize, ROWS as usize);
    screen.feed(output);
    screen.lines().join("\n")
}

fn contains_marker(output: &[u8], marker: &str) -> bool {
    let text = rendered_text(output);
    let compact_text: String = text.split_whitespace().collect::<String>().to_lowercase();
    let compact_marker: String = marker.split_whitespace().collect::<String>().to_lowercase();
    text.contains(marker) || compact_text.contains(&compact_marker)
}

/// Write the synthetic xclip provider: records argv into the log file and
/// echoes the fixture payload to stdout.
fn create_xclip(provider_dir: &Path, log_path: &Path) -> Result<(), String> {
    fs::create_dir_all(provider_dir).map_err(|error| error.to_string())?;
    let script =
        "#!/bin/sh\nprintf '%s\\n' \"$*\" > \"$HADES_CLIPBOARD_LOG\"\ncat \"$HADES_CLIPBOARD_PAYLOAD\"\n"
            .to_string();
    let xclip = provider_dir.join("xclip");
    fs::write(&xclip, script).map_err(|error| error.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions =
            fs::metadata(&xclip).map_err(|error| error.to_string())?.permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&xclip, permissions).map_err(|error| error.to_string())?;
    }
    fs::write(log_path, []).map_err(|error| error.to_string())?;
    Ok(())
}

fn spawn_osc52(
    binary: &Path,
    home: &Path,
    provider_dir: &Path,
    payload_path: &Path,
    log_path: &Path,
    multiplexer_marker: Option<&str>,
) -> Result<ReplayChild, String> {
    let path_value = std::env::var("PATH").unwrap_or_default();
    let mut entries = vec![provider_dir.as_os_str().to_owned()];
    entries.extend(std::env::split_paths(&path_value).map(std::ffi::OsString::from));
    let provider_path =
        std::env::join_paths(entries).map_err(|error| format!("could not build PATH: {error}"))?;
    let provider_path =
        provider_path.to_str().ok_or_else(|| "non-utf8 provider path".to_owned())?.to_owned();
    let mut extra: Vec<(&str, String)> = vec![
        ("HOME", home.display().to_string()),
        ("HERMES_HOME", home.display().to_string()),
        ("HADES_PROVIDER_BASE_URL", "http://127.0.0.1:8765/v1".to_owned()),
        ("PATH", provider_path),
        ("HADES_CLIPBOARD_PAYLOAD", payload_path.display().to_string()),
        ("HADES_CLIPBOARD_LOG", log_path.display().to_string()),
        ("SSH_TTY", "/dev/pts/999".to_owned()),
    ];
    match multiplexer_marker {
        Some("TMUX") => extra.push(("TMUX", "/tmp/tmux-999/default,123,0".to_owned())),
        Some("STY") => extra.push(("STY", "1234.pts-0.host".to_owned())),
        _ => {}
    }
    let strip = [
        "SSH_CONNECTION",
        "SSH_CLIENT",
        "TMUX",
        "STY",
        "WAYLAND_DISPLAY",
        "WSL_INTEROP",
        "WSL_DISTRO_NAME",
    ];
    let extra_refs: Vec<(&str, &str)> =
        extra.iter().map(|(key, value)| (*key, value.as_str())).collect();
    spawn_with_env(binary, &[], &extra_refs, &strip).map_err(|error| error.to_string())
}

fn input_hex(event_value: &str) -> Result<Vec<u8>, String> {
    let compact: String = event_value.split_whitespace().collect();
    (0..compact.len())
        .step_by(2)
        .map(|index| {
            u8::from_str_radix(&compact[index..index + 2], 16)
                .map_err(|error| format!("invalid input bytes: {error}"))
        })
        .collect()
}

fn run_case(
    binary: &Path,
    case: &Value,
    timeout: Duration,
    ordinal: usize,
) -> Result<Value, String> {
    let case_id = case
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| "case has no id".to_owned())?
        .to_owned();
    let home =
        std::env::temp_dir().join(format!("had025-{case_id}-{ordinal}-{}", std::process::id()));
    let provider_dir = home.join("bin");
    let payload_path = home.join("clipboard.payload");
    let log_path = home.join("clipboard.args");
    fs::create_dir_all(&home).map_err(|error| error.to_string())?;
    fs::write(
        &payload_path,
        case.get("native_payload").and_then(Value::as_str).unwrap_or_default().as_bytes(),
    )
    .map_err(|error| error.to_string())?;
    create_xclip(&provider_dir, &log_path)?;
    let multiplexer_marker =
        case.get("multiplexer_marker").and_then(Value::as_str).map(str::to_owned);
    let wrapped_query = match case.get("wrapped_query_bytes_hex").and_then(Value::as_str) {
        Some(hex) => input_hex(hex)?,
        None => OSC52_QUERY.to_vec(),
    };

    let mut reaped = false;
    let result = (|| -> Result<Value, String> {
        let child = spawn_osc52(
            binary,
            &home,
            &provider_dir,
            &payload_path,
            &log_path,
            multiplexer_marker.as_deref(),
        )?;
        let mut output = Vec::new();

        wait_for(
            &child.child,
            &mut output,
            &format!("{case_id}: startup"),
            |text| STARTUP_MARKERS.iter().all(|marker| marker_present(text, marker)),
            timeout,
        )?;

        let draft = case.get("draft").and_then(Value::as_str).unwrap_or_default().to_owned();
        hades_dev::replay::send(&child.child.master, draft.as_bytes())
            .map_err(|error| error.to_string())?;
        wait_for_rendered(
            &child.child,
            &mut output,
            &format!("{case_id}: draft"),
            |rendered| marker_present(rendered, &draft),
            timeout,
        )?;
        let start = output.len();
        hades_dev::replay::send(&child.child.master, b"\x16").map_err(|error| error.to_string())?;
        let query_deadline = Instant::now() + timeout;
        let query_at = loop {
            output.extend_from_slice(&read_available(&child.child.master));
            if let Some(position) =
                find_subslice(&output[start..], &wrapped_query).map(|offset| start + offset)
            {
                break position;
            }
            if try_wait(&child.child)?.is_some() {
                return Err(format!("{case_id}: osc52-query: process exited before the query"));
            }
            if Instant::now() >= query_deadline {
                return Err(format!("{case_id}: osc52-query: timed out"));
            }
            std::thread::sleep(Duration::from_millis(20));
        };
        let da1_deadline = Instant::now() + timeout;
        let da1_at = loop {
            output.extend_from_slice(&read_available(&child.child.master));
            if let Some(position) =
                find_subslice(&output[query_at + wrapped_query.len()..], DA1_QUERY)
                    .map(|offset| query_at + wrapped_query.len() + offset)
            {
                break position;
            }
            if try_wait(&child.child)?.is_some() {
                return Err(format!("{case_id}: da1-query: process exited before the query"));
            }
            if Instant::now() >= da1_deadline {
                return Err(format!("{case_id}: da1-query: timed out"));
            }
            std::thread::sleep(Duration::from_millis(20));
        };

        let outcome = if case_id == "osc52-response" {
            let payload = case.get("osc52_payload").and_then(Value::as_str).unwrap_or_default();
            let response = base64_payload(payload);
            hades_dev::replay::send(&child.child.master, &response)
                .map_err(|error| error.to_string())?;
            hades_dev::replay::send(&child.child.master, DA1_RESPONSE)
                .map_err(|error| error.to_string())?;
            wait_for_rendered(
                &child.child,
                &mut output,
                &format!("{case_id}: remote-text"),
                |rendered| case_markers(case).iter().all(|marker| marker_present(rendered, marker)),
                timeout,
            )?;
            let provider_arguments = fs::read_to_string(&log_path).unwrap_or_default();
            if !provider_arguments.trim().is_empty() {
                return Err(format!(
                    "{case_id}: provider-order: native xclip ran after usable OSC52 text"
                ));
            }
            json!({
                "status": "passed",
                "path": "OSC52 response won before native provider",
                "osc52_query_bytes_hex": hex_bytes(OSC52_QUERY),
                "wrapped_query_bytes_hex": hex_bytes(&wrapped_query),
                "osc52_response_bytes_hex": hex_bytes(&response),
                "da1_query_bytes_hex": hex_bytes(DA1_QUERY),
                "da1_response_bytes_hex": hex_bytes(DA1_RESPONSE),
                "native_provider": "not invoked",
            })
        } else if let Some(response_hex) =
            case.get("osc52_response_bytes_hex").and_then(Value::as_str)
        {
            let response = input_hex(response_hex)?;
            hades_dev::replay::send(&child.child.master, &response)
                .map_err(|error| error.to_string())?;
            hades_dev::replay::send(&child.child.master, DA1_RESPONSE)
                .map_err(|error| error.to_string())?;
            let expected_outcome =
                case.get("expected_outcome").and_then(Value::as_str).unwrap_or("native-fallback");
            wait_for_rendered(
                &child.child,
                &mut output,
                &format!("{case_id}: response-outcome"),
                |rendered| case_markers(case).iter().all(|marker| marker_present(rendered, marker)),
                timeout,
            )?;
            let provider_arguments = fs::read_to_string(&log_path).unwrap_or_default();
            if expected_outcome == "osc52-response" {
                if !provider_arguments.trim().is_empty() {
                    return Err(format!(
                        "{case_id}: provider-order: native xclip ran after usable ST OSC52 text"
                    ));
                }
                json!({
                    "status": "passed",
                    "path": match multiplexer_marker.as_deref() {
                        Some(marker) => format!("{marker} passthrough OSC52 response won before native provider"),
                        None => "ST-terminated OSC52 response won before native provider".to_owned(),
                    },
                    "osc52_query_bytes_hex": hex_bytes(OSC52_QUERY),
                    "wrapped_query_bytes_hex": hex_bytes(&wrapped_query),
                    "osc52_response_bytes_hex": hex_bytes(&response),
                    "da1_query_bytes_hex": hex_bytes(DA1_QUERY),
                    "da1_response_bytes_hex": hex_bytes(DA1_RESPONSE),
                    "native_provider": "not invoked",
                })
            } else {
                let expected_arguments = "-selection clipboard -out";
                if provider_arguments.trim() != expected_arguments {
                    return Err(format!(
                        "{case_id}: provider-order: unexpected native provider log: {provider_arguments:?}"
                    ));
                }
                json!({
                    "status": "passed",
                    "path": match multiplexer_marker.as_deref() {
                        Some(marker) => format!("{marker} passthrough OSC52 response fell back to native provider"),
                        None => "Malformed or empty OSC52 response fell back to native provider".to_owned(),
                    },
                    "osc52_query_bytes_hex": hex_bytes(OSC52_QUERY),
                    "wrapped_query_bytes_hex": hex_bytes(&wrapped_query),
                    "osc52_response_bytes_hex": hex_bytes(&response),
                    "da1_query_bytes_hex": hex_bytes(DA1_QUERY),
                    "da1_response_bytes_hex": hex_bytes(DA1_RESPONSE),
                    "native_provider": "xclip",
                    "native_provider_arguments": provider_arguments.trim().to_owned(),
                })
            }
        } else {
            hades_dev::replay::send(&child.child.master, DA1_RESPONSE)
                .map_err(|error| error.to_string())?;
            wait_for_rendered(
                &child.child,
                &mut output,
                &format!("{case_id}: native-fallback"),
                |rendered| case_markers(case).iter().all(|marker| marker_present(rendered, marker)),
                timeout,
            )?;
            let provider_arguments = fs::read_to_string(&log_path).unwrap_or_default();
            let expected_arguments = "-selection clipboard -out";
            if provider_arguments.trim() != expected_arguments {
                return Err(format!(
                    "{case_id}: provider-order: unexpected native provider log: {provider_arguments:?}"
                ));
            }
            json!({
                "status": "passed",
                "path": match multiplexer_marker.as_deref() {
                    Some(marker) => format!("{marker} passthrough DA1 barrier acknowledged, then native provider fallback ran"),
                    None => "DA1 barrier acknowledged, then native provider fallback ran".to_owned(),
                },
                "osc52_query_bytes_hex": hex_bytes(OSC52_QUERY),
                "wrapped_query_bytes_hex": hex_bytes(&wrapped_query),
                "osc52_response": "not sent",
                "da1_query_bytes_hex": hex_bytes(DA1_QUERY),
                "da1_response_bytes_hex": hex_bytes(DA1_RESPONSE),
                "native_provider": "xclip",
                "native_provider_arguments": provider_arguments.trim().to_owned(),
            })
        };

        let rendered = rendered_text(&output);
        for marker in case_absent_markers(case) {
            if contains_marker(&output, &marker) || rendered.contains(&marker) {
                return Err(format!("{case_id}: screen: unexpected marker: {marker}"));
            }
        }
        if try_wait(&child.child)?.is_some() {
            return Err(format!("{case_id}: ready-state: process exited before cleanup"));
        }
        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 0 }) {
            return Err(format!("{case_id}: unexpected exit status: {exit_status:?}"));
        }

        Ok(json!({
            "id": case_id,
            "status": "passed",
            "draft": draft,
            "ssh_marker": "SSH_TTY=/dev/pts/999",
            "multiplexer_marker": multiplexer_marker,
            "input_bytes_hex": [
                hex_ascii(draft.as_bytes()),
                "16",
            ],
            "query_offset": query_at,
            "da1_query_offset": da1_at,
            "outcome": outcome,
            "screen_markers": case_markers(case),
            "screen_absent_markers": case_absent_markers(case),
            "capture": "direct PTY with TIOCSWINSZ 120x40",
        }))
    })();

    if !reaped {
        let _ = fs::remove_dir_all(&home);
    }
    result
}

fn case_markers(case: &Value) -> Vec<String> {
    case.get("screen_markers")
        .and_then(Value::as_array)
        .map(|markers| {
            markers.iter().filter_map(|marker| marker.as_str().map(str::to_owned)).collect()
        })
        .unwrap_or_default()
}

fn case_absent_markers(case: &Value) -> Vec<String> {
    case.get("screen_absent_markers")
        .and_then(Value::as_array)
        .map(|markers| {
            markers.iter().filter_map(|marker| marker.as_str().map(str::to_owned)).collect()
        })
        .unwrap_or_default()
}

fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|window| window == needle)
}

fn hex_bytes(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect::<Vec<_>>().join(" ")
}

fn hex_ascii(bytes: &[u8]) -> String {
    hex_bytes(bytes)
}

fn base64_payload(payload: &str) -> Vec<u8> {
    // Minimal base64 encoder (RFC 4648) for the fixture payload.
    const ALPHABET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let bytes = payload.as_bytes();
    let mut out = Vec::new();
    for chunk in bytes.chunks(3) {
        let b = [chunk[0], chunk.get(1).copied().unwrap_or(0), chunk.get(2).copied().unwrap_or(0)];
        let n = (u32::from(b[0]) << 16) | (u32::from(b[1]) << 8) | u32::from(b[2]);
        out.push(ALPHABET[(n >> 18) as usize & 63]);
        out.push(ALPHABET[(n >> 12) as usize & 63]);
        out.push(if chunk.len() > 1 { ALPHABET[(n >> 6) as usize & 63] } else { b'=' });
        out.push(if chunk.len() > 2 { ALPHABET[n as usize & 63] } else { b'=' });
    }
    let mut response = format!("\x1b]52;c;{}", String::from_utf8_lossy(&out)).into_bytes();
    response.push(0x07);
    response
}

fn write_report(report: &Value, path: Option<&Path>, status: u8) -> ExitCode {
    let text = serde_json::to_string_pretty(report).expect("serialize report");
    if let Some(path) = path {
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        use std::io::Write;
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
    let mut contract_path =
        PathBuf::from("tests/fixtures/parity/OBS-0025-hades-osc52-clipboard.json");
    let mut report_path: Option<PathBuf> = None;
    let mut timeout = Duration::from_secs_f64(5.0);

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
                    timeout = Duration::from_secs_f64(value.parse().unwrap_or(5.0));
                }
            }
            _ => {}
        }
    }

    let binary = binary.canonicalize().unwrap_or_else(|_| binary.clone());
    let contract_path = contract_path.canonicalize().unwrap_or_else(|_| contract_path.clone());
    let mut report = json!({
        "schema_version": 1,
        "command": "replay-osc52-clipboard",
        "passed": false,
        "binary": binary.display().to_string(),
        "contract": contract_path.display().to_string(),
        "checks": [],
    });
    if !binary.is_file() {
        report["failure"] = json!({"case": "input", "step": "binary", "message": format!("binary not found: {}", binary.display())});
        return write_report(&report, report_path.as_deref(), 1);
    }

    let contract: Value = match fs::read_to_string(&contract_path) {
        Ok(contents) => match serde_json::from_str(&contents) {
            Ok(value) => value,
            Err(error) => {
                report["failure"] =
                    json!({"case": "contract", "step": "load", "message": error.to_string()});
                return write_report(&report, report_path.as_deref(), 1);
            }
        },
        Err(error) => {
            report["failure"] =
                json!({"case": "contract", "step": "load", "message": error.to_string()});
            return write_report(&report, report_path.as_deref(), 1);
        }
    };
    if contract.get("schema_version").and_then(Value::as_u64) != Some(1) {
        report["failure"] =
            json!({"case": "contract", "step": "load", "message": "unsupported OSC52 contract"});
        return write_report(&report, report_path.as_deref(), 1);
    }
    let steps = contract.get("steps").and_then(Value::as_array).cloned().unwrap_or_default();
    if steps.is_empty() {
        report["failure"] = json!({"case": "contract", "step": "load", "message": "steps must be a non-empty array"});
        return write_report(&report, report_path.as_deref(), 1);
    }
    report["contract_observation"] = contract["observation_id"].clone();
    if let Some(reference) = contract.get("reference_observation") {
        report["reference_observation"] = reference.clone();
    }
    report["dimensions"] = contract["reference"]["terminal"].clone();

    let mut checks = Vec::new();
    for (ordinal, case) in steps.iter().enumerate() {
        match run_case(&binary, case, timeout, ordinal + 1) {
            Ok(check) => checks.push(check),
            Err(error) => {
                report["failure"] = json!({"case": "report", "step": "runtime", "message": error});
                return write_report(&report, report_path.as_deref(), 1);
            }
        }
    }
    report["checks"] = json!(checks);
    report["passed"] = json!(true);
    write_report(&report, report_path.as_deref(), 0)
}
