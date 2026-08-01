use std::{
    ffi::OsStr,
    io::Write,
    time::{Duration, Instant},
};

use base64::{Engine as _, engine::general_purpose::STANDARD};

use crate::clipboard;

const OSC52_QUERY: &[u8] = b"\x1b]52;c;?\x07";
const DA1_QUERY: &[u8] = b"\x1b[c";
const DA1_RESPONSE: &[u8] = b"\x1b[?62c";
const OSC52_RESPONSE_PREFIX: &[u8] = b"\x1b]52;";
const RESPONSE_TIMEOUT: Duration = Duration::from_millis(250);
const MAX_RESPONSE_BYTES: usize = clipboard::CLIPBOARD_MAX_BYTES * 2;

pub(crate) fn read_usable_text<W: Write>(writer: &mut W) -> Option<String> {
    #[cfg(unix)]
    {
        if !is_remote_shell() {
            return None;
        }

        read_remote_text(writer).ok().flatten()
    }

    #[cfg(not(unix))]
    {
        let _ = writer;
        None
    }
}

#[cfg(unix)]
fn read_remote_text<W: Write>(writer: &mut W) -> std::io::Result<Option<String>> {
    writer.write_all(OSC52_QUERY)?;
    writer.write_all(DA1_QUERY)?;
    writer.flush()?;
    Ok(read_response())
}

#[cfg(unix)]
fn read_response() -> Option<String> {
    let input = rustix::stdio::stdin();
    let deadline = Instant::now() + RESPONSE_TIMEOUT;
    let mut buffer = Vec::with_capacity(256);

    while Instant::now() < deadline {
        let remaining = deadline.saturating_duration_since(Instant::now());
        let timeout = rustix::event::Timespec::try_from(remaining).ok()?;
        let mut poll_fds = [rustix::event::PollFd::new(&input, rustix::event::PollFlags::IN)];
        let ready = rustix::event::poll(&mut poll_fds, Some(&timeout)).ok()?;
        if ready == 0 {
            break;
        }

        let mut chunk = [0_u8; 4096];
        let read = rustix::io::read(input, &mut chunk).ok()?;
        if read == 0 {
            break;
        }
        if buffer.len().saturating_add(read) > MAX_RESPONSE_BYTES {
            return None;
        }
        buffer.extend_from_slice(&chunk[..read]);

        if let Some(text) = parse_response(&buffer) {
            return text;
        }
        if find_subslice(&buffer, DA1_RESPONSE).is_some() {
            return None;
        }
    }

    None
}

fn is_remote_shell() -> bool {
    is_remote_shell_with(
        std::env::var_os("SSH_TTY").as_deref(),
        std::env::var_os("SSH_CONNECTION").as_deref(),
        std::env::var_os("SSH_CLIENT").as_deref(),
        std::env::var_os("TMUX").as_deref(),
        std::env::var_os("STY").as_deref(),
    )
}

fn is_remote_shell_with(
    ssh_tty: Option<&OsStr>,
    ssh_connection: Option<&OsStr>,
    ssh_client: Option<&OsStr>,
    tmux: Option<&OsStr>,
    sty: Option<&OsStr>,
) -> bool {
    let remote_marker =
        [ssh_tty, ssh_connection, ssh_client].into_iter().flatten().any(|value| !value.is_empty());
    remote_marker && ![tmux, sty].into_iter().flatten().any(|value| !value.is_empty())
}

fn parse_response(buffer: &[u8]) -> Option<Option<String>> {
    let start = find_subslice(buffer, OSC52_RESPONSE_PREFIX)?;
    let body_start = start + OSC52_RESPONSE_PREFIX.len();
    let (body_end, _) = find_osc_terminator(&buffer[body_start..])?;
    let body = &buffer[body_start..body_start + body_end];
    let encoded = body.strip_prefix(b"c;")?;
    let decoded = STANDARD.decode(encoded).ok()?;
    let text = String::from_utf8(decoded).ok()?;

    Some(clipboard::normalize_text(&text))
}

fn find_osc_terminator(buffer: &[u8]) -> Option<(usize, usize)> {
    for (index, byte) in buffer.iter().copied().enumerate() {
        if byte == b'\x07' {
            return Some((index, 1));
        }
        if byte == b'\x1b' && buffer.get(index + 1) == Some(&b'\\') {
            return Some((index, 2));
        }
    }
    None
}

fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|window| window == needle)
}

#[cfg(test)]
mod tests {
    use std::ffi::OsStr;

    use super::*;

    #[test]
    fn request_bytes_match_the_observed_bare_remote_sequence() {
        let mut request = Vec::new();
        request.extend_from_slice(OSC52_QUERY);
        request.extend_from_slice(DA1_QUERY);
        assert_eq!(request, b"\x1b]52;c;?\x07\x1b[c");
        assert_eq!(DA1_RESPONSE, b"\x1b[?62c");
    }

    #[test]
    fn remote_detection_requires_a_marker_and_excludes_unobserved_wrappers() {
        assert!(is_remote_shell_with(Some(OsStr::new("/dev/pts/999")), None, None, None, None,));
        assert!(is_remote_shell_with(
            None,
            Some(OsStr::new("10.0.0.1 22 10.0.0.2 5555")),
            None,
            None,
            None,
        ));
        assert!(!is_remote_shell_with(None, None, None, None, None));
        assert!(!is_remote_shell_with(
            Some(OsStr::new("/dev/pts/999")),
            None,
            None,
            Some(OsStr::new("/tmp/tmux-1000/default,1,2")),
            None,
        ));
    }

    #[test]
    fn response_decodes_text_and_removes_only_trailing_newlines() {
        let payload = STANDARD.encode("osc-remote  \nline-two\n\n");
        let response = format!("\x1b]52;c;{payload}\x07");
        assert_eq!(
            parse_response(response.as_bytes()).flatten().as_deref(),
            Some("osc-remote  \nline-two")
        );
    }

    #[test]
    fn response_accepts_st_termination_and_rejects_empty_or_invalid_text() {
        let payload = STANDARD.encode("usable");
        let response = format!("\x1b]52;c;{payload}\x1b\\");
        assert_eq!(parse_response(response.as_bytes()).flatten().as_deref(), Some("usable"));

        let empty = b"\x1b]52;c;\x07";
        assert_eq!(parse_response(empty).unwrap(), None);
        let invalid = b"\x1b]52;c;not-base64\x07";
        assert_eq!(parse_response(invalid), None);
    }

    #[test]
    fn incomplete_response_waits_for_a_terminator() {
        let payload = STANDARD.encode("usable");
        let response = format!("\x1b]52;c;{payload}");
        assert_eq!(parse_response(response.as_bytes()), None);
    }
}
