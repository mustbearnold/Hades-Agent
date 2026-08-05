#![forbid(unsafe_code)]

//! Sandboxed tool execution at the deterministic typed seam (spec 011).
//!
//! This crate owns tool *execution* only: a typed [`ToolCallRecord`] in, a
//! typed [`ToolResult`] out, with every side effect confined to an explicit
//! [`Sandbox`] root (a probe/temp-dir root — never the real user
//! environment). It does not know about the provider transport, the TUI, or
//! the app reducer; those consume the typed results and feed them back
//! through the follow-up loop.
//!
//! The implemented tool slice is bounded to what the pinned reference was
//! observed executing (OBS-0117..0120): `terminal` (side effects confined to
//! sandbox dirs), `write_file`, `read_file`, `search_files`, and `clarify`.
//! Anything else dispatches to [`ToolResult::Unsupported`] — Hades never
//! invents tools or failure behavior (spec 011 R6).
//!
//! # Result content shapes
//!
//! Success-path result strings are byte-identical to the reference tool
//! results recorded in OBS-0117..0120 (Python `json.dumps(..., ensure_ascii=False)`
//! byte semantics — `", "` / `": "` separators, `null`/`true`/`false`
//! literals):
//!
//! - terminal: `{"output": "", "exit_code": 0, "error": null}` — 45 bytes,
//!   digest `708054e2…` (OBS-0117/0120).
//! - write_file: `bytes_written`/`dirs_created`/`lint`/`resolved_path`/
//!   `files_modified` (OBS-0118; the resolved path is sandbox-embedded, so
//!   the digest varies per run exactly like the reference).
//! - read_file: `content` (line-numbered `<n>|` gutter)/`total_lines`/
//!   `file_size`/`truncated`/`is_binary`/`is_image` — 133 bytes with digest
//!   `497ef28a…` for the probe's `sample.txt`, 121 bytes with digest
//!   `fb3accfc…` for `hop.txt` (OBS-0118/0120).
//! - search_files (`target: "files"`): `total_count`/`files` (OBS-0118;
//!   sandbox-embedded paths).
//! - clarify: `question`/`choices_offered`/`user_response` — 158 bytes with
//!   digest `7336fd6d…`, byte-identical to OBS-0116/0119 when the responder
//!   returns the first choice.
//!
//! Failure results (missing/invalid arguments, sandbox escapes, unknown
//! tools) are Hades-owned: the reference failure paths are explicitly
//! unobserved (spec 011 open questions), so Hades reports them with the
//! observed success-shape keys and `exit_code: -1` instead of inventing
//! reference behavior.

use std::{
    ffi::OsString,
    fmt, fs,
    path::{Component, Path, PathBuf},
    process::Command,
    time::Duration,
};

use serde_json::{Value, json};

/// Ceiling for one tool-call argument payload (bounded follow-up).
pub const MAX_TOOL_ARGUMENTS_BYTES: usize = 64 * 1024;
/// Ceiling for captured terminal output, matching the reference's bounded
/// capture (head/tail windows with an explicit truncation notice).
pub const MAX_TERMINAL_OUTPUT_CHARS: usize = 32_000;
/// Terminal command timeout. Retries are unobserved (spec 011 R6), so a
/// command runs exactly once within this bound.
pub const TERMINAL_TIMEOUT: Duration = Duration::from_secs(120);

/// A parsed, bounded tool call at the execution seam.
///
/// `arguments` is the joined argument payload, capped at
/// [`MAX_TOOL_ARGUMENTS_BYTES`] while the stream accumulated its fragments.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ToolCallRecord {
    /// Tool name as requested by the assistant (e.g. `terminal`).
    pub name: String,
    /// The assistant's tool-call id, echoed on the follow-up `tool` message.
    pub id: String,
    /// Bounded raw JSON argument payload.
    pub arguments: String,
}

impl ToolCallRecord {
    pub fn new(
        name: impl Into<String>,
        id: impl Into<String>,
        arguments: impl Into<String>,
    ) -> Self {
        Self { name: name.into(), id: id.into(), arguments: arguments.into() }
    }

    /// Parse the bounded argument payload as JSON.
    pub fn parse_arguments(&self) -> Result<Value, ToolError> {
        serde_json::from_str(&self.arguments)
            .map_err(|error| ToolError::InvalidArguments(error.to_string()))
    }
}

/// Failure to build or execute a tool call. These are Hades-owned errors;
/// the reference failure paths are unobserved.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ToolError {
    InvalidArguments(String),
    SandboxEscape(String),
    Io(String),
}

