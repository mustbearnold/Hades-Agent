//! `hades-dev validate-fixture` — Rust port of
//! `scripts/validate_reference_fixture.py` (HAD-124).
//!
//! Validates a sanitized, provenance-bearing Hermes reference fixture and
//! prints the same JSON summary with the same exit codes: 0 valid, 1 invalid
//! (message on stderr). The contract is byte-for-byte equivalent to the
//! Python validator so the gate can swap implementations without changing
//! what it enforces.

use std::path::{Path, PathBuf};
use std::process::ExitCode;

use serde_json::Value;

const DEFAULT_FIXTURE: &str = "tests/fixtures/parity/OBS-0010-input-editing-keymap.json";
const FORBIDDEN_MARKERS: [&str; 4] = ["local-test-key", "authorization:", "bearer ", "sk-"];

fn fail<T>(message: &str) -> Result<T, String> {
    Err(message.to_owned())
}

fn require_string(value: &Value, path: &str) -> Result<(), String> {
    match value {
        Value::String(text) if !text.trim().is_empty() => Ok(()),
        _ => fail(&format!("{path} must be a non-empty string")),
    }
}

fn require_string_list(value: &Value, path: &str, non_empty: bool) -> Result<(), String> {
    let Value::Array(items) = value else {
        return fail(&format!("{path} must be a non-empty string array"));
    };
    if non_empty && items.is_empty() {
        return fail(&format!("{path} must be a non-empty string array"));
    }
    for item in items {
        match item {
            Value::String(text) if !text.trim().is_empty() => {}
            _ => return fail(&format!("{path} must contain only non-empty strings")),
        }
    }
    Ok(())
}

fn validate_input_event(event: &Value, path: &str) -> Result<(), String> {
    let Value::Object(map) = event else {
        return fail(&format!("{path} must be an object"));
    };
    require_string(&map.get("kind").cloned().unwrap_or(Value::Null), &format!("{path}.kind"))?;
    require_string(&map.get("value").cloned().unwrap_or(Value::Null), &format!("{path}.value"))?;
    if map.get("kind").and_then(Value::as_str) == Some("wait") {
        return Ok(());
    }
    let raw_hex = map.get("bytes_hex").cloned().unwrap_or(Value::Null);
    let Value::String(raw_hex) = raw_hex else {
        return fail(&format!("{path}.bytes_hex is required for non-wait input"));
    };
    if raw_hex.trim().is_empty() {
        return fail(&format!("{path}.bytes_hex is required for non-wait input"));
    }
    let compact: String = raw_hex.split_whitespace().collect();
    if !compact.len().is_multiple_of(2) || !compact.chars().all(|c| c.is_ascii_hexdigit()) {
        return fail(&format!(
            "{path}.bytes_hex must contain an even number of hexadecimal digits"
        ));
    }
    Ok(())
}

