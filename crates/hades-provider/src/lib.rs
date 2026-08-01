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
    time::Duration,
};

use serde::Serialize;
use serde_json::Value;

pub const DEFAULT_MAX_TOKENS: u32 = 65_536;
pub const DEFAULT_TIMEOUT: Duration = Duration::from_secs(10);

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
pub enum StreamEvent {
    TextDelta(String),
    Done,
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
        let body = WireRequest::from(request);
        let body = serde_json::to_vec(&body)
            .map_err(|error| TransportError::Serialization(error.to_string()))?;
        let mut stream = TcpStream::connect_timeout(&self.address, self.timeout)
            .map_err(|error| TransportError::Io(error.to_string()))?;
        stream
            .set_read_timeout(Some(self.timeout))
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

        let mut response = Vec::new();
        stream.read_to_end(&mut response).map_err(|error| TransportError::Io(error.to_string()))?;
        parse_http_sse(&response)
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

fn parse_http_sse(response: &[u8]) -> Result<Vec<StreamEvent>, TransportError> {
    let separator =
        response.windows(4).position(|window| window == b"\r\n\r\n").ok_or_else(|| {
            TransportError::InvalidResponse("missing HTTP header boundary".to_owned())
        })?;
    let (header_bytes, body) = response.split_at(separator + 4);
    let header = std::str::from_utf8(header_bytes)
        .map_err(|error| TransportError::InvalidResponse(error.to_string()))?;
    let mut status_parts = header.lines().next().unwrap_or_default().split_whitespace();
    let _http_version = status_parts.next();
    let status = status_parts
        .next()
        .ok_or_else(|| TransportError::InvalidResponse("missing HTTP status".to_owned()))?
        .parse::<u16>()
        .map_err(|_| TransportError::InvalidResponse("invalid HTTP status".to_owned()))?;
    if status != 200 {
        let body = String::from_utf8_lossy(body).trim().to_owned();
        return Err(TransportError::HttpStatus { status, body });
    }
    let content_type = header.lines().find_map(|line| {
        let (name, value) = line.split_once(':')?;
        (name.eq_ignore_ascii_case("content-type")).then_some(value.trim())
    });
    if !content_type.is_some_and(|value| value.starts_with("text/event-stream")) {
        return Err(TransportError::InvalidResponse("expected text/event-stream".to_owned()));
    }
    parse_sse(std::str::from_utf8(body).map_err(|error| {
        TransportError::InvalidResponse(format!("response body is not UTF-8: {error}"))
    })?)
}

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
    if !events.iter().any(|event| matches!(event, StreamEvent::TextDelta(_))) {
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
    let text = payload
        .get("choices")
        .and_then(Value::as_array)
        .and_then(|choices| choices.first())
        .and_then(|choice| choice.get("delta"))
        .and_then(|delta| delta.get("content"))
        .and_then(Value::as_str);
    Ok(text.filter(|value| !value.is_empty()).map(|value| StreamEvent::TextDelta(value.to_owned())))
}

#[cfg(test)]
mod tests {
    use std::{
        io::{Read, Write},
        net::TcpListener,
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
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            )
            .expect("write fixture response");
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
}