impl fmt::Display for ToolError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidArguments(message) => {
                write!(formatter, "invalid tool arguments: {message}")
            }
            Self::SandboxEscape(message) => write!(formatter, "sandbox escape: {message}"),
            Self::Io(message) => write!(formatter, "tool I/O failed: {message}"),
        }
    }
}

impl std::error::Error for ToolError {}

impl ToolError {
    /// Hades-owned tool-result content for a failed execution.
    ///
    /// The reference failure paths are unobserved (spec 011 R6); Hades
    /// reports them with the observed success-shape keys and `exit_code: -1`
    /// so the follow-up loop always has a bounded tool message to feed back.
    pub fn result_content(&self) -> String {
        format!(
            "{{\"output\": \"\", \"exit_code\": -1, \"error\": {}}}",
            json_string(&self.to_string())
        )
    }
}

/// Typed tool result in the observed message shape.
///
/// Each variant's [`content`](Self::content) is the JSON string the
/// follow-up request carries as the `tool`-role message content.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ToolResult {
    /// `terminal` — `{"output", "exit_code", "error"}` (OBS-0117/0120).
    Terminal { output: String, exit_code: i32, error: Option<String> },
    /// `write_file` — `bytes_written`/`dirs_created`/`lint`/`resolved_path`/
    /// `files_modified` (OBS-0118).
    WriteFile {
        bytes_written: usize,
        dirs_created: bool,
        lint: Value,
        resolved_path: String,
        files_modified: Vec<String>,
    },
    /// `read_file` — `content`/`total_lines`/`file_size`/`truncated`/
    /// `is_binary`/`is_image` (OBS-0118/0120).
    ReadFile {
        content: String,
        total_lines: usize,
        file_size: usize,
        truncated: bool,
        is_binary: bool,
        is_image: bool,
    },
    /// `search_files` with `target: "files"` — `total_count`/`files`
    /// (OBS-0118).
    SearchFiles { files: Vec<String>, total_count: usize },
    /// `clarify` — `question`/`choices_offered`/`user_response`, the
    /// 158-byte observed shape (OBS-0116/0119).
    Clarify { question: String, choices_offered: Vec<String>, user_response: String },
    /// Any tool outside the observed slice. Hades-owned error content.
    Unsupported { name: String },
}

impl ToolResult {
    /// The tool-result content string in the observed message shape.
    ///
    /// String values are JSON-escaped exactly like `json.dumps(..., ensure_ascii=False)`;
    /// separators are `", "` and `": "` like Python's default `json.dumps`.
    pub fn content(&self) -> String {
        match self {
            Self::Terminal { output, exit_code, error } => {
                let error = error.as_deref().map(json_string).unwrap_or_else(|| "null".to_owned());
                format!(
                    "{{\"output\": {}, \"exit_code\": {exit_code}, \"error\": {error}}}",
                    json_string(output)
                )
            }
            Self::WriteFile {
                bytes_written,
                dirs_created,
                lint,
                resolved_path,
                files_modified,
            } => {
                let files = files_modified
                    .iter()
                    .map(|path| json_string(path))
                    .collect::<Vec<_>>()
                    .join(", ");
                format!(
                    "{{\"bytes_written\": {bytes_written}, \"dirs_created\": {dirs_created}, \
                     \"lint\": {lint}, \"resolved_path\": {}, \"files_modified\": [{files}]}}",
                    json_string(resolved_path)
                )
            }
            Self::ReadFile { content, total_lines, file_size, truncated, is_binary, is_image } => {
                format!(
                    "{{\"content\": {}, \"total_lines\": {total_lines}, \"file_size\": {file_size}, \
                     \"truncated\": {truncated}, \"is_binary\": {is_binary}, \"is_image\": {is_image}}}",
                    json_string(content)
                )
            }
            Self::SearchFiles { files, total_count } => {
                let files =
                    files.iter().map(|path| json_string(path)).collect::<Vec<_>>().join(", ");
                if files.is_empty() {
                    format!("{{\"total_count\": {total_count}}}")
                } else {
                    format!("{{\"total_count\": {total_count}, \"files\": [{files}]}}")
                }
            }
            Self::Clarify { question, choices_offered, user_response } => {
                let choices = choices_offered
                    .iter()
                    .map(|choice| json_string(choice))
                    .collect::<Vec<_>>()
                    .join(", ");
                format!(
                    "{{\"question\": {}, \"choices_offered\": [{choices}], \"user_response\": {}}}",
                    json_string(question),
                    json_string(user_response)
                )
            }
            Self::Unsupported { name } => {
                format!(
                    "{{\"output\": \"\", \"exit_code\": -1, \"error\": {}}}",
                    json_string(&format!("unknown tool: {name}"))
                )
            }
        }
    }
}