/// Validate a fixture file, returning the parsed data on success.
pub fn validate_fixture(path: &Path) -> Result<Value, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|error| format!("could not read {}: {error}", path.display()))?;
    let data: Value = serde_json::from_str(&text)
        .map_err(|error| format!("could not read {}: {error}", path.display()))?;
    let Value::Object(map) = &data else {
        return fail("fixture must contain a JSON object");
    };

    let schema = map.get("schema_version").cloned().unwrap_or(Value::Null);
    if schema != Value::Number(serde_json::Number::from(1)) {
        return fail("schema_version must be 1");
    }
    require_string(&map.get("observation_id").cloned().unwrap_or(Value::Null), "observation_id")?;

    let reference = map.get("reference").cloned().unwrap_or(Value::Null);
    let Value::Object(reference) = &reference else {
        return fail("reference must be an object");
    };
    require_string(&reference.get("product").cloned().unwrap_or(Value::Null), "reference.product")?;
    require_string(&reference.get("version").cloned().unwrap_or(Value::Null), "reference.version")?;
    let source_commit = reference.get("source_commit").and_then(Value::as_str).unwrap_or("");
    if !(source_commit.len() == 40 && source_commit.chars().all(|c| c.is_ascii_hexdigit())) {
        return fail("reference.source_commit must be a 40-character lowercase commit");
    }
    let terminal = reference.get("terminal").cloned().unwrap_or(Value::Null);
    let Value::Object(terminal) = &terminal else {
        return fail("reference.terminal must contain positive integer columns and rows");
    };
    for key in ["columns", "rows"] {
        let value = terminal.get(key).and_then(Value::as_i64).unwrap_or(0);
        if value <= 0 {
            return fail("reference.terminal must contain positive integer columns and rows");
        }
    }
    require_string(&reference.get("capture").cloned().unwrap_or(Value::Null), "reference.capture")?;
    require_string_list(
        &map.get("normalization").cloned().unwrap_or(Value::Null),
        "normalization",
        true,
    )?;
    require_string_list(&map.get("unknowns").cloned().unwrap_or(Value::Null), "unknowns", true)?;

    let steps = map.get("steps").cloned().unwrap_or(Value::Null);
    let Value::Array(steps) = &steps else {
        return fail("steps must be a non-empty array");
    };
    if steps.is_empty() {
        return fail("steps must be a non-empty array");
    }
    let mut step_ids = std::collections::HashSet::new();
    for (index, step) in steps.iter().enumerate() {
        let path_prefix = format!("steps[{index}]");
        let Value::Object(step_map) = step else {
            return fail(&format!("{path_prefix} must be an object"));
        };
        let step_id = step_map.get("id").and_then(Value::as_str).unwrap_or("");
        if !step_ids.insert(step_id.to_owned()) {
            return fail(&format!("duplicate step id: {step_id}"));
        }
        let inputs = step_map.get("input_sequence").cloned().unwrap_or(Value::Null);
        let Value::Array(inputs) = &inputs else {
            return fail(&format!("{path_prefix}.input_sequence must be a non-empty array"));
        };
        if inputs.is_empty() {
            return fail(&format!("{path_prefix}.input_sequence must be a non-empty array"));
        }
        for (event_index, event) in inputs.iter().enumerate() {
            validate_input_event(event, &format!("{path_prefix}.input_sequence[{event_index}]"))?;
        }
        if !step_map.get("output").is_some_and(|output| output.is_object()) {
            return fail(&format!("{path_prefix}.output must be an object"));
        }
    }

    // Credential scan over the lowercase serialized fixture. `sk-` keys
    // appear at a token boundary; hyphenated prose such as "task-specific"
    // embeds `sk-` between word characters and must not trip the scan.
    let serialized = serde_json::to_string(&data)
        .map_err(|error| format!("could not serialize fixture: {error}"))?
        .to_lowercase();
    for marker in FORBIDDEN_MARKERS {
        if marker == "sk-" {
            continue;
        }
        if serialized.contains(marker) {
            return fail(&format!("fixture contains a forbidden credential-like marker: {marker}"));
        }
    }
    let bytes = serialized.as_bytes();
    // Python: SK_TOKEN = re.compile(r"(^|[^a-z0-9_])sk-[a-z0-9]").
    let mut index = 0;
    while index + 3 <= bytes.len() {
        if &bytes[index..index + 3] == b"sk-" && index + 4 <= bytes.len() {
            let preceded_by_boundary =
                index == 0 || !bytes[index - 1].is_ascii_alphanumeric() && bytes[index - 1] != b'_';
            let followed_by_token = bytes[index + 3].is_ascii_alphanumeric();
            if preceded_by_boundary && followed_by_token {
                return fail("fixture contains a forbidden credential-like marker: sk-");
            }
        }
        index += 1;
    }

    Ok(data)
}

