//! `hades-dev replay-osc52-timing-limits` — Rust port of
//! `scripts/replay_osc52_timing_limits.py` (HAD-159).
//!
//! Replays the OBS-0033 OSC52 timing and bounded-payload controls in a
//! direct PTY: responses before/after the 500ms timeout race, and large
//! (256KB) / oversized (512KB) bounded payloads that must be delivered
//! before the timeout deadline. A usable OSC52 response wins before the
//! native xclip provider; a delayed response falls back to xclip.

use std::fs;
use std::io::Write;
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
const TIMEOUT_RACE_MS: u64 = 500;
const NATIVE_ARGUMENTS: &str = "-selection clipboard -out";
const LARGE_DECODED_BYTES: usize = 256 * 1024;
const OVERSIZED_DECODED_BYTES: usize = 512 * 1024;

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
) -> Result<ReplayChild, String> {
    let path_value = std::env::var("PATH").unwrap_or_default();
    let mut entries = vec![provider_dir.as_os_str().to_owned()];
    entries.extend(std::env::split_paths(&path_value).map(std::ffi::OsString::from));
    let provider_path =
        std::env::join_paths(entries).map_err(|error| format!("could not build PATH: {error}"))?;
    let provider_path =
        provider_path.to_str().ok_or_else(|| "non-utf8 provider path".to_owned())?.to_owned();
    let extra: [(&str, &str); 7] = [
        ("HOME", home.to_str().ok_or_else(|| "non-utf8 home".to_owned())?),
        ("HERMES_HOME", home.to_str().ok_or_else(|| "non-utf8 home".to_owned())?),
        ("HADES_PROVIDER_BASE_URL", "http://127.0.0.1:8765/v1"),
        ("PATH", &provider_path),
        (
            "HADES_CLIPBOARD_PAYLOAD",
            payload_path.to_str().ok_or_else(|| "non-utf8 payload".to_owned())?,
        ),
        ("HADES_CLIPBOARD_LOG", log_path.to_str().ok_or_else(|| "non-utf8 log".to_owned())?),
        ("SSH_TTY", "/dev/pts/999"),
    ];
    let strip = [
        "SSH_CONNECTION",
        "SSH_CLIENT",
        "TMUX",
        "STY",
        "WAYLAND_DISPLAY",
        "WSL_INTEROP",
        "WSL_DISTRO_NAME",
    ];
    spawn_with_env(binary, &[], &extra, &strip).map_err(|error| error.to_string())
}

/// Build the deterministic payload like the Python `build_payload`:
/// a label prefix/suffix around a fill byte.
fn build_payload(label: &str, size: usize) -> Result<Vec<u8>, String> {
    let prefix = format!("{label}-start\n").into_bytes();
    let suffix = format!("\n{label}-end\n\n").into_bytes();
    if size <= prefix.len() + suffix.len() {
        return Err(format!("payload size is too small for {label}: {size}"));
    }
    let fill = vec![label.as_bytes()[0]; size - prefix.len() - suffix.len()];
    let mut payload = prefix;
    payload.extend_from_slice(&fill);
    payload.extend_from_slice(&suffix);
    Ok(payload)
}

fn payload_for(case_id: &str) -> Result<Vec<u8>, String> {
    match case_id {
        "response-before-timeout" => Ok(b"timing-before-remote  \nline-two\n\n".to_vec()),
        "response-after-timeout" => Ok(b"timing-after-remote  \nline-two\n\n".to_vec()),
        "large-response" => build_payload("large-response", LARGE_DECODED_BYTES),
        "oversized-response" => build_payload("oversized-response", OVERSIZED_DECODED_BYTES),
        _ => Err(format!("unknown OBS-0033 case: {case_id}")),
    }
}

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hasher.finalize().iter().map(|byte| format!("{byte:02x}")).collect()
}