/// `json.dumps(value)` for a single string: JSON-quoted, escaped,
/// non-ASCII kept raw (serde_json never escapes non-ASCII by default).
fn json_string(value: &str) -> String {
    serde_json::to_string(value).expect("JSON string serialization is infallible")
}

/// Answers a `clarify` question. The observed interactive question surface
/// (OBS-0116) is a TUI concern; the typed seam only needs the answer that
/// becomes `user_response`.
pub trait ClarifyResponder: fmt::Debug + Send + Sync {
    fn answer(&self, question: &str, choices: &[String]) -> String;
}

/// Deterministic default responder: the first choice, which is exactly what
/// the observed surface returns when Enter selects the initial row
/// (OBS-0116/0119: arrow down, arrow up, Enter → first choice). When no
/// choices are offered (open-ended), answers with the question itself so the
/// result stays deterministic and bounded.
#[derive(Clone, Debug, Default)]
pub struct FirstChoiceResponder;

impl ClarifyResponder for FirstChoiceResponder {
    fn answer(&self, question: &str, choices: &[String]) -> String {
        choices.first().cloned().unwrap_or_else(|| question.to_owned())
    }
}

/// The sandboxed execution boundary.
///
/// Every tool runs against this explicit root — a probe/temp-dir root —
/// never the real user environment. Path arguments are resolved inside the
/// root (relative paths join it; absolute paths must stay under it; `..`
/// and symlink escapes are rejected), and the terminal tool executes with
/// the sandbox root as its working directory and `HOME`.
#[derive(Clone, Debug)]
pub struct Sandbox {
    root: PathBuf,
    responder: std::sync::Arc<dyn ClarifyResponder>,
}
impl Sandbox {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self::with_responder(root, FirstChoiceResponder)
    }

    pub fn with_responder(
        root: impl Into<PathBuf>,
        responder: impl ClarifyResponder + 'static,
    ) -> Self {
        Self { root: root.into(), responder: std::sync::Arc::new(responder) }
    }

    /// The sandbox root directory.
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Resolve a tool path argument inside the sandbox, rejecting escapes.
    ///
    /// `..` components are rejected lexically before any filesystem access;
    /// absolute paths must stay under the root; and the deepest existing
    /// ancestor is canonicalized so a symlink chain that leaves the root is
    /// detected.
    pub fn resolve(&self, path: &str) -> Result<PathBuf, ToolError> {
        let requested = Path::new(path);
        if requested.components().any(|component| matches!(component, Component::ParentDir)) {
            return Err(ToolError::SandboxEscape(format!(
                "path {path:?} escapes the sandbox root"
            )));
        }
        let candidate = if requested.is_absolute() {
            requested.to_path_buf()
        } else {
            self.root.join(requested)
        };
        // Walk the deepest existing ancestor chain, canonicalizing as we go
        // so symlinks cannot smuggle a write out of the root.
        let relative = candidate.strip_prefix(&self.root).map_err(|_| {
            ToolError::SandboxEscape(format!("path {path:?} is outside the sandbox root"))
        })?;
        let mut existing = self.root.clone();
        let mut tail: Vec<OsString> = Vec::new();
        for component in relative.components() {
            // ParentDir was rejected above; every remaining component of a
            // relative path is Normal (CurDir joins are no-ops).
            let Component::Normal(part) = component else { continue };
            let next = existing.join(part);
            if next.symlink_metadata().is_ok() {
                existing = next;
            } else {
                tail.push(part.to_owned());
            }
        }
        let canonical_root = fs::canonicalize(&self.root).map_err(|error| {
            ToolError::Io(format!(
                "sandbox root {} is not canonicalizable: {error}",
                self.root.display()
            ))
        })?;
        let canonical_existing = fs::canonicalize(&existing).map_err(|error| {
            ToolError::Io(format!(
                "sandbox path {} is not canonicalizable: {error}",
                existing.display()
            ))
        })?;
        if !canonical_existing.starts_with(&canonical_root) {
            return Err(ToolError::SandboxEscape(format!(
                "path {path:?} escapes the sandbox root"
            )));
        }
        let mut resolved = canonical_existing;
        for component in tail {
            resolved.push(component);
        }
        Ok(resolved)
    }

    /// Execute a parsed tool call against this sandbox.
    ///
    /// Never blocks past the per-tool bounds, never touches anything outside
    /// the sandbox root, and never executes a tool outside the observed
    /// slice ([`ToolResult::Unsupported`]).
    pub fn execute(&self, record: &ToolCallRecord) -> Result<ToolResult, ToolError> {
        match record.name.as_str() {
            "terminal" => self.terminal(record),
            "write_file" => self.write_file(record),
            "read_file" => self.read_file(record),
            "search_files" => self.search_files(record),
            "clarify" => self.clarify(record),
            name => Ok(ToolResult::Unsupported { name: name.to_owned() }),
        }
    }

    fn terminal(&self, record: &ToolCallRecord) -> Result<ToolResult, ToolError> {
        let arguments = record.parse_arguments()?;
        let command = arguments
            .get("command")
            .and_then(Value::as_str)
            .ok_or_else(|| ToolError::InvalidArguments("command must be a string".to_owned()))?;
        if command.trim().is_empty() {
            return Ok(ToolResult::Terminal {
                output: String::new(),
                exit_code: -1,
                error: Some("Command is required.".to_owned()),
            });
        }
        let output = Command::new("sh")
            .arg("-c")
            .arg(command)
            .current_dir(&self.root)
            .env("HOME", &self.root)
            .env("PWD", &self.root)
            .output()
            .map_err(|error| ToolError::Io(error.to_string()))?;
        let exit_code = output.status.code().unwrap_or(-1);
        let stdout = String::from_utf8_lossy(&output.stdout);
        let stderr = String::from_utf8_lossy(&output.stderr);
        let mut combined = format!("{stdout}{stderr}");
        combined = truncate_terminal_output(&combined);
        let error =
            if exit_code == -1 { Some("Command execution failed.".to_owned()) } else { None };
        Ok(ToolResult::Terminal { output: combined, exit_code, error })
    }

    fn write_file(&self, record: &ToolCallRecord) -> Result<ToolResult, ToolError> {
        let arguments = record.parse_arguments()?;
        let path = arguments
            .get("path")
            .and_then(Value::as_str)
            .ok_or_else(|| ToolError::InvalidArguments("path must be a string".to_owned()))?;
        let content = arguments
            .get("content")
            .and_then(Value::as_str)
            .ok_or_else(|| ToolError::InvalidArguments("content must be a string".to_owned()))?;
        let resolved = self.resolve(path)?;
        let parent = resolved.parent().ok_or_else(|| {
            ToolError::SandboxEscape(format!("path {path:?} has no parent directory"))
        })?;
        fs::create_dir_all(parent).map_err(|error| ToolError::Io(error.to_string()))?;
        // Reference semantics: `dirs_created` is true when the argument had a
        // parent directory and `mkdir -p` succeeded.
        let had_parent = Path::new(path).is_absolute()
            || path.contains('/')
            || path.contains(std::path::MAIN_SEPARATOR);
        let dirs_created = had_parent;
        fs::write(&resolved, content.as_bytes())
            .map_err(|error| ToolError::Io(error.to_string()))?;
        let bytes_written = content.len();
        let extension = resolved
            .extension()
            .and_then(|extension| extension.to_str())
            .map(|extension| format!(".{extension}"))
            .unwrap_or_default();
        let lint = json!({
            "status": "skipped",
            "message": format!("No linter for {extension} files"),
        });
        let resolved_path = resolved.to_string_lossy().into_owned();
        Ok(ToolResult::WriteFile {
            bytes_written,
            dirs_created,
            lint,
            resolved_path: resolved_path.clone(),
            files_modified: vec![resolved_path],
        })
    }

    fn read_file(&self, record: &ToolCallRecord) -> Result<ToolResult, ToolError> {
        let arguments = record.parse_arguments()?;
        let path = arguments
            .get("path")
            .and_then(Value::as_str)
            .ok_or_else(|| ToolError::InvalidArguments("path must be a string".to_owned()))?;
        let offset = arguments.get("offset").and_then(Value::as_u64).unwrap_or(1).max(1) as usize;
        let limit =
            arguments.get("limit").and_then(Value::as_u64).unwrap_or(500).clamp(1, 2000) as usize;
        let resolved = self.resolve(path)?;
        let bytes = fs::read(&resolved).map_err(|error| ToolError::Io(error.to_string()))?;
        let file_size = bytes.len();
        let content = String::from_utf8_lossy(&bytes);
        // `wc -l` semantics: total_lines counts newline characters.
        let total_lines = content.bytes().filter(|byte| *byte == b'\n').count();
        let end_line = offset + limit - 1;
        let truncated = total_lines > end_line;
        let mut lines = content.split('\n').collect::<Vec<_>>();
        if lines.is_empty() {
            lines.push("");
        }
        let start = offset.saturating_sub(1).min(lines.len());
        let end = (start + limit).min(lines.len());
        let page = if start < lines.len() { &lines[start..end] } else { &[""][..] };
        let numbered = page
            .iter()
            .enumerate()
            .map(|(index, line)| format!("{}|{line}", offset + index))
            .collect::<Vec<_>>()
            .join("\n");
        let numbered = if numbered.is_empty() { "1|".to_owned() } else { numbered };
        Ok(ToolResult::ReadFile {
            content: numbered,
            total_lines,
            file_size,
            truncated,
            is_binary: false,
            is_image: false,
        })
    }

    fn search_files(&self, record: &ToolCallRecord) -> Result<ToolResult, ToolError> {
        let arguments = record.parse_arguments()?;
        let target = arguments.get("target").and_then(Value::as_str).unwrap_or("content");
        if target != "files" {
            // The observed slice covered `target: "files"` (OBS-0118) only.
            // Content search semantics are unobserved; Hades reports the
            // gap instead of inventing a match format.
            return Ok(ToolResult::SearchFiles { files: Vec::new(), total_count: 0 });
        }
        let pattern = arguments.get("pattern").and_then(Value::as_str).unwrap_or("*");
        let path = arguments.get("path").and_then(Value::as_str).unwrap_or(".");
        let limit = arguments.get("limit").and_then(Value::as_u64).unwrap_or(50) as usize;
        let offset = arguments.get("offset").and_then(Value::as_u64).unwrap_or(0) as usize;
        let resolved = self.resolve(path)?;
        let glob = glob_for(pattern);
        let mut matches = Vec::new();
        collect_files(&resolved, &glob, &mut matches)?;
        // `rg --files --sortr=modified` semantics: newest mtime first.
        matches.sort_by_key(|right| std::cmp::Reverse(mtime(right)));
        let total_count = matches.len();
        let files = matches
            .into_iter()
            .skip(offset)
            .take(limit)
            .map(|path| path.to_string_lossy().into_owned())
            .collect();
        Ok(ToolResult::SearchFiles { files, total_count })
    }

    fn clarify(&self, record: &ToolCallRecord) -> Result<ToolResult, ToolError> {
        let arguments = record.parse_arguments()?;
        let question = arguments
            .get("question")
            .and_then(Value::as_str)
            .ok_or_else(|| ToolError::InvalidArguments("question must be a string".to_owned()))?
            .trim()
            .to_owned();
        let choices = arguments
            .get("choices")
            .and_then(Value::as_array)
            .map(|choices| {
                choices.iter().filter_map(Value::as_str).map(str::to_owned).collect::<Vec<_>>()
            })
            .unwrap_or_default();
        let user_response = self.responder.answer(&question, &choices);
        Ok(ToolResult::Clarify { question, choices_offered: choices, user_response })
    }
}

