#![forbid(unsafe_code)]

//! A deliberately small local OpenAI-compatible streaming transport.
//!
//! This crate owns wire effects, URL policy, and SSE normalization. It does
//! not know about TUI state, tool execution, persistence, credentials, or
//! external HTTPS providers. Keeping those boundaries explicit lets the app
//! reducer consume typed stream events without importing an HTTP client.

use std::{
    fmt,
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};

use serde::Serialize;
use serde_json::Value;

pub const DEFAULT_MAX_TOKENS: u32 = 65_536;
pub const DEFAULT_TIMEOUT: Duration = Duration::from_secs(10);
const READ_POLL_INTERVAL: Duration = Duration::from_millis(50);
const MAX_RESPONSE_HEADER_BYTES: usize = 64 * 1024;

/// The observed Hermes 31-tool inventory (OBS-0112), embedded as public API
/// schema data from the pinned reference commit. Hades advertises this
/// inventory on streaming chat requests to match the observed wire contract;
/// it never executes, approves, or forwards these tools.
pub fn hermes_tool_inventory() -> &'static [Value] {
    static TOOLS: std::sync::LazyLock<Vec<Value>> = std::sync::LazyLock::new(|| {
        serde_json::from_str(include_str!("../assets/hermes-tools.json"))
            .expect("embedded Hermes tool inventory must be valid JSON")
    });
    &TOOLS
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

impl ChatMessage {
    pub fn new(role: impl Into<String>, content: impl Into<String>) -> Self {
        Self { role: role.into(), content: content.into() }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ChatRequest {
    pub model: String,
    pub messages: Vec<ChatMessage>,
    pub tools: Vec<Value>,
    pub max_tokens: u32,
    pub include_usage: bool,
}

impl ChatRequest {
    pub fn new(model: impl Into<String>, messages: Vec<ChatMessage>, tools: Vec<Value>) -> Self {
        Self {
            model: model.into(),
            messages,
            tools,
            max_tokens: DEFAULT_MAX_TOKENS,
            include_usage: true,
        }
    }

    pub fn with_max_tokens(mut self, max_tokens: u32) -> Self {
        self.max_tokens = max_tokens;
        self
    }

    pub fn with_usage(mut self, include_usage: bool) -> Self {
        self.include_usage = include_usage;
        self
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ToolCallDelta {
    /// Per-stream tool-call index; argument fragments for the same call share it.
    pub index: usize,
    /// Optional call identifier supplied on the first delta.
    pub id: Option<String>,
    /// Optional function name supplied on the first delta.
    pub name: Option<String>,
    /// One JSON argument fragment; later deltas append to the call.
    pub arguments: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum StreamEvent {
    TextDelta(String),
    ToolCallDelta(ToolCallDelta),
    Done,
}

#[derive(Clone, Debug)]
pub struct CancellationToken {
    cancelled: Arc<AtomicBool>,
}

impl CancellationToken {
    pub fn new() -> Self {
        Self { cancelled: Arc::new(AtomicBool::new(false)) }
    }

    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Release);
    }

    fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::Acquire)
    }
}

impl Default for CancellationToken {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TransportError {
    UnsupportedScheme(String),
    NonLoopbackHost(String),
    MissingPort,
    InvalidPort(String),
    InvalidBasePath(String),
    Io(String),
    Serialization(String),
    InvalidResponse(String),
    HttpStatus { status: u16, body: String },
    MalformedSse(String),
    MissingDone,
    MissingCompletionData,
    Cancelled,
}

impl fmt::Display for TransportError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnsupportedScheme(scheme) => {
                write!(formatter, "unsupported URL scheme: {scheme}")
            }
            Self::NonLoopbackHost(host) => {
                write!(formatter, "provider host is not loopback: {host}")
            }
            Self::MissingPort => formatter.write_str("provider URL is missing a port"),
            Self::InvalidPort(port) => write!(formatter, "invalid provider port: {port}"),
            Self::InvalidBasePath(path) => write!(formatter, "invalid provider base path: {path}"),
            Self::Io(message) => write!(formatter, "provider I/O failed: {message}"),
            Self::Serialization(message) => {
                write!(formatter, "provider request serialization failed: {message}")
            }
            Self::InvalidResponse(message) => {
                write!(formatter, "invalid provider response: {message}")
            }
            Self::HttpStatus { status, body } => {
                write!(formatter, "provider returned HTTP {status}: {body}")
            }
            Self::MalformedSse(message) => {
                write!(formatter, "malformed provider SSE: {message}")
            }
            Self::MissingDone => formatter.write_str("provider stream ended without [DONE]"),
            Self::MissingCompletionData => {
                formatter.write_str("provider stream contained no assistant text")
            }
            Self::Cancelled => formatter.write_str("provider stream cancelled"),
        }
    }
}