/// RFC 4648 base64 encode.
fn base64_encode(bytes: &[u8]) -> String {
    const ALPHABET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::new();
    for chunk in bytes.chunks(3) {
        let b = [chunk[0], chunk.get(1).copied().unwrap_or(0), chunk.get(2).copied().unwrap_or(0)];
        let n = (u32::from(b[0]) << 16) | (u32::from(b[1]) << 8) | u32::from(b[2]);
        out.push(ALPHABET[(n >> 18) as usize & 63] as char);
        out.push(ALPHABET[(n >> 12) as usize & 63] as char);
        out.push(if chunk.len() > 1 { ALPHABET[(n >> 6) as usize & 63] as char } else { '=' });
        out.push(if chunk.len() > 2 { ALPHABET[n as usize & 63] as char } else { '=' });
    }
    out
}

fn hex_bytes(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect::<Vec<_>>().join(" ")
}

fn hex_from_string(value: &str) -> Result<Vec<u8>, String> {
    let compact: String = value.split_whitespace().collect();
    (0..compact.len())
        .step_by(2)
        .map(|index| {
            u8::from_str_radix(&compact[index..index + 2], 16)
                .map_err(|error| format!("invalid hex: {error}"))
        })
        .collect()
}

fn response_bytes(case_id: &str, payload: &[u8], case: &Value) -> Result<Vec<u8>, String> {
    let mut response = format!("\x1b]52;c;{}", base64_encode(payload)).into_bytes();
    response.push(0x07);
    let terminal_response =
        case.get("terminal_response").ok_or_else(|| "case has no terminal_response".to_owned())?;
    let expected_hash = terminal_response
        .get("decoded_payload_sha256")
        .and_then(Value::as_str)
        .ok_or_else(|| "missing decoded_payload_sha256".to_owned())?;
    if sha256_hex(payload) != expected_hash {
        return Err(format!(
            "{case_id}: payload-contract: deterministic payload hash disagrees with OBS-0033"
        ));
    }
    let expected_bytes =
        terminal_response.get("decoded_payload_bytes").and_then(Value::as_u64).unwrap_or_default()
            as usize;
    if payload.len() != expected_bytes {
        return Err(format!(
            "{case_id}: payload-contract: deterministic payload size disagrees with OBS-0033"
        ));
    }
    if let Some(response_hex) =
        terminal_response.get("osc52_response_bytes_hex").and_then(Value::as_str)
    {
        if hex_bytes(&response) != response_hex {
            return Err(format!(
                "{case_id}: payload-contract: small response bytes disagree with OBS-0033"
            ));
        }
    } else {
        let expected_len = terminal_response
            .get("osc52_response_bytes")
            .and_then(Value::as_u64)
            .unwrap_or_default() as usize;
        if response.len() != expected_len {
            return Err(format!(
                "{case_id}: payload-contract: bounded response byte count disagrees with OBS-0033"
            ));
        }
        let prefix = terminal_response
            .get("osc52_response_prefix_hex")
            .and_then(Value::as_str)
            .ok_or_else(|| "missing response prefix".to_owned())?;
        let suffix = terminal_response
            .get("osc52_response_suffix_hex")
            .and_then(Value::as_str)
            .ok_or_else(|| "missing response suffix".to_owned())?;
        if hex_bytes(&response[..16.min(response.len())]) != prefix {
            return Err(format!(
                "{case_id}: payload-contract: bounded response prefix disagrees with OBS-0033"
            ));
        }
        let tail_start = response.len().saturating_sub(16);
        if hex_bytes(&response[tail_start..]) != suffix {
            return Err(format!(
                "{case_id}: payload-contract: bounded response suffix disagrees with OBS-0033"
            ));
        }
    }
    Ok(response)
}