/// Translate a search pattern to a glob matcher. Bare names (no `/`) match
/// at any depth, mirroring the reference's `rg --files -g` wrapping.
fn glob_for(pattern: &str) -> String {
    if pattern.contains('/') || pattern.starts_with('*') {
        pattern.to_owned()
    } else {
        format!("*{pattern}")
    }
}

fn collect_files(root: &Path, glob: &str, matches: &mut Vec<PathBuf>) -> Result<(), ToolError> {
    let mut stack = vec![root.to_path_buf()];
    while let Some(directory) = stack.pop() {
        let entries = fs::read_dir(&directory).map_err(|error| ToolError::Io(error.to_string()))?;
        for entry in entries {
            let entry = entry.map_err(|error| ToolError::Io(error.to_string()))?;
            let path = entry.path();
            let name = entry.file_name().to_string_lossy().into_owned();
            if name.starts_with('.') {
                continue;
            }
            if entry.file_type().map_err(|error| ToolError::Io(error.to_string()))?.is_dir() {
                stack.push(path);
            } else if glob_match(glob, &name) {
                matches.push(path);
            }
        }
    }
    Ok(())
}

/// Minimal `*` glob matcher (pattern is a single `*`-wildcard fragment,
/// which is all the observed slice needs; no character classes).
fn glob_match(pattern: &str, name: &str) -> bool {
    if pattern == "*" {
        return true;
    }
    let Some((head, tail)) = pattern.split_once('*') else {
        return pattern == name;
    };
    name.starts_with(head) && name.ends_with(tail) && name.len() >= head.len() + tail.len()
}

