//! Hold-provider loopback server: the Rust port of
//! `replay_composer.HoldProviderServer` (HAD-132).
//!
//! A tiny std-only HTTP server on an ephemeral loopback port that accepts a
//! provider request, reads and discards its body, flags `request_seen`, then
//! HOLDS the connection open until `release_response` is set (up to a 3s
//! bound), mirroring the Python handler which never writes a response body.
//! The Hades TUI under test stays in its busy state while the connection is
//! held, which is exactly what the configured-family replays assert.
//!
//! `environment()` returns the provider env vars
//! (`HADES_PROVIDER_BASE_URL`/`HADES_MODEL`/`HADES_PROVIDER_API_KEY`) that
//! point a fresh Hades process at this server, like
//! `hold_provider_environment`.

use std::io::Read;
use std::net::{TcpListener, TcpStream};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

/// Shared server state: the request/release events.
struct HoldState {
    request_seen: AtomicBool,
    release_response: AtomicBool,
    shutdown: AtomicBool,
}

/// The running hold-provider server.
pub struct HoldProvider {
    port: u16,
    state: Arc<HoldState>,
    handle: Option<std::thread::JoinHandle<()>>,
}

impl HoldProvider {
    /// Bind an ephemeral loopback port and start the accept loop.
    pub fn start() -> std::io::Result<Self> {
        let listener = TcpListener::bind(("127.0.0.1", 0))?;
        let port = listener.local_addr()?.port();
        let state = Arc::new(HoldState {
            request_seen: AtomicBool::new(false),
            release_response: AtomicBool::new(false),
            shutdown: AtomicBool::new(false),
        });
        let thread_state = Arc::clone(&state);
        let handle = std::thread::spawn(move || serve(listener, thread_state));
        Ok(Self { port, state, handle: Some(handle) })
    }

    /// Whether a provider request has been accepted and read.
    pub fn request_seen(&self) -> bool {
        self.state.request_seen.load(Ordering::SeqCst)
    }

    /// Release held connections so their handlers can finish.
    pub fn release(&self) {
        self.state.release_response.store(true, Ordering::SeqCst);
    }

    /// The provider environment pointing a Hades process at this server,
    /// like `hold_provider_environment`.
    pub fn environment(&self) -> Vec<(&'static str, String)> {
        vec![
            ("HADES_PROVIDER_BASE_URL", format!("http://127.0.0.1:{}/v1", self.port)),
            ("HADES_MODEL", "palette-model".to_string()),
            ("HADES_PROVIDER_API_KEY", String::new()),
        ]
    }

    /// Stop the server: release any held connection and join the loop.
    pub fn finish(&mut self) {
        self.state.release_response.store(true, Ordering::SeqCst);
        self.state.shutdown.store(true, Ordering::SeqCst);
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

/// Accept loop on a non-blocking listener; exits on the shutdown flag.
fn serve(listener: TcpListener, state: Arc<HoldState>) {
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

/// Read a request head + Content-Length body, then hold the connection,
/// mirroring `HoldProviderServer.Handler.do_POST`.
fn handle_connection(mut stream: TcpStream, state: Arc<HoldState>) {
    let _ = stream.set_nodelay(true);
    if read_request_body(&mut stream).is_err() {
        return;
    }
    state.request_seen.store(true, Ordering::SeqCst);
    let deadline = Instant::now() + Duration::from_secs(3);
    while !state.release_response.load(Ordering::SeqCst) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(10));
    }
    let _ = stream.shutdown(std::net::Shutdown::Both);
}

/// Read the request head plus the Content-Length body, discarding both.
fn read_request_body(stream: &mut TcpStream) -> Result<(), String> {
    let mut buf = Vec::new();
    let mut tmp = [0u8; 8192];
    let (head_end, content_length) = loop {
        let count =
            stream.read(&mut tmp).map_err(|error| format!("request read failed: {error}"))?;
        if count == 0 {
            return Err("request ended inside the head".to_string());
        }
        buf.extend_from_slice(&tmp[..count]);
        if let Some(end) = buf.windows(4).position(|window| window == b"\r\n\r\n") {
            let header_block = &buf[..end];
            let mut length = 0usize;
            for line in header_block.split(|&byte| byte == b'\n') {
                let line = line.strip_suffix(b"\r").unwrap_or(line);
                if let Some(colon) = line.iter().position(|&byte| byte == b':') {
                    let key = &line[..colon];
                    let value = String::from_utf8_lossy(&line[colon + 1..]);
                    if key.eq_ignore_ascii_case(b"content-length") {
                        length = value.trim().parse().unwrap_or(0);
                    }
                }
            }
            break (end + 4, length);
        }
    };
    let mut have = buf[head_end..].len();
    while have < content_length {
        let count =
            stream.read(&mut tmp).map_err(|error| format!("request body read failed: {error}"))?;
        if count == 0 {
            break;
        }
        have += count;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::net::TcpStream;

    #[test]
    fn hold_provider_flags_request_seen_and_releases() {
        let mut provider = HoldProvider::start().expect("start");
        let (base, _model, _key) = {
            let env = provider.environment();
            (env[0].1.clone(), env[1].1.clone(), env[2].1.clone())
        };
        let url = format!("{base}/chat/completions");
        let client = std::thread::spawn(move || {
            let mut stream =
                TcpStream::connect(url.replace("http://", "").split('/').next().unwrap())
                    .expect("connect");
            let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));
            let request =
                "POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}".to_string();
            stream.write_all(request.as_bytes()).expect("write");
            // The server holds the connection; a short read should return
            // nothing yet, and the thread ends once release closes it.
            let mut buf = [0u8; 16];
            let _ = stream.read(&mut buf);
        });
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline && !provider.request_seen() {
            std::thread::sleep(Duration::from_millis(10));
        }
        assert!(provider.request_seen(), "request was never seen");
        provider.release();
        let _ = client.join();
        provider.finish();
    }

    #[test]
    fn hold_provider_environment_has_expected_keys() {
        let provider = HoldProvider::start().expect("start");
        let env = provider.environment();
        assert_eq!(env[0].0, "HADES_PROVIDER_BASE_URL");
        assert!(env[0].1.starts_with("http://127.0.0.1:"));
        assert_eq!(env[1].0, "HADES_MODEL");
        assert_eq!(env[1].1, "palette-model");
        assert_eq!(env[2].0, "HADES_PROVIDER_API_KEY");
        let mut provider = provider;
        provider.finish();
    }
}