impl std::error::Error for TransportError {}

#[derive(Clone, Debug)]
pub struct LocalOpenAiTransport {
    address: SocketAddr,
    host_header: String,
    request_path: String,
    api_key: Option<String>,
    timeout: Duration,
}

pub struct OpenAiStream {
    stream: TcpStream,
    buffer: Vec<u8>,
    data_lines: Vec<String>,
    saw_text: bool,
    saw_tool_call: bool,
    done: bool,
    cancellation: CancellationToken,
}

impl LocalOpenAiTransport {
    pub fn new(base_url: &str, api_key: Option<String>) -> Result<Self, TransportError> {
        Self::with_timeout(base_url, api_key, DEFAULT_TIMEOUT)
    }

    pub fn with_timeout(
        base_url: &str,
        api_key: Option<String>,
        timeout: Duration,
    ) -> Result<Self, TransportError> {
        let parsed = parse_base_url(base_url)?;
        Ok(Self {
            address: parsed.address,
            host_header: parsed.host_header,
            request_path: parsed.request_path,
            api_key,
            timeout,
        })
    }

    pub fn request_path(&self) -> &str {
        &self.request_path
    }

    pub fn stream_chat(&self, request: &ChatRequest) -> Result<Vec<StreamEvent>, TransportError> {
        let cancellation = CancellationToken::new();
        let mut stream = self.open_stream(request, &cancellation)?;
        let mut events = Vec::new();
        while let Some(event) = stream.next_event()? {
            let is_done = event == StreamEvent::Done;
            events.push(event);
            if is_done {
                break;
            }
        }
        Ok(events)
    }

    pub fn open_stream(
        &self,
        request: &ChatRequest,
        cancellation: &CancellationToken,
    ) -> Result<OpenAiStream, TransportError> {
        if cancellation.is_cancelled() {
            return Err(TransportError::Cancelled);
        }
        let body = WireRequest::from(request);
        let body = serde_json::to_vec(&body)
            .map_err(|error| TransportError::Serialization(error.to_string()))?;
        let mut stream = TcpStream::connect_timeout(&self.address, self.timeout)
            .map_err(|error| TransportError::Io(error.to_string()))?;
        stream
            .set_read_timeout(Some(READ_POLL_INTERVAL))
            .map_err(|error| TransportError::Io(error.to_string()))?;
        stream
            .set_write_timeout(Some(self.timeout))
            .map_err(|error| TransportError::Io(error.to_string()))?;

        let mut headers = format!(
            "POST {} HTTP/1.1\r\nHost: {}\r\nContent-Type: application/json\r\nAccept: text/event-stream\r\nConnection: close\r\nContent-Length: {}\r\n",
            self.request_path,
            self.host_header,
            body.len()
        );
        if let Some(api_key) = &self.api_key {
            headers.push_str(&format!("Authorization: Bearer {api_key}\r\n"));
        }
        headers.push_str("\r\n");
        stream
            .write_all(headers.as_bytes())
            .and_then(|_| stream.write_all(&body))
            .map_err(|error| TransportError::Io(error.to_string()))?;

        let response_bytes = read_http_headers(&mut stream, cancellation, self.timeout)?;
        let header_end = response_bytes
            .windows(4)
            .position(|window| window == b"\r\n\r\n")
            .map(|position| position + 4)
            .ok_or_else(|| {
                TransportError::InvalidResponse("missing HTTP header boundary".to_owned())
            })?;
        let header = parse_http_header(&response_bytes[..header_end])?;
        let initial_body = &response_bytes[header_end..];
        if header.status != 200 {
            let mut body = initial_body.to_vec();
            body.extend(read_to_end_with_cancellation(&mut stream, cancellation)?);
            return Err(TransportError::HttpStatus {
                status: header.status,
                body: String::from_utf8_lossy(&body).trim().to_owned(),
            });
        }
        if !header.content_type.is_some_and(|value| value.starts_with("text/event-stream")) {
            return Err(TransportError::InvalidResponse("expected text/event-stream".to_owned()));
        }
        Ok(OpenAiStream {
            stream,
            buffer: initial_body.to_vec(),
            data_lines: Vec::new(),
            saw_text: false,
            saw_tool_call: false,
            done: false,
            cancellation: cancellation.clone(),
        })
    }
}