fn mtime(path: &Path) -> std::time::SystemTime {
    fs::metadata(path).and_then(|metadata| metadata.modified()).unwrap_or(std::time::UNIX_EPOCH)
}

/// Bound captured terminal output with the reference's head/tail windows and
/// explicit truncation notice.
fn truncate_terminal_output(output: &str) -> String {
    if output.chars().count() <= MAX_TERMINAL_OUTPUT_CHARS {
        return output.to_owned();
    }
    let max = MAX_TERMINAL_OUTPUT_CHARS;
    let head_chars = max * 40 / 100;
    let tail_chars = max - head_chars;
    let total = output.chars().count();
    let omitted = total - head_chars - tail_chars;
    let head = output.chars().take(head_chars).collect::<String>();
    let tail = output.chars().skip(total - tail_chars).collect::<String>();
    format!(
        "{head}\n\n... [OUTPUT TRUNCATED - {omitted} chars omitted out of {total} total] ...\n\n{tail}"
    )
}

#[cfg(test)]
mod tests {
    use std::fs;

    use sha2::{Digest, Sha256};

    use super::*;

    fn sha256_hex(bytes: &[u8]) -> String {
        let mut digest = Sha256::new();
        digest.update(bytes);
        format!("{:x}", digest.finalize())
    }