fn run() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    let fixture_arg = args.next().unwrap_or_else(|| DEFAULT_FIXTURE.to_owned());
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .canonicalize()
        .map_err(|error| format!("could not resolve repository root: {error}"))?;
    let path = PathBuf::from(&fixture_arg);
    let path = if path.is_absolute() { path } else { root.join(&path) };
    let path = path
        .canonicalize()
        .map_err(|error| format!("could not read {}: {error}", path.display()))?;
    let data = validate_fixture(&path)?;
    let observation_id = data.get("observation_id").and_then(Value::as_str).unwrap_or_default();
    let steps = data.get("steps").and_then(Value::as_array).map_or(0, Vec::len);
    let relative = path.strip_prefix(&root).unwrap_or(&path).to_string_lossy().to_string();
    let summary = serde_json::json!({
        "fixture": relative,
        "observation_id": observation_id,
        "steps": steps,
        "valid": true,
    });
    println!("{}", serde_json::to_string_pretty(&summary).map_err(|e| e.to_string())?);
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("reference fixture invalid: {message}");
            ExitCode::FAILURE
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn write_temp(contents: &str) -> PathBuf {
        let mut path = std::env::temp_dir();
        path.push(format!(
            "hades-fixture-test-{}-{:?}.json",
            std::process::id(),
            std::thread::current().id()
        ));
        let mut file = std::fs::File::create(&path).unwrap();
        file.write_all(contents.as_bytes()).unwrap();
        path
    }

    const VALID_FIXTURE: &str = r#"{
        "schema_version": 1,
        "observation_id": "OBS-TEST",
        "reference": {
            "product": "hermes",
            "version": "0.19.1",
            "source_commit": "e444d165807f489b5c1ab8e4a612c8d09c2e67a2",
            "terminal": {"columns": 120, "rows": 40},
            "capture": "direct pty"
        },
        "normalization": ["digest"],
        "unknowns": ["none"],
        "steps": [{
            "id": "startup",
            "input_sequence": [{"kind": "wait", "value": "ready"}],
            "output": {"status": "ready"}
        }]
    }"#;

    #[test]
    fn accepts_valid_fixture() {
        let path = write_temp(VALID_FIXTURE);
        let data = validate_fixture(&path).expect("valid fixture");
        assert_eq!(data["observation_id"], "OBS-TEST");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn rejects_bad_schema_version() {
        let path =
            write_temp(&VALID_FIXTURE.replace("\"schema_version\": 1", "\"schema_version\": 2"));
        let error = validate_fixture(&path).unwrap_err();
        assert!(error.contains("schema_version must be 1"), "{error}");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn rejects_short_source_commit() {
        let path =
            write_temp(&VALID_FIXTURE.replace("e444d165807f489b5c1ab8e4a612c8d09c2e67a2", "abc"));
        let error = validate_fixture(&path).unwrap_err();
        assert!(error.contains("source_commit"), "{error}");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn rejects_forbidden_credential_marker() {
        let path = write_temp(&VALID_FIXTURE.replace("OBS-TEST", "sk-abcdef123456"));
        let error = validate_fixture(&path).unwrap_err();
        assert!(error.contains("sk-"), "{error}");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn allows_hyphenated_prose_with_embedded_sk() {
        // "task-specific" embeds `sk-` between word characters and must not
        // trip the credential scan (same as the Python SK_TOKEN regex).
        let path = write_temp(&VALID_FIXTURE.replace("OBS-TEST", "task-specific"));
        validate_fixture(&path).expect("hyphenated prose must pass");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn rejects_duplicate_step_ids() {
        let duplicated = VALID_FIXTURE.replace(
            "\"output\": {\"status\": \"ready\"}\n        }]",
            "\"output\": {\"status\": \"ready\"}\n        }, {\n            \"id\": \"startup\",\n            \"input_sequence\": [{\"kind\": \"wait\", \"value\": \"ready\"}],\n            \"output\": {\"status\": \"ready\"}\n        }]",
        );
        let path = write_temp(&duplicated);
        let error = validate_fixture(&path).unwrap_err();
        assert!(error.contains("duplicate step id"), "{error}");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn rejects_non_wait_event_without_bytes_hex() {
        let missing = VALID_FIXTURE.replace(
            "{\"kind\": \"wait\", \"value\": \"ready\"}",
            "{\"kind\": \"key\", \"value\": \"a\"}",
        );
        let path = write_temp(&missing);
        let error = validate_fixture(&path).unwrap_err();
        assert!(error.contains("bytes_hex"), "{error}");
        let _ = std::fs::remove_file(&path);
    }
}