impl OpenAiStream {
    pub fn next_event(&mut self) -> Result<Option<StreamEvent>, TransportError> {
        if self.done {
            return Ok(None);
        }

        loop {
            if self.cancellation.is_cancelled() {
                return Err(TransportError::Cancelled);
            }
            if let Some(newline) = self.buffer.iter().position(|byte| *byte == b'\n') {
                let line = self.buffer.drain(..=newline).collect::<Vec<_>>();
                let line = line.strip_suffix(b"\n").unwrap_or(&line);
                let line = line.strip_suffix(b"\r").unwrap_or(line);
                if line.is_empty() {
                    if self.data_lines.is_empty() {
                        continue;
                    }
                    let data = self.data_lines.join("\n");
                    self.data_lines.clear();
                    let event = parse_sse_data(&data)?;
                    if let Some(event) = event {
                        if event == StreamEvent::Done {
                            if !self.saw_text && !self.saw_tool_call {
                                return Err(TransportError::MissingCompletionData);
                            }
                            self.done = true;
                        } else {
                            match event {
                                StreamEvent::TextDelta(_) => self.saw_text = true,
                                StreamEvent::ToolCallDelta(_) => self.saw_tool_call = true,
                                StreamEvent::Done => {}
                            }
                        }
                        return Ok(Some(event));
                    }
                    continue;
                }
                if line.starts_with(b":") || line.starts_with(b"event:") || line.starts_with(b"id:")
                {
                    continue;
                }
                if let Some(data) = line.strip_prefix(b"data:") {
                    let data = data.strip_prefix(b" ").unwrap_or(data);
                    let data = std::str::from_utf8(data)
                        .map_err(|error| TransportError::MalformedSse(error.to_string()))?;
                    self.data_lines.push(data.to_owned());
                    continue;
                }
                let line = String::from_utf8_lossy(line);
                return Err(TransportError::MalformedSse(format!("unexpected line: {line}")));
            }

            let mut chunk = [0_u8; 8192];
            match self.stream.read(&mut chunk) {
                Ok(0) => return Err(TransportError::MissingDone),
                Ok(read) => self.buffer.extend_from_slice(&chunk[..read]),
                Err(error)
                    if matches!(
                        error.kind(),
                        std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                    ) =>
                {
                    continue;
                }
                Err(error) => return Err(TransportError::Io(error.to_string())),
            }
        }
    }
}

#[derive(Serialize)]
struct WireRequest<'a> {
    max_tokens: u32,
    messages: &'a [ChatMessage],
    model: &'a str,
    stream: bool,
    stream_options: StreamOptions,
    tools: &'a [Value],
}

impl<'a> From<&'a ChatRequest> for WireRequest<'a> {
    fn from(request: &'a ChatRequest) -> Self {
        Self {
            max_tokens: request.max_tokens,
            messages: &request.messages,
            model: &request.model,
            stream: true,
            stream_options: StreamOptions { include_usage: request.include_usage },
            tools: &request.tools,
        }
    }
}

#[derive(Serialize)]
struct StreamOptions {
    include_usage: bool,
}

struct ParsedBaseUrl {
    address: SocketAddr,
    host_header: String,
    request_path: String,
}

struct HttpHeader {
    status: u16,
    content_type: Option<String>,
}

fn parse_base_url(base_url: &str) -> Result<ParsedBaseUrl, TransportError> {
    let Some(rest) = base_url.strip_prefix("http://") else {
        let scheme = base_url.split_once("://").map_or("unknown", |(scheme, _)| scheme);
        return Err(TransportError::UnsupportedScheme(scheme.to_owned()));
    };
    if rest.contains('@') || rest.contains('?') || rest.contains('#') {
        return Err(TransportError::InvalidBasePath(base_url.to_owned()));
    }
    let (authority, path) = rest
        .split_once('/')
        .map_or((rest, String::new()), |(authority, path)| (authority, format!("/{path}")));
    let Some((host, port)) = authority.rsplit_once(':') else {
        return Err(TransportError::MissingPort);
    };
    if host != "127.0.0.1" {
        return Err(TransportError::NonLoopbackHost(host.to_owned()));
    }
    let port = port.parse::<u16>().map_err(|_| TransportError::InvalidPort(port.to_owned()))?;
    let path = if path.is_empty() { "/" } else { path.as_str() };
    if !path.starts_with('/') || path.ends_with("//") {
        return Err(TransportError::InvalidBasePath(path.to_owned()));
    }
    let base_path = path.trim_end_matches('/');
    let request_path = if base_path.is_empty() {
        "/chat/completions".to_owned()
    } else {
        format!("{base_path}/chat/completions")
    };
    let host_header = format!("127.0.0.1:{port}");
    let address =
        host_header.parse::<SocketAddr>().map_err(|error| TransportError::Io(error.to_string()))?;
    Ok(ParsedBaseUrl { address, host_header, request_path })
}