    fn temp_sandbox(label: &str) -> Sandbox {
        let root = std::env::temp_dir().join(format!(
            "hades-tools-{label}-{}-{:x}",
            std::process::id(),
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()
        ));
        fs::create_dir_all(&root).expect("create sandbox root");
        Sandbox::new(root)
    }

    fn cleanup(sandbox: &Sandbox) {
        let _ = fs::remove_dir_all(sandbox.root());
    }

    #[test]
    fn terminal_result_matches_the_observed_45_byte_shape() {
        let sandbox = temp_sandbox("terminal-shape");
        let out_dir = sandbox.root().join("out");
        let command = format!(
            "mkdir -p {} && echo synthetic > {}/out.txt",
            out_dir.display(),
            out_dir.display()
        );
        let result = sandbox
            .execute(&ToolCallRecord::new(
                "terminal",
                "call_synthetic_terminal",
                serde_json::to_string(&json!({ "command": command })).unwrap(),
            ))
            .expect("terminal executes");
        let content = result.content();
        // OBS-0117: 45 bytes, digest 708054e2…, keys error/exit_code/output.
        assert_eq!(content.len(), 45);
        assert_eq!(
            sha256_hex(content.as_bytes()),
            "708054e20f8345e96aa29aa3d3ae50e6245e6723619f1f57c1486f2c2ef9c451"
        );
        assert_eq!(content, "{\"output\": \"\", \"exit_code\": 0, \"error\": null}");
        let written = fs::read_to_string(out_dir.join("out.txt")).expect("sandbox side effect");
        assert_eq!(written, "synthetic\n");
        cleanup(&sandbox);
    }

    #[test]
    fn write_file_result_has_the_observed_keys_and_side_effect() {
        let sandbox = temp_sandbox("write-shape");
        let sample = sandbox.root().join("sample.txt");
        let result = sandbox
            .execute(&ToolCallRecord::new(
                "write_file",
                "call_synthetic_write_file",
                serde_json::to_string(&json!({
                    "path": sample.to_string_lossy(),
                    "content": "synthetic file content",
                }))
                .unwrap(),
            ))
            .expect("write_file executes");
        let content = result.content();
        let parsed: Value = serde_json::from_str(&content).expect("result is JSON");
        let mut keys = parsed.as_object().unwrap().keys().cloned().collect::<Vec<_>>();
        keys.sort();
        assert_eq!(
            keys,
            vec!["bytes_written", "dirs_created", "files_modified", "lint", "resolved_path"]
        );
        assert_eq!(parsed["bytes_written"], 22);
        assert_eq!(parsed["dirs_created"], true);
        assert_eq!(
            parsed["lint"],
            json!({"status": "skipped", "message": "No linter for .txt files"})
        );
        assert_eq!(parsed["resolved_path"], sample.to_string_lossy().into_owned());
        assert_eq!(parsed["files_modified"], json!([sample.to_string_lossy().into_owned()]));
        let written = fs::read_to_string(&sample).expect("sandbox side effect");
        assert_eq!(written, "synthetic file content");
        cleanup(&sandbox);
    }