/// Write the full payload, waiting for the PTY to drain so large bounded
/// responses land before the timeout deadline (mirrors the Python
/// write_nonblocking: per-chunk os.write + select for writability).
///
/// The master is non-blocking, so `write` may partially write then return
/// EAGAIN; unlike `write_bytes` (which discards partial progress on
/// error), this tracks the offset across retries.
fn write_bounded(
    child: &ReplayChild,
    payload: &[u8],
    deadline: Instant,
    case_id: &str,
) -> Result<f64, String> {
    use rustix::io::{Errno, write};
    let started = Instant::now();
    let mut offset = 0;
    while offset < payload.len() {
        let chunk = &payload[offset..(offset + 65_536).min(payload.len())];
        match write(&child.child.master, chunk) {
            Ok(count) => offset += count,
            Err(Errno::AGAIN) => {
                if Instant::now() >= deadline {
                    return Err(format!(
                        "{case_id}: osc52-response-write: bounded response did not reach the PTY before the pre-timeout deadline (payload_bytes={}, written_bytes={offset})",
                        payload.len()
                    ));
                }
                std::thread::sleep(Duration::from_millis(2));
            }
            Err(error) => {
                return Err(format!(
                    "{case_id}: osc52-response-write: PTY write failed: {error:?} (written_bytes={offset})"
                ));
            }
        }
    }
    Ok(started.elapsed().as_secs_f64() * 1000.0)
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
    let payload = payload_for(&case_id)?;
    let response = response_bytes(&case_id, &payload, case)?;
    let terminal_response =
        case.get("terminal_response").ok_or_else(|| "missing terminal_response".to_owned())?;
    if terminal_response.get("osc52_query_bytes_hex").and_then(Value::as_str)
        != Some(&hex_bytes(OSC52_QUERY))
    {
        return Err(format!(
            "{case_id}: query-contract: OBS-0033 query bytes are not the bare OSC52 query"
        ));
    }
    if terminal_response.get("da1_sentinel_bytes_hex").and_then(Value::as_str)
        != Some(&hex_bytes(DA1_QUERY))
    {
        return Err(format!(
            "{case_id}: query-contract: OBS-0033 DA1 sentinel bytes are incorrect"
        ));
    }
    if terminal_response.get("da1_response_bytes_hex").and_then(Value::as_str)
        != Some(&hex_bytes(DA1_RESPONSE))
    {
        return Err(format!(
            "{case_id}: query-contract: OBS-0033 DA1 response bytes are incorrect"
        ));
    }

    let output_contract = case.get("output").ok_or_else(|| "missing output contract".to_owned())?;
    let native_payload =
        output_contract.get("native_payload").and_then(Value::as_str).unwrap_or_default();
    let home =
        std::env::temp_dir().join(format!("had033-{case_id}-{ordinal}-{}", std::process::id()));
    let provider_dir = home.join("bin");
    let payload_path = home.join("clipboard.payload");
    let log_path = home.join("clipboard.args");
    fs::create_dir_all(&home).map_err(|error| error.to_string())?;
    fs::write(&payload_path, native_payload.as_bytes()).map_err(|error| error.to_string())?;
    create_xclip(&provider_dir, &log_path)?;

    let mut reaped = false;
    let result = (|| -> Result<Value, String> {
        let child = spawn_osc52(binary, &home, &provider_dir, &payload_path, &log_path)?;
        let mut output = Vec::new();

        wait_for(
            &child.child,
            &mut output,
            &format!("{case_id}: startup"),
            |text| STARTUP_MARKERS.iter().all(|marker| marker_present(text, marker)),
            timeout,
        )?;
        let draft = case["input_sequence"][0]["value"].as_str().unwrap_or_default().to_owned();
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
                find_subslice(&output[start..], OSC52_QUERY).map(|offset| start + offset)
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
        let query_observed_at = Instant::now();
        let da1_deadline = Instant::now() + timeout;
        let da1_at = loop {
            output.extend_from_slice(&read_available(&child.child.master));
            if let Some(position) =
                find_subslice(&output[query_at + OSC52_QUERY.len()..], DA1_QUERY)
                    .map(|offset| query_at + OSC52_QUERY.len() + offset)
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

        let (response_write_ms, boundary): (f64, &str) = match case_id.as_str() {
            "response-after-timeout" => {
                sleep_until(query_observed_at + Duration::from_millis(600));
                let response_sent_at = Instant::now();
                hades_dev::replay::send(&child.child.master, &response)
                    .map_err(|error| error.to_string())?;
                hades_dev::replay::send(&child.child.master, DA1_RESPONSE)
                    .map_err(|error| error.to_string())?;
                (response_sent_at.elapsed().as_secs_f64() * 1000.0, "response-after-500ms-timeout")
            }
            "response-before-timeout" => {
                sleep_until(query_observed_at + Duration::from_millis(100));
                let response_sent_at = Instant::now();
                hades_dev::replay::send(&child.child.master, &response)
                    .map_err(|error| error.to_string())?;
                hades_dev::replay::send(&child.child.master, DA1_RESPONSE)
                    .map_err(|error| error.to_string())?;
                (response_sent_at.elapsed().as_secs_f64() * 1000.0, "response-before-500ms-timeout")
            }
            _ => {
                let response_sent_at = Instant::now();
                let write_ms = write_bounded(
                    &child,
                    &response,
                    query_observed_at + Duration::from_millis(450),
                    &case_id,
                )?;
                hades_dev::replay::send(&child.child.master, DA1_RESPONSE)
                    .map_err(|error| error.to_string())?;
                (write_ms, "bounded-response-before-500ms-timeout")
            }
        };

        let expected_outcome =
            output_contract.get("outcome").and_then(Value::as_str).unwrap_or_default().to_owned();
        let screen_markers: Vec<String> = output_contract
            .get("screen_markers")
            .and_then(Value::as_array)
            .map(|markers| {
                markers.iter().filter_map(|marker| marker.as_str().map(str::to_owned)).collect()
            })
            .unwrap_or_default();
        wait_for_rendered(
            &child.child,
            &mut output,
            &format!("{case_id}: response-outcome"),
            |rendered| screen_markers.iter().all(|marker| marker_present(rendered, marker)),
            timeout,
        )?;
        let provider_arguments = fs::read_to_string(&log_path).unwrap_or_default();
        let remote_marker = output_contract.get("remote_marker").and_then(Value::as_str);
        let remote_observed = remote_marker.is_some_and(|marker| contains_marker(&output, marker));
        let native_observed = contains_marker(&output, native_payload.trim_end_matches('\n'));
        if expected_outcome == "osc52-response" {
            if !provider_arguments.trim().is_empty() || !remote_observed || native_observed {
                return Err(format!(
                    "{case_id}: provider-order: Hades did not keep the usable OSC52 response ahead of native xclip (native_provider_arguments={provider_arguments:?}, remote_observed={remote_observed})"
                ));
            }
        } else if expected_outcome == "native-fallback" {
            if provider_arguments.trim() != NATIVE_ARGUMENTS || !native_observed || remote_observed
            {
                return Err(format!(
                    "{case_id}: provider-order: Hades did not fall back to native xclip after the delayed OSC52 response (native_provider_arguments={provider_arguments:?}, remote_observed={remote_observed})"
                ));
            }
        } else {
            return Err(format!(
                "{case_id}: contract: unsupported expected outcome: {expected_outcome}"
            ));
        }

        for marker in output_contract
            .get("screen_absent_markers")
            .and_then(Value::as_array)
            .map(|markers| {
                markers
                    .iter()
                    .filter_map(|marker| marker.as_str().map(str::to_owned))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default()
        {
            if contains_marker(&output, &marker) {
                return Err(format!("{case_id}: screen: unexpected marker: {marker}"));
            }
        }
        if try_wait(&child.child)?.is_some() {
            return Err(format!("{case_id}: ready-state: Hades exited before cleanup"));
        }
        hades_dev::replay::send(&child.child.master, b"\x03").map_err(|error| error.to_string())?;
        let status = wait_for_exit(&child.child, &mut output, timeout)?;
        reaped = true;
        let exit_status = ExitStatus::describe(status);
        if exit_status != (ExitStatus::Exit { code: 0 }) {
            return Err(format!("{case_id}: unexpected exit status: {exit_status:?}"));
        }

        let response_elapsed_ms = (Instant::now() - query_observed_at).as_secs_f64() * 1000.0;
        let rendered = rendered_text(&output);
        let screen_tail = if rendered.len() > 2000 {
            rendered[rendered.len() - 2000..].to_owned()
        } else {
            rendered
        };
        Ok(json!({
            "id": case_id,
            "status": "passed",
            "draft": draft,
            "ssh_marker": "SSH_TTY=/dev/pts/999",
            "input_sequence": case["input_sequence"].clone(),
            "terminal_response": {
                "osc52_query_bytes_hex": hex_bytes(OSC52_QUERY),
                "da1_sentinel_bytes_hex": hex_bytes(DA1_QUERY),
                "da1_response_bytes_hex": hex_bytes(DA1_RESPONSE),
                "osc52_response_prefix_hex": hex_bytes(&response[..16.min(response.len())]),
                "osc52_response_suffix_hex": hex_bytes(
                    &response[response.len().saturating_sub(16)..]
                ),
                "osc52_response_bytes": response.len(),
                "decoded_payload_bytes": payload.len(),
                "decoded_payload_sha256": sha256_hex(&payload),
                "query_offset": query_at,
                "da1_query_offset": da1_at,
            },
            "timing": {
                "timeout_race_ms": TIMEOUT_RACE_MS,
                "boundary": boundary,
                "response_elapsed_ms": response_elapsed_ms,
                "response_write_ms": response_write_ms,
            },
            "output": {
                "status": "ready",
                "outcome": expected_outcome,
                "provider_order": output_contract.get("provider_order").cloned().unwrap_or_default(),
                "native_provider": output_contract.get("native_provider").cloned().unwrap_or_default(),
                "native_provider_arguments": provider_arguments.trim().to_owned(),
                "screen_markers": screen_markers,
                "screen_absent_markers": output_contract
                    .get("screen_absent_markers")
                    .cloned()
                    .unwrap_or_else(|| json!([])),
                "submission": output_contract.get("submission").cloned().unwrap_or_default(),
                "cleanup": "clean exit after bounded replay",
            },
            "screen_tail": screen_tail,
        }))
    })();

    if !reaped {
        let _ = fs::remove_dir_all(&home);
    }
    result
}

fn sleep_until(deadline: Instant) {
    let remaining = deadline.saturating_duration_since(Instant::now());
    if !remaining.is_zero() {
        std::thread::sleep(remaining);
    }
}

fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|window| window == needle)
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
    let mut contract_path =
        PathBuf::from("tests/fixtures/parity/OBS-0033-hades-osc52-timing-limits.json");
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
        "command": "replay-osc52-timing-limits",
        "observation_id": "OBS-0033",
        "reference_observation": "OBS-0032",
        "binary": binary.display().to_string(),
        "contract": contract_path.display().to_string(),
        "terminal": {"columns": COLUMNS, "rows": ROWS, "capture": "direct PTY with raw bytes"},
        "checks": [],
        "passed": false,
    });
    if !binary.is_file() {
        report["failure"] = json!({"case": "input", "step": "binary", "message": format!("binary not found: {}", binary.display())});
        return write_report(&report, report_path.as_deref(), 1);
    }
    let contract: Value = match fs::read_to_string(&contract_path) {
        Ok(contents) => serde_json::from_str(&contents).unwrap_or(Value::Null),
        Err(error) => {
            report["failure"] =
                json!({"case": "contract", "step": "load", "message": error.to_string()});
            return write_report(&report, report_path.as_deref(), 1);
        }
    };
    if contract.get("schema_version").and_then(Value::as_u64) != Some(1)
        || contract.get("observation_id").and_then(Value::as_str) != Some("OBS-0033")
    {
        report["failure"] =
            json!({"case": "contract", "step": "load", "message": "unsupported OBS-0033 contract"});
        return write_report(&report, report_path.as_deref(), 1);
    }
    let steps = contract.get("steps").and_then(Value::as_array).cloned().unwrap_or_default();
    let expected_ids = [
        "response-before-timeout",
        "response-after-timeout",
        "large-response",
        "oversized-response",
    ];
    let mut ids: Vec<&str> =
        steps.iter().filter_map(|step| step.get("id").and_then(Value::as_str)).collect();
    ids.sort();
    let mut expected = expected_ids.to_vec();
    expected.sort();
    if ids != expected {
        report["failure"] = json!({"case": "contract", "step": "load", "message": "OBS-0033 must contain the four timing-limit controls"});
        return write_report(&report, report_path.as_deref(), 1);
    }

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
    report["unknowns"] = json!([
        "The Hades replay proves only the OBS-0032 direct-PTY timing controls and bounded 256 KiB/512 KiB payloads.",
        "It does not claim a universal timeout or maximum-size contract, larger payload behavior, or wall-clock jitter parity.",
        "ST termination, TMUX/STY forwarding, images/paths, gateway behavior, and concurrent input remain separate controls.",
    ]);
    report["passed"] = json!(true);
    write_report(&report, report_path.as_deref(), 0)
}