fn read_http_headers(
    stream: &mut TcpStream,
    cancellation: &CancellationToken,
    timeout: Duration,
) -> Result<Vec<u8>, TransportError> {
    let deadline = Instant::now() + timeout;
    let mut response = Vec::new();
    let mut chunk = [0_u8; 8192];
    loop {
        if cancellation.is_cancelled() {
            return Err(TransportError::Cancelled);
        }
        if response.windows(4).any(|window| window == b"\r\n\r\n") {
            return Ok(response);
        }
        if response.len() >= MAX_RESPONSE_HEADER_BYTES {
            return Err(TransportError::InvalidResponse("HTTP headers are too large".to_owned()));
        }
        match stream.read(&mut chunk) {
            Ok(0) => {
                return Err(TransportError::InvalidResponse(
                    "missing HTTP header boundary".to_owned(),
                ));
            }
            Ok(read) => response.extend_from_slice(&chunk[..read]),
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                ) =>
            {
                if Instant::now() >= deadline {
                    return Err(TransportError::Io(
                        "provider response headers timed out".to_owned(),
                    ));
                }
            }
            Err(error) => return Err(TransportError::Io(error.to_string())),
        }
    }
}

fn parse_http_header(header_bytes: &[u8]) -> Result<HttpHeader, TransportError> {
    let header = std::str::from_utf8(header_bytes)
        .map_err(|error| TransportError::InvalidResponse(error.to_string()))?;
    let mut status_parts = header.lines().next().unwrap_or_default().split_whitespace();
    let _http_version = status_parts.next();
    let status = status_parts
        .next()
        .ok_or_else(|| TransportError::InvalidResponse("missing HTTP status".to_owned()))?
        .parse::<u16>()
        .map_err(|_| TransportError::InvalidResponse("invalid HTTP status".to_owned()))?;
    let content_type = header.lines().find_map(|line| {
        let (name, value) = line.split_once(':')?;
        (name.eq_ignore_ascii_case("content-type")).then_some(value.trim())
    });
    Ok(HttpHeader { status, content_type: content_type.map(str::to_owned) })
}

fn read_to_end_with_cancellation(
    stream: &mut TcpStream,
    cancellation: &CancellationToken,
) -> Result<Vec<u8>, TransportError> {
    let mut body = Vec::new();
    let mut chunk = [0_u8; 8192];
    loop {
        if cancellation.is_cancelled() {
            return Err(TransportError::Cancelled);
        }
        match stream.read(&mut chunk) {
            Ok(0) => return Ok(body),
            Ok(read) => body.extend_from_slice(&chunk[..read]),
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                ) =>
            {
                continue;
            }
            Err(error) => return Err(TransportError::Io(error.to_string())),
        }
    }
}

#[cfg(test)]
fn parse_sse(body: &str) -> Result<Vec<StreamEvent>, TransportError> {
    let mut events = Vec::new();
    let mut data_lines = Vec::new();
    let mut saw_done = false;
    for line in body.lines() {
        let line = line.strip_suffix('\r').unwrap_or(line);
        if line.is_empty() {
            if let Some(event) = parse_sse_event(&data_lines)? {
                if event == StreamEvent::Done {
                    saw_done = true;
                    events.push(event);
                    break;
                }
                events.push(event);
            }
            data_lines.clear();
            continue;
        }
        if line.starts_with(':') || line.starts_with("event:") || line.starts_with("id:") {
            continue;
        }
        if let Some(data) = line.strip_prefix("data:") {
            data_lines.push(data.strip_prefix(' ').unwrap_or(data));
        } else {
            return Err(TransportError::MalformedSse(format!("unexpected line: {line}")));
        }
    }
    if !data_lines.is_empty()
        && !saw_done
        && let Some(event) = parse_sse_event(&data_lines)?
    {
        events.push(event);
    }
    if !saw_done {
        return Err(TransportError::MissingDone);
    }
    let has_content = events
        .iter()
        .any(|event| matches!(event, StreamEvent::TextDelta(_) | StreamEvent::ToolCallDelta(_)));
    if !has_content {
        return Err(TransportError::MissingCompletionData);
    }
    Ok(events)
}