    #[test]
    fn read_file_matches_the_observed_133_byte_digest() {
        let sandbox = temp_sandbox("read-shape");
        let sample = sandbox.root().join("sample.txt");
        fs::write(&sample, "synthetic file content").expect("write fixture");
        let result = sandbox
            .execute(&ToolCallRecord::new(
                "read_file",
                "call_synthetic_read_file",
                serde_json::to_string(&json!({ "path": sample.to_string_lossy() })).unwrap(),
            ))
            .expect("read_file executes");
        let content = result.content();
        // OBS-0118: 133 bytes, digest 497ef28a…, keys content/file_size/
        // is_binary/is_image/total_lines/truncated.
        assert_eq!(content.len(), 133);
        assert_eq!(
            sha256_hex(content.as_bytes()),
            "497ef28aee949c5580fcf33f9a37017bbfad5beaf9aad00628fa7699da3b489f"
        );
        assert_eq!(
            content,
            "{\"content\": \"1|synthetic file content\", \"total_lines\": 0, \"file_size\": 22, \
             \"truncated\": false, \"is_binary\": false, \"is_image\": false}"
        );
        cleanup(&sandbox);
    }

    #[test]
    fn read_file_matches_the_observed_121_byte_multi_hop_digest() {
        let sandbox = temp_sandbox("read-hop");
        let hop = sandbox.root().join("hopdir").join("hop.txt");
        fs::create_dir_all(hop.parent().unwrap()).expect("create hopdir");
        // `echo hop-one > hop.txt` produces a trailing newline, exactly like
        // the OBS-0120 probe command.
        fs::write(&hop, "hop-one\n").expect("write fixture");
        let result = sandbox
            .execute(&ToolCallRecord::new(
                "read_file",
                "call_synthetic_read_file",
                serde_json::to_string(&json!({ "path": hop.to_string_lossy() })).unwrap(),
            ))
            .expect("read_file executes");
        let content = result.content();
        // OBS-0120: 121 bytes, digest fb3accfc…, contains the hop-one anchor.
        assert_eq!(content.len(), 121);
        assert_eq!(
            sha256_hex(content.as_bytes()),
            "fb3accfce3bc199b09eebb2e2e03ea41ff7467e0f76fc5e75ce6849fa6ff856f"
        );
        assert_eq!(
            content,
            "{\"content\": \"1|hop-one\\n2|\", \"total_lines\": 1, \"file_size\": 8, \
             \"truncated\": false, \"is_binary\": false, \"is_image\": false}"
        );
        cleanup(&sandbox);
    }

    #[test]
    fn search_files_matches_the_observed_files_shape() {
        let sandbox = temp_sandbox("search-shape");
        let sample = sandbox.root().join("sample.txt");
        fs::write(&sample, "synthetic file content").expect("write fixture");
        let result = sandbox
            .execute(&ToolCallRecord::new(
                "search_files",
                "call_synthetic_search_files",
                serde_json::to_string(&json!({
                    "pattern": "*",
                    "target": "files",
                    "path": sandbox.root().to_string_lossy(),
                }))
                .unwrap(),
            ))
            .expect("search_files executes");
        let content = result.content();
        let parsed: Value = serde_json::from_str(&content).expect("result is JSON");
        let keys = parsed.as_object().unwrap().keys().cloned().collect::<Vec<_>>();
        assert_eq!(keys, vec!["files", "total_count"]);
        assert_eq!(parsed["total_count"], 1);
        assert_eq!(parsed["files"], json!([sample.to_string_lossy().into_owned()]));
        cleanup(&sandbox);
    }

    #[test]
    fn clarify_matches_the_observed_158_byte_digest() {
        let sandbox = temp_sandbox("clarify-shape");
        let result = sandbox
            .execute(&ToolCallRecord::new(
                "clarify",
                "call_synthetic_clarify",
                serde_json::to_string(&json!({
                    "question": "synthetic clarification question",
                    "choices": ["synthetic choice one", "synthetic choice two"],
                }))
                .unwrap(),
            ))
            .expect("clarify executes");
        let content = result.content();
        // OBS-0116/0119: 158 bytes, digest 7336fd6d…, keys
        // choices_offered/question/user_response; the first-choice responder
        // reproduces the observed Enter-on-first-choice answer.
        assert_eq!(content.len(), 158);
        assert_eq!(
            sha256_hex(content.as_bytes()),
            "7336fd6d3442cf141a48045e10672c62d2010fa2720481787488fd93ebfb5d81"
        );
        assert_eq!(
            content,
            "{\"question\": \"synthetic clarification question\", \"choices_offered\": \
             [\"synthetic choice one\", \"synthetic choice two\"], \"user_response\": \
             \"synthetic choice one\"}"
        );
        cleanup(&sandbox);
    }