fn parse_sse_event(data_lines: &[&str]) -> Result<Option<StreamEvent>, TransportError> {
    if data_lines.is_empty() {
        return Ok(None);
    }
    let data = data_lines.join("\n");
    if data == "[DONE]" {
        return Ok(Some(StreamEvent::Done));
    }
    let payload: Value = serde_json::from_str(&data)
        .map_err(|error| TransportError::MalformedSse(error.to_string()))?;
    let choice =
        payload.get("choices").and_then(Value::as_array).and_then(|choices| choices.first());
    let text = choice
        .and_then(|choice| choice.get("delta"))
        .and_then(|delta| delta.get("content"))
        .and_then(Value::as_str);
    if let Some(text) = text.filter(|value| !value.is_empty()) {
        return Ok(Some(StreamEvent::TextDelta(text.to_owned())));
    }
    let tool_calls = choice
        .and_then(|choice| choice.get("delta"))
        .and_then(|delta| delta.get("tool_calls"))
        .and_then(Value::as_array);
    if let Some(tool_calls) = tool_calls {
        for call in tool_calls {
            let index = call.get("index").and_then(Value::as_u64).unwrap_or(0) as usize;
            let id = call.get("id").and_then(Value::as_str).map(str::to_owned);
            let function = call.get("function");
            let name =
                function.and_then(|f| f.get("name")).and_then(Value::as_str).map(str::to_owned);
            let arguments = function
                .and_then(|f| f.get("arguments"))
                .and_then(Value::as_str)
                .map(str::to_owned);
            if id.is_some() || name.is_some() || arguments.is_some() {
                return Ok(Some(StreamEvent::ToolCallDelta(ToolCallDelta {
                    index,
                    id,
                    name,
                    arguments,
                })));
            }
        }
    }
    Ok(None)
}

fn parse_sse_data(data: &str) -> Result<Option<StreamEvent>, TransportError> {
    let lines = data.split('\n').collect::<Vec<_>>();
    parse_sse_event(&lines)
}

#[cfg(test)]
mod tests {
    use std::{
        io::{Read, Write},
        net::TcpListener,
        sync::mpsc,
        thread,
    };

    use serde_json::{Value, json};

    use super::*;

    fn request() -> ChatRequest {
        ChatRequest::new(
            "palette-model",
            vec![
                ChatMessage::new("system", "system prompt"),
                ChatMessage::new("user", "sanitized prompt"),
            ],
            vec![json!({
                "type": "function",
                "function": {
                    "name": "synthetic_tool",
                    "parameters": {"type": "object"}
                }
            })],
        )
    }