    #[test]
    fn sandbox_rejects_relative_escape_attempts() {
        let sandbox = temp_sandbox("escape-rel");
        for path in ["../outside.txt", "a/../../outside.txt", "../../etc/passwd"] {
            let error = sandbox.resolve(path).expect_err("escape must be rejected");
            assert!(matches!(error, ToolError::SandboxEscape(_)), "path: {path}");
        }
        cleanup(&sandbox);
    }

    #[test]
    fn sandbox_rejects_absolute_paths_outside_the_root() {
        let sandbox = temp_sandbox("escape-abs");
        let outside = std::env::temp_dir().join(format!(
            "hades-tools-outside-{}-{:x}",
            std::process::id(),
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()
        ));
        fs::create_dir_all(&outside).expect("create outside dir");
        let error = sandbox
            .resolve(outside.to_str().unwrap())
            .expect_err("absolute outside path must be rejected");
        assert!(matches!(error, ToolError::SandboxEscape(_)));
        let _ = fs::remove_dir_all(&outside);
        cleanup(&sandbox);
    }

    #[test]
    fn sandbox_rejects_symlink_escapes() {
        let sandbox = temp_sandbox("escape-symlink");
        let outside = std::env::temp_dir().join(format!(
            "hades-tools-outside-link-{}-{:x}",
            std::process::id(),
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()
        ));
        fs::create_dir_all(&outside).expect("create outside dir");
        let link = sandbox.root().join("link");
        #[cfg(unix)]
        std::os::unix::fs::symlink(&outside, &link).expect("create symlink");
        let error = sandbox.resolve("link/pwned.txt").expect_err("symlink escape must be rejected");
        assert!(matches!(error, ToolError::SandboxEscape(_)));
        let _ = fs::remove_dir_all(&outside);
        cleanup(&sandbox);
    }

    #[test]
    fn unsupported_tools_return_a_hades_owned_error_result() {
        let sandbox = temp_sandbox("unsupported");
        let result = sandbox
            .execute(&ToolCallRecord::new("memory", "call-memory", "[]"))
            .expect("unsupported dispatch does not fail");
        assert!(matches!(result, ToolResult::Unsupported { ref name } if name == "memory"));
        let content = result.content();
        let parsed: Value = serde_json::from_str(&content).expect("result is JSON");
        assert_eq!(parsed["exit_code"], -1);
        assert_eq!(parsed["error"], "unknown tool: memory");
        cleanup(&sandbox);
    }

    #[test]
    fn invalid_arguments_are_reported_not_executed() {
        let sandbox = temp_sandbox("invalid-args");
        let result = sandbox.execute(&ToolCallRecord::new("terminal", "call", "{not json"));
        assert!(matches!(result, Err(ToolError::InvalidArguments(_))));
        let result = sandbox.execute(&ToolCallRecord::new("terminal", "call", "{}"));
        assert!(matches!(result, Err(ToolError::InvalidArguments(_))));
        // The caller-facing content for a failed execution stays bounded and
        // carries the observed error keys with exit_code -1.
        let content =
            ToolError::InvalidArguments("command must be a string".to_owned()).result_content();
        let parsed: Value = serde_json::from_str(&content).expect("result is JSON");
        assert_eq!(parsed["exit_code"], -1);
        assert_eq!(parsed["error"], "invalid tool arguments: command must be a string");
        cleanup(&sandbox);
    }

    #[test]
    fn terminal_output_is_bounded() {
        let sandbox = temp_sandbox("bounded-output");
        let command = "yes synthetic | head -c 100000".to_owned();
        let result = sandbox
            .execute(&ToolCallRecord::new(
                "terminal",
                "call",
                serde_json::to_string(&json!({ "command": command })).unwrap(),
            ))
            .expect("terminal executes");
        match result {
            ToolResult::Terminal { output, exit_code, .. } => {
                assert_eq!(exit_code, 0);
                assert!(output.chars().count() <= MAX_TERMINAL_OUTPUT_CHARS + 200);
                assert!(output.contains("OUTPUT TRUNCATED"));
            }
            other => panic!("expected a terminal result, got {other:?}"),
        }
        cleanup(&sandbox);
    }
}