    #[test]
    fn local_transport_emits_observed_request_shape_and_parses_sse() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).expect("bind loopback fixture");
        let port = listener.local_addr().unwrap().port();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept fixture client");
            let mut request_bytes = Vec::new();
            let mut chunk = [0_u8; 4096];
            loop {
                let read = stream.read(&mut chunk).expect("read request");
                request_bytes.extend_from_slice(&chunk[..read]);
                if request_bytes.windows(4).any(|window| window == b"\r\n\r\n") {
                    let header_end =
                        request_bytes.windows(4).position(|window| window == b"\r\n\r\n").unwrap()
                            + 4;
                    let header = String::from_utf8_lossy(&request_bytes[..header_end]);
                    let length = header
                        .lines()
                        .find_map(|line| line.strip_prefix("Content-Length: "))
                        .unwrap()
                        .parse::<usize>()
                        .unwrap();
                    if request_bytes.len() >= header_end + length {
                        break;
                    }
                }
            }
            let body_start =
                request_bytes.windows(4).position(|window| window == b"\r\n\r\n").unwrap() + 4;
            let body: Value = serde_json::from_slice(&request_bytes[body_start..]).unwrap();
            let body_keys = body.as_object().unwrap().keys().cloned().collect::<Vec<_>>();
            assert_eq!(
                body_keys,
                vec!["max_tokens", "messages", "model", "stream", "stream_options", "tools"]
            );
            assert_eq!(body["model"], "palette-model");
            assert_eq!(body["stream"], true);
            assert_eq!(body["messages"][0]["role"], "system");
            assert_eq!(body["messages"][1]["role"], "user");
            assert!(body["tools"].as_array().is_some_and(|tools| !tools.is_empty()));
            assert!(
                String::from_utf8_lossy(&request_bytes[..body_start])
                    .contains("Authorization: Bearer synthetic-key")
            );

            let body = concat!(
                "data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n",
                "data: {\"choices\":[{\"delta\":{\"content\":\"Synthetic loopback response.\"}}]}\n\n",
                "data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\n",
                "data: [DONE]\n\n"
            );
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            );
            stream.write_all(response.as_bytes()).expect("write fixture response");
            stream.flush().expect("flush fixture response");
        });

        let transport = LocalOpenAiTransport::new(
            &format!("http://127.0.0.1:{port}/v1"),
            Some("synthetic-key".to_owned()),
        )
        .unwrap();
        assert_eq!(transport.request_path(), "/v1/chat/completions");
        let events = transport.stream_chat(&request()).unwrap();
        assert_eq!(
            events,
            vec![
                StreamEvent::TextDelta("Synthetic loopback response.".to_owned()),
                StreamEvent::Done,
            ]
        );
        server.join().unwrap();
    }

    #[test]
    fn transport_rejects_non_loopback_and_https_urls() {
        assert!(matches!(
            LocalOpenAiTransport::new("https://127.0.0.1:8765/v1", None),
            Err(TransportError::UnsupportedScheme(scheme)) if scheme == "https"
        ));
        assert!(matches!(
            LocalOpenAiTransport::new("http://example.com:8765/v1", None),
            Err(TransportError::NonLoopbackHost(host)) if host == "example.com"
        ));
    }

    #[test]
    fn incremental_stream_emits_first_delta_before_later_fixture_write() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).expect("bind loopback fixture");
        let port = listener.local_addr().unwrap().port();
        let (release_sender, release_receiver) = mpsc::channel();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept fixture client");
            let mut request_bytes = Vec::new();
            let mut chunk = [0_u8; 4096];
            loop {
                let read = stream.read(&mut chunk).expect("read request");
                request_bytes.extend_from_slice(&chunk[..read]);
                if request_bytes.windows(4).any(|window| window == b"\r\n\r\n") {
                    let header_end =
                        request_bytes.windows(4).position(|window| window == b"\r\n\r\n").unwrap()
                            + 4;
                    let header = String::from_utf8_lossy(&request_bytes[..header_end]);
                    let length = header
                        .lines()
                        .find_map(|line| line.strip_prefix("Content-Length: "))
                        .unwrap()
                        .parse::<usize>()
                        .unwrap();
                    if request_bytes.len() >= header_end + length {
                        break;
                    }
                }
            }
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n"
            )
            .expect("write response headers");
            stream
                .write_all(b"data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n")
                .expect("write role delta");
            stream
                .write_all(b"data: {\"choices\":[{\"delta\":{\"content\":\"first\"}}]}\n\n")
                .expect("write first delta");
            stream.flush().expect("flush first delta");
            release_receiver.recv().expect("wait for incremental assertion");
            stream
                .write_all(b"data: {\"choices\":[{\"delta\":{\"content\":\"second\"}}]}\n\n")
                .expect("write second delta");
            stream
                .write_all(b"data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\ndata: [DONE]\n\n")
                .expect("write completion");
        });

        let transport =
            LocalOpenAiTransport::new(&format!("http://127.0.0.1:{port}/v1"), None).unwrap();
        let cancellation = CancellationToken::new();
        let mut stream = transport.open_stream(&request(), &cancellation).unwrap();
        assert_eq!(stream.next_event().unwrap(), Some(StreamEvent::TextDelta("first".to_owned())));
        release_sender.send(()).unwrap();
        assert_eq!(stream.next_event().unwrap(), Some(StreamEvent::TextDelta("second".to_owned())));
        assert_eq!(stream.next_event().unwrap(), Some(StreamEvent::Done));
        server.join().unwrap();
    }

    #[test]
    fn incremental_stream_cancellation_interrupts_an_idle_read() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).expect("bind loopback fixture");
        let port = listener.local_addr().unwrap().port();
        let (release_sender, release_receiver) = mpsc::channel();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept fixture client");
            let mut request_bytes = Vec::new();
            let mut chunk = [0_u8; 4096];
            loop {
                let read = stream.read(&mut chunk).expect("read request");
                request_bytes.extend_from_slice(&chunk[..read]);
                if request_bytes.windows(4).any(|window| window == b"\r\n\r\n") {
                    let header_end =
                        request_bytes.windows(4).position(|window| window == b"\r\n\r\n").unwrap()
                            + 4;
                    let header = String::from_utf8_lossy(&request_bytes[..header_end]);
                    let length = header
                        .lines()
                        .find_map(|line| line.strip_prefix("Content-Length: "))
                        .unwrap()
                        .parse::<usize>()
                        .unwrap();
                    if request_bytes.len() >= header_end + length {
                        break;
                    }
                }
            }
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n"
            )
            .expect("write response headers");
            stream
                .write_all(b"data: {\"choices\":[{\"delta\":{\"content\":\"first\"}}]}\n\n")
                .expect("write first delta");
            stream.flush().expect("flush first delta");
            release_receiver.recv().expect("wait for cancellation assertion");
            let _ = stream.write_all(b"data: [DONE]\n\n");
        });

        let transport =
            LocalOpenAiTransport::new(&format!("http://127.0.0.1:{port}/v1"), None).unwrap();
        let cancellation = CancellationToken::new();
        let mut stream = transport.open_stream(&request(), &cancellation).unwrap();
        assert_eq!(stream.next_event().unwrap(), Some(StreamEvent::TextDelta("first".to_owned())));
        let reader = thread::spawn(move || stream.next_event());
        thread::sleep(READ_POLL_INTERVAL * 2);
        cancellation.cancel();
        assert_eq!(reader.join().unwrap(), Err(TransportError::Cancelled));
        release_sender.send(()).unwrap();
        server.join().unwrap();
    }

    #[test]
    fn sse_parser_rejects_malformed_and_incomplete_completion_streams() {
        assert!(matches!(
            parse_sse("data: {not-json}\n\ndata: [DONE]\n\n"),
            Err(TransportError::MalformedSse(_))
        ));
        assert_eq!(parse_sse("data: {\"choices\":[]}\n\n"), Err(TransportError::MissingDone));
        assert_eq!(
            parse_sse("data: {\"choices\":[]}\n\ndata: [DONE]\n\n"),
            Err(TransportError::MissingCompletionData)
        );
    }

    #[test]
    fn sse_parser_emits_typed_tool_call_deltas_and_completes_without_text() {
        let events = parse_sse(concat!(
            "data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n",
            r#"data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","type":"function","function":{"name":"clarify","arguments":"{\"question\":\"syn"}}]}}]}"#,
            "\n\n",
            r#"data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"thetic\"}"}}]}}]}"#,
            "\n\n",
            "data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"tool_calls\"}]}\n\n",
            "data: [DONE]\n\n"
        ))
        .unwrap();
        assert_eq!(
            events,
            vec![
                StreamEvent::ToolCallDelta(ToolCallDelta {
                    index: 0,
                    id: Some("call-1".to_owned()),
                    name: Some("clarify".to_owned()),
                    arguments: Some("{\"question\":\"syn".to_owned()),
                }),
                StreamEvent::ToolCallDelta(ToolCallDelta {
                    index: 0,
                    id: None,
                    name: None,
                    arguments: Some("thetic\"}".to_owned()),
                }),
                StreamEvent::Done,
            ]
        );
    }

    #[test]
    fn sse_parser_accumulates_per_index_tool_calls_with_mixed_text() {
        let events = parse_sse(concat!(
            "data: {\"choices\":[{\"delta\":{\"content\":\"Synthetic handoff\"}}]}\n\n",
            "data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"call-a\",\"function\":{\"name\":\"clarify\",\"arguments\":\"{}\"}}]}}]}\n\n",
            "data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":1,\"id\":\"call-b\",\"function\":{\"name\":\"memory\",\"arguments\":\"[]\"}}]}}]}\n\n",
            "data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"tool_calls\"}]}\n\n",
            "data: [DONE]\n\n"
        ))
        .unwrap();
        assert_eq!(
            events,
            vec![
                StreamEvent::TextDelta("Synthetic handoff".to_owned()),
                StreamEvent::ToolCallDelta(ToolCallDelta {
                    index: 0,
                    id: Some("call-a".to_owned()),
                    name: Some("clarify".to_owned()),
                    arguments: Some("{}".to_owned()),
                }),
                StreamEvent::ToolCallDelta(ToolCallDelta {
                    index: 1,
                    id: Some("call-b".to_owned()),
                    name: Some("memory".to_owned()),
                    arguments: Some("[]".to_owned()),
                }),
                StreamEvent::Done,
            ]
        );
    }

    #[test]
    fn sse_parser_skips_empty_tool_call_objects_without_fabricating_events() {
        let events = parse_sse(concat!(
            "data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"type\":\"function\",\"function\":{}}]}}]}\n\n",
            "data: {\"choices\":[{\"delta\":{\"content\":\"only text\"}}]}\n\n",
            "data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\n",
            "data: [DONE]\n\n"
        ))
        .unwrap();
        assert_eq!(events, vec![StreamEvent::TextDelta("only text".to_owned()), StreamEvent::Done]);
    }

    #[test]
    fn transport_stream_accepts_tool_call_only_completion() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).expect("bind loopback fixture");
        let port = listener.local_addr().unwrap().port();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept fixture client");
            let mut request_bytes = Vec::new();
            let mut chunk = [0_u8; 4096];
            loop {
                let read = stream.read(&mut chunk).expect("read request");
                request_bytes.extend_from_slice(&chunk[..read]);
                if request_bytes.windows(4).any(|window| window == b"\r\n\r\n") {
                    let header_end =
                        request_bytes.windows(4).position(|window| window == b"\r\n\r\n").unwrap()
                            + 4;
                    let header = String::from_utf8_lossy(&request_bytes[..header_end]);
                    let length = header
                        .lines()
                        .find_map(|line| line.strip_prefix("Content-Length: "))
                        .unwrap()
                        .parse::<usize>()
                        .unwrap();
                    if request_bytes.len() >= header_end + length {
                        break;
                    }
                }
            }
            let body = concat!(
                "data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n",
                r#"data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"clarify","arguments":"{\"question\":\"syn"}}]}}]}"#,
                "\n\n",
                r#"data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"thetic\"}"}}]}}]}"#,
                "\n\n",
                "data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"tool_calls\"}]}\n\n",
                "data: [DONE]\n\n"
            );
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            );
            stream.write_all(response.as_bytes()).expect("write fixture response");
            stream.flush().expect("flush fixture response");
        });

        let transport =
            LocalOpenAiTransport::new(&format!("http://127.0.0.1:{port}/v1"), None).unwrap();
        let events = transport.stream_chat(&request()).unwrap();
        assert_eq!(
            events,
            vec![
                StreamEvent::ToolCallDelta(ToolCallDelta {
                    index: 0,
                    id: Some("call-1".to_owned()),
                    name: Some("clarify".to_owned()),
                    arguments: Some("{\"question\":\"syn".to_owned()),
                }),
                StreamEvent::ToolCallDelta(ToolCallDelta {
                    index: 0,
                    id: None,
                    name: None,
                    arguments: Some("thetic\"}".to_owned()),
                }),
                StreamEvent::Done,
            ]
        );
        server.join().unwrap();
    }

    #[test]
    fn embedded_inventory_matches_the_observed_hermes_wire_digest() {
        let tools = hermes_tool_inventory();
        assert_eq!(tools.len(), 31);
        let names = tools
            .iter()
            .filter_map(|tool| tool.get("function")?.get("name")?.as_str())
            .collect::<Vec<_>>();
        assert_eq!(names.first(), Some(&"browser_back"));
        assert!(names.contains(&"clarify"));
        assert_eq!(names.last(), Some(&"tool_call"));

        let digest = canonical_sha256(&serde_json::to_value(tools).unwrap());
        assert_eq!(digest, "b2cbd3f2bf77de3a91cf9a4844b324f6130aab8c72b2924a159cce533f38a220");
    }

    #[test]
    fn advertised_inventory_request_carries_the_observed_tools() {
        let request = ChatRequest::new(
            "palette-model",
            vec![ChatMessage::new("user", "synthetic prompt")],
            hermes_tool_inventory().to_vec(),
        );
        assert_eq!(request.tools.len(), 31);
        let body = serde_json::to_value(WireRequest::from(&request)).unwrap();
        let tools = body.get("tools").and_then(Value::as_array).unwrap();
        assert_eq!(tools.len(), 31);
        assert!(tools.iter().any(|tool| {
            tool.get("function").and_then(|f| f.get("name")).and_then(Value::as_str)
                == Some("clarify")
        }));
    }

    /// Recursively sort object keys so the digest matches the probe's
    /// `sort_keys=True` canonical serialization.
    fn canonical_sort(value: &Value) -> Value {
        match value {
            Value::Object(map) => {
                let mut entries = map
                    .iter()
                    .map(|(key, value)| (key.clone(), canonical_sort(value)))
                    .collect::<Vec<_>>();
                entries.sort_by(|left, right| left.0.cmp(&right.0));
                Value::Object(entries.into_iter().collect())
            }
            Value::Array(items) => Value::Array(items.iter().map(canonical_sort).collect()),
            other => other.clone(),
        }
    }

    fn canonical_sha256(value: &Value) -> String {
        use sha2::{Digest, Sha256};
        let encoded = serde_json::to_string(&canonical_sort(value)).expect("canonical JSON");
        let digest = Sha256::digest(encoded.as_bytes());
        digest.iter().map(|byte| format!("{byte:02x}")).collect()
    }
}
