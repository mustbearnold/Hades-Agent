//! `hades-dev control-plane` — Rust port of
//! `scripts/agent/control_plane.py` (HAD-125).
//!
//! Validates and mutates the small, checked-in Hades development control
//! plane (`.hades/tasks.json`). Commands, JSON output shapes, validation
//! errors, and flock-based locking are equivalent to the Python control
//! plane so the gate and the `just agent` workflow can swap implementations
//! without changing behavior.

use std::collections::{HashMap, HashSet};
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::os::fd::AsFd;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{SystemTime, UNIX_EPOCH};

use rustix::fs::{FlockOperation, flock};
use serde_json::{Value, json};

const STATUSES: [&str; 6] = ["queued", "ready", "in_progress", "blocked", "complete", "cancelled"];
const RISKS: [&str; 3] = ["low", "medium", "high"];
const REQUIRED_FILES: [&str; 11] = [
    "AGENTS.md",
    "README.md",
    "SECURITY.md",
    "Cargo.toml",
    "rust-toolchain.toml",
    "specs/constitution.md",
    "specs/conventions.md",
    "specs/001-parity-contract/spec.md",
    "specs/001-parity-contract/matrix.md",
    "docs/runbooks/agent-contracts.md",
    ".hades/protocol/task.schema.json",
];

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .canonicalize()
        .expect("repository root")
}

fn tasks_path() -> PathBuf {
    root().join(".hades").join("tasks.json")
}

fn config_path() -> PathBuf {
    root().join(".hades").join("config.toml")
}

fn lock_path() -> PathBuf {
    root().join(".hades").join("locks").join("tasks.lock")
}

fn now() -> String {
    let seconds = SystemTime::now().duration_since(UNIX_EPOCH).expect("clock").as_secs();
    // Python: datetime.now(timezone.utc).replace(microsecond=0)
    // .isoformat().replace("+00:00", "Z")
    let days = seconds / 86400;
    let (year, month, day) = civil_from_days(days as i64);
    let (hour, minute, second) = {
        let tod = seconds % 86400;
        (tod / 3600, (tod % 3600) / 60, tod % 60)
    };
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
}

/// Convert days since 1970-01-01 to a civil (year, month, day).
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let year = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let month = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if month <= 2 { year + 1 } else { year }, month, day)
}

fn load_json(path: &Path) -> Result<Value, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|error| format!("missing control-plane file: {} ({error})", path.display()))?;
    let value: Value = serde_json::from_str(&text)
        .map_err(|error| format!("invalid JSON in {}: {error}", path.display()))?;
    if !value.is_object() {
        return Err(format!("expected an object in {}", path.display()));
    }
    Ok(value)
}

fn task_map(data: &Value) -> HashMap<String, Value> {
    data["tasks"]
        .as_array()
        .map(|tasks| {
            tasks
                .iter()
                .filter_map(|task| {
                    task.get("id").and_then(Value::as_str).map(|id| (id.to_owned(), task.clone()))
                })
                .collect()
        })
        .unwrap_or_default()
}

fn validate_evidence_path(task_id: &str, value: &str) -> Vec<String> {
    let path = Path::new(value);
    if path.is_absolute() || path.components().any(|c| c.as_os_str() == "..") {
        return vec![format!(
            "{task_id} evidence path must stay relative to the repository: {value}"
        )];
    }
    if !root().join(path).exists() {
        return vec![format!("{task_id} evidence path does not exist: {value}")];
    }
    Vec::new()
}

fn validate(data: &Value) -> Vec<String> {
    let mut errors: Vec<String> = Vec::new();
    if data.get("schema_version") != Some(&json!(1)) {
        errors.push(".hades/tasks.json must use schema_version 1".to_owned());
    }
    let Some(tasks) = data.get("tasks").and_then(Value::as_array) else {
        errors.push(".hades/tasks.json must contain a non-empty tasks array".to_owned());
        return errors;
    };
    if tasks.is_empty() {
        errors.push(".hades/tasks.json must contain a non-empty tasks array".to_owned());
        return errors;
    }

    let mut by_id: HashMap<String, Value> = HashMap::new();
    for (index, task) in tasks.iter().enumerate() {
        let prefix = format!("task[{index}]");
        if !task.is_object() {
            errors.push(format!("{prefix} must be an object"));
            continue;
        }
        let task_id = task.get("id").and_then(Value::as_str).unwrap_or_default();
        if !task_id.starts_with("HAD-") {
            errors.push(format!("{prefix} has an invalid id"));
        } else if by_id.contains_key(task_id) {
            errors.push(format!("duplicate task id: {task_id}"));
        } else {
            by_id.insert(task_id.to_owned(), task.clone());
        }

        let title = task.get("title").and_then(Value::as_str).unwrap_or_default();
        if title.trim().is_empty() {
            errors.push(format!("{prefix} needs a non-empty title"));
        }
        let priority = task.get("priority").and_then(Value::as_i64).unwrap_or(-1);
        if priority < 0 {
            errors.push(format!("{prefix} needs a non-negative integer priority"));
        }
        let status = task.get("status").and_then(Value::as_str).unwrap_or_default();
        if !STATUSES.contains(&status) {
            errors.push(format!("{prefix} has an invalid status"));
        }
        let risk = task.get("risk").and_then(Value::as_str).unwrap_or_default();
        if !RISKS.contains(&risk) {
            errors.push(format!("{prefix} has an invalid risk"));
        }
        for field in ["depends_on", "oracle", "acceptance", "evidence"] {
            let value = task.get(field).cloned().unwrap_or(Value::Null);
            let Some(items) = value.as_array() else {
                errors.push(format!("{prefix}.{field} must be an array"));
                continue;
            };
            if matches!(field, "oracle" | "acceptance") && items.is_empty() {
                errors.push(format!("{prefix}.{field} must not be empty"));
            }
            if !items.iter().all(|item| item.as_str().is_some_and(|text| !text.trim().is_empty())) {
                errors.push(format!("{prefix}.{field} must contain non-empty strings"));
            }
        }

        if status == "in_progress" {
            let claimed_by = task.get("claimed_by").and_then(Value::as_str).unwrap_or_default();
            if claimed_by.trim().is_empty() {
                errors.push(format!("{task_id} in_progress task needs claimed_by"));
            }
            let claimed_at = task.get("claimed_at").and_then(Value::as_str).unwrap_or_default();
            if claimed_at.trim().is_empty() {
                errors.push(format!("{task_id} in_progress task needs claimed_at"));
            }
        }

        if status == "complete" {
            let evidence =
                task.get("evidence").and_then(Value::as_array).cloned().unwrap_or_default();
            if evidence.is_empty() {
                errors.push(format!("{task_id} complete task needs evidence"));
            }
            for evidence_path in &evidence {
                if let Some(path) = evidence_path.as_str() {
                    errors.extend(validate_evidence_path(task_id, path));
                }
            }
            let result = task.get("result");
            let summary_ok = result
                .and_then(|r| r.get("summary"))
                .and_then(Value::as_str)
                .is_some_and(|s| !s.trim().is_empty());
            if !summary_ok {
                errors.push(format!("{task_id} complete task needs a result summary"));
            }
            let result_evidence = result
                .and_then(|r| r.get("evidence"))
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            if result_evidence != evidence {
                errors.push(format!("{task_id} result evidence must match task evidence"));
            }
        }
    }

    for (task_id, task) in &by_id {
        let Some(dependencies) = task.get("depends_on").and_then(Value::as_array) else {
            continue;
        };
        for dependency in dependencies {
            let Some(dependency) = dependency.as_str() else {
                continue;
            };
            if dependency == task_id {
                errors.push(format!("{task_id} cannot depend on itself"));
            } else if !by_id.contains_key(dependency) {
                errors.push(format!("{task_id} depends on unknown task {dependency}"));
            }
        }
    }

    // Cycle detection (DFS with visiting/visited sets, like the Python).
    let mut visiting: HashSet<String> = HashSet::new();
    let mut visited: HashSet<String> = HashSet::new();
    fn visit(
        task_id: &str,
        by_id: &HashMap<String, Value>,
        visiting: &mut HashSet<String>,
        visited: &mut HashSet<String>,
        errors: &mut Vec<String>,
    ) {
        if visiting.contains(task_id) {
            errors.push(format!("task dependency cycle includes {task_id}"));
            return;
        }
        if visited.contains(task_id) {
            return;
        }
        visiting.insert(task_id.to_owned());
        if let Some(task) = by_id.get(task_id)
            && let Some(dependencies) = task.get("depends_on").and_then(Value::as_array)
        {
            for dependency in dependencies {
                if let Some(dependency) = dependency.as_str()
                    && by_id.contains_key(dependency)
                {
                    visit(dependency, by_id, visiting, visited, errors);
                }
            }
        }
        visiting.remove(task_id);
        visited.insert(task_id.to_owned());
    }
    for task_id in by_id.keys() {
        visit(task_id, &by_id, &mut visiting, &mut visited, &mut errors);
    }

    for required_file in REQUIRED_FILES {
        let path = root().join(required_file);
        let is_empty = std::fs::metadata(&path).map(|metadata| metadata.len() == 0).unwrap_or(true);
        if !path.is_file() || is_empty {
            errors.push(format!("missing or empty required file: {required_file}"));
        }
    }

    let config_text = std::fs::read_to_string(config_path());
    match config_text {
        Ok(text) => match text.parse::<toml::Table>() {
            Ok(config) => {
                if config.get("schema_version").and_then(toml::Value::as_integer) != Some(1) {
                    errors.push(".hades/config.toml must use schema_version 1".to_owned());
                }
                if !config.get("required_gates").is_some() {
                    errors.push(".hades/config.toml must declare required_gates".to_owned());
                }
            }
            Err(error) => errors.push(format!("invalid .hades/config.toml: {error}")),
        },
        Err(error) => errors.push(format!("invalid .hades/config.toml: {error}")),
    }

    errors
}

fn read_validated() -> Result<Value, String> {
    let data = load_json(&tasks_path())?;
    let errors = validate(&data);
    if !errors.is_empty() {
        return Err(errors.join("\n"));
    }
    Ok(data)
}

/// Apply `mutator` under an exclusive flock, validate, promote unblocked
/// tasks, bump `updated_at`, and atomically replace the ledger.
fn write_locked(
    mutator: impl FnOnce(&mut Value) -> Result<Value, String>,
) -> Result<Value, String> {
    let lock_path = lock_path();
    let lock_dir = lock_path.parent().expect("lock parent").to_owned();
    std::fs::create_dir_all(&lock_dir)
        .map_err(|error| format!("could not create lock dir: {error}"))?;
    let lock_file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(&lock_path)
        .map_err(|error| format!("could not open lock: {error}"))?;
    flock(lock_file.as_fd(), FlockOperation::LockExclusive)
        .map_err(|error| format!("could not lock control plane: {error}"))?;

    let mut data = read_validated()?;
    let result = mutator(&mut data)?;
    promote_unblocked(&mut data);
    data["updated_at"] = json!(now());

    let temporary = tasks_path().with_file_name(format!(".tasks.json.{}.tmp", std::process::id()));
    let mut handle =
        File::create(&temporary).map_err(|error| format!("could not write ledger: {error}"))?;
    let serialized = serde_json::to_string_pretty(&data)
        .map_err(|error| format!("could not serialize ledger: {error}"))?;
    handle
        .write_all(serialized.as_bytes())
        .and_then(|_| handle.write_all(b"\n"))
        .and_then(|_| handle.sync_all())
        .map_err(|error| format!("could not write ledger: {error}"))?;
    std::fs::rename(&temporary, tasks_path())
        .map_err(|error| format!("could not replace ledger: {error}"))?;
    Ok(result)
}

fn promote_unblocked(data: &mut Value) {
    let by_id = task_map(data);
    if let Some(tasks) = data.get_mut("tasks").and_then(Value::as_array_mut) {
        for task in tasks.iter_mut() {
            if task.get("status").and_then(Value::as_str) == Some("queued") {
                let dependencies = task.get("depends_on").and_then(Value::as_array).cloned();
                let all_complete = dependencies.is_none_or(|dependencies| {
                    dependencies.iter().all(|dependency| {
                        dependency
                            .as_str()
                            .and_then(|id| by_id.get(id))
                            .and_then(|task| task.get("status"))
                            .and_then(Value::as_str)
                            == Some("complete")
                    })
                });
                if all_complete {
                    task["status"] = json!("ready");
                    task["ready_at"] = json!(now());
                }
            }
        }
    }
}

fn eligible_tasks(data: &Value) -> Vec<Value> {
    let by_id = task_map(data);
    let mut eligible: Vec<Value> = data["tasks"]
        .as_array()
        .map(|tasks| {
            tasks
                .iter()
                .filter(|task| {
                    task.get("status").and_then(Value::as_str) == Some("ready")
                        && task
                            .get("depends_on")
                            .and_then(Value::as_array)
                            .map(|dependencies| {
                                dependencies.iter().all(|dependency| {
                                    dependency
                                        .as_str()
                                        .and_then(|id| by_id.get(id))
                                        .and_then(|task| task.get("status"))
                                        .and_then(Value::as_str)
                                        == Some("complete")
                                })
                            })
                            .unwrap_or(true)
                })
                .cloned()
                .collect()
        })
        .unwrap_or_default();
    eligible.sort_by(|a, b| {
        let priority_a = a.get("priority").and_then(Value::as_i64).unwrap_or(0);
        let priority_b = b.get("priority").and_then(Value::as_i64).unwrap_or(0);
        priority_b.cmp(&priority_a).then_with(|| {
            a.get("id").and_then(Value::as_str).cmp(&b.get("id").and_then(Value::as_str))
        })
    });
    eligible
}

fn find_task<'a>(data: &'a Value, task_id: &str) -> Result<&'a Value, String> {
    data["tasks"]
        .as_array()
        .and_then(|tasks| {
            tasks.iter().find(|task| task.get("id").and_then(Value::as_str) == Some(task_id))
        })
        .ok_or_else(|| format!("unknown task: {task_id}"))
}

fn command_validate() -> Result<Value, String> {
    let data = load_json(&tasks_path())?;
    let errors = validate(&data);
    if !errors.is_empty() {
        return Err(errors.join("\n"));
    }
    Ok(json!({
        "valid": true,
        "task_count": data["tasks"].as_array().map_or(0, Vec::len),
    }))
}

fn command_next() -> Result<Value, String> {
    let data = read_validated()?;
    let eligible = eligible_tasks(&data);
    if eligible.is_empty() {
        Ok(json!({"task": null, "reason": "no unblocked ready task"}))
    } else {
        Ok(json!({"task": eligible[0]}))
    }
}

fn command_show(task_id: &str) -> Result<Value, String> {
    let data = read_validated()?;
    Ok(find_task(&data, task_id)?.clone())
}

fn command_claim(task_id: &str, agent: &str) -> Result<Value, String> {
    let task_id = task_id.to_owned();
    let agent = agent.to_owned();
    write_locked(|data| {
        let by_id = task_map(data);
        let task = find_task(data, &task_id)?.clone();
        let status = task.get("status").and_then(Value::as_str).unwrap_or_default();
        if status != "ready" {
            return Err(format!("{task_id} is {status}, not ready"));
        }
        let blocked_by: Vec<String> = task
            .get("depends_on")
            .and_then(Value::as_array)
            .map(|dependencies| {
                dependencies
                    .iter()
                    .filter_map(|dependency| {
                        let id = dependency.as_str()?;
                        let status = by_id
                            .get(id)
                            .and_then(|task| task.get("status"))
                            .and_then(Value::as_str)?;
                        (status != "complete").then(|| id.to_owned())
                    })
                    .collect()
            })
            .unwrap_or_default();
        if !blocked_by.is_empty() {
            return Err(format!("{task_id} is blocked by: {}", blocked_by.join(", ")));
        }
        let task = data["tasks"]
            .as_array_mut()
            .and_then(|tasks| {
                tasks
                    .iter_mut()
                    .find(|task| task.get("id").and_then(Value::as_str) == Some(task_id.as_str()))
            })
            .ok_or_else(|| format!("unknown task: {task_id}"))?;
        task["status"] = json!("in_progress");
        task["claimed_by"] = json!(agent);
        task["claimed_at"] = json!(now());
        let attempts = task.get("attempts").and_then(Value::as_i64).unwrap_or(0);
        task["attempts"] = json!(attempts + 1);
        Ok(json!({"claimed": task.clone()}))
    })
}

fn command_complete(task_id: &str, summary: &str, evidence: &[String]) -> Result<Value, String> {
    let evidence: Vec<String> = {
        let mut seen = HashSet::new();
        evidence.iter().filter(|path| seen.insert((*path).clone())).cloned().collect()
    };
    let path_errors: Vec<String> =
        evidence.iter().flat_map(|path| validate_evidence_path(task_id, path)).collect();
    if !path_errors.is_empty() {
        return Err(path_errors.join("\n"));
    }

    let task_id = task_id.to_owned();
    let summary = summary.to_owned();
    let evidence_clone = evidence.clone();
    write_locked(move |data| {
        let task = find_task(data, &task_id)?.clone();
        let status = task.get("status").and_then(Value::as_str).unwrap_or_default();
        if status != "in_progress" {
            return Err(format!("{task_id} is {status}; claim it before completing"));
        }
        let task = data["tasks"]
            .as_array_mut()
            .and_then(|tasks| {
                tasks
                    .iter_mut()
                    .find(|task| task.get("id").and_then(Value::as_str) == Some(task_id.as_str()))
            })
            .ok_or_else(|| format!("unknown task: {task_id}"))?;
        let evidence_value: Vec<Value> = evidence_clone.iter().map(|path| json!(path)).collect();
        task["status"] = json!("complete");
        task["evidence"] = Value::Array(evidence_value.clone());
        task["result"] = json!({
            "summary": summary,
            "completed_at": now(),
            "evidence": evidence_value,
        });
        Ok(json!({"completed": task.clone()}))
    })
}

fn command_block(task_id: &str, reason: &str, next_action: Option<&str>) -> Result<Value, String> {
    let task_id = task_id.to_owned();
    let reason = reason.to_owned();
    let next_action = next_action.map(str::to_owned);
    write_locked(move |data| {
        let task = find_task(data, &task_id)?.clone();
        let status = task.get("status").and_then(Value::as_str).unwrap_or_default();
        if !matches!(status, "in_progress" | "ready") {
            return Err(format!("{task_id} is {status}; only active work can be blocked"));
        }
        let task = data["tasks"]
            .as_array_mut()
            .and_then(|tasks| {
                tasks
                    .iter_mut()
                    .find(|task| task.get("id").and_then(Value::as_str) == Some(task_id.as_str()))
            })
            .ok_or_else(|| format!("unknown task: {task_id}"))?;
        let mut result = serde_json::Map::new();
        result.insert("reason".to_owned(), json!(reason));
        result.insert("blocked_at".to_owned(), json!(now()));
        if let Some(next_action) = next_action {
            result.insert("next_action".to_owned(), json!(next_action));
        }
        task["status"] = json!("blocked");
        task["result"] = Value::Object(result);
        Ok(json!({"blocked": task.clone()}))
    })
}

fn command_cancel(task_id: &str, reason: &str) -> Result<Value, String> {
    let task_id = task_id.to_owned();
    let reason = reason.to_owned();
    write_locked(move |data| {
        let task = find_task(data, &task_id)?.clone();
        let status = task.get("status").and_then(Value::as_str).unwrap_or_default();
        if !matches!(status, "in_progress" | "ready" | "queued") {
            return Err(format!("{task_id} is {status}; only unfinished work can be cancelled"));
        }
        let task = data["tasks"]
            .as_array_mut()
            .and_then(|tasks| {
                tasks
                    .iter_mut()
                    .find(|task| task.get("id").and_then(Value::as_str) == Some(task_id.as_str()))
            })
            .ok_or_else(|| format!("unknown task: {task_id}"))?;
        task["status"] = json!("cancelled");
        task["result"] = json!({"reason": reason, "cancelled_at": now()});
        Ok(json!({"cancelled": task.clone()}))
    })
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let result = match args.first().map(String::as_str) {
        Some("validate") if args.len() == 1 => command_validate(),
        Some("next") if args.len() == 1 => command_next(),
        Some("show") if args.len() == 2 => command_show(&args[1]),
        Some("claim") if args.len() == 3 => command_claim(&args[1], &args[2]),
        Some("complete") => {
            let task_id = args.get(1).cloned().unwrap_or_default();
            let mut summary = None;
            let mut evidence = Vec::new();
            let mut index = 2;
            while index < args.len() {
                match args[index].as_str() {
                    "--summary" if index + 1 < args.len() => {
                        summary = Some(args[index + 1].clone());
                        index += 2;
                    }
                    "--evidence" if index + 1 < args.len() => {
                        evidence.push(args[index + 1].clone());
                        index += 2;
                    }
                    _ => {
                        return error_exit(format!(
                            "unexpected argument: {}",
                            args[index]
                        ));
                    }
                }
            }
            match (summary, task_id.as_str()) {
                (Some(summary), id) if !id.is_empty() && !evidence.is_empty() => {
                    command_complete(id, &summary, &evidence)
                }
                _ => return error_exit("complete requires task_id, --summary, and --evidence".to_owned()),
            }
        }
        Some("block") => {
            let task_id = args.get(1).cloned().unwrap_or_default();
            let mut reason = None;
            let mut next_action = None;
            let mut index = 2;
            while index < args.len() {
                match args[index].as_str() {
                    "--reason" if index + 1 < args.len() => {
                        reason = Some(args[index + 1].clone());
                        index += 2;
                    }
                    "--next-action" if index + 1 < args.len() => {
                        next_action = Some(args[index + 1].clone());
                        index += 2;
                    }
                    _ => return error_exit(format!("unexpected argument: {}", args[index])),
                }
            }
            match (reason, task_id.as_str()) {
                (Some(reason), id) if !id.is_empty() => {
                    command_block(id, &reason, next_action.as_deref())
                }
                _ => return error_exit("block requires task_id and --reason".to_owned()),
            }
        }
        Some("cancel") => {
            let task_id = args.get(1).cloned().unwrap_or_default();
            let mut reason = None;
            let mut index = 2;
            while index < args.len() {
                match args[index].as_str() {
                    "--reason" if index + 1 < args.len() => {
                        reason = Some(args[index + 1].clone());
                        index += 2;
                    }
                    _ => return error_exit(format!("unexpected argument: {}", args[index])),
                }
            }
            match (reason, task_id.as_str()) {
                (Some(reason), id) if !id.is_empty() => command_cancel(id, &reason),
                _ => return error_exit("cancel requires task_id and --reason".to_owned()),
            }
        }
        _ => return error_exit(
            "usage: control-plane validate|next|show <task_id>|claim <task_id> <agent>|complete <task_id> --summary S --evidence P [--evidence P ...]|block <task_id> --reason R [--next-action N]|cancel <task_id> --reason R".to_owned(),
        ),
    };

    match result {
        Ok(value) => {
            println!("{}", serde_json::to_string_pretty(&value).expect("serialize"));
            ExitCode::SUCCESS
        }
        Err(message) => error_exit(message),
    }
}

fn error_exit(message: String) -> ExitCode {
    eprintln!("ERROR: {message}");
    ExitCode::FAILURE
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_ledger() -> Value {
        json!({
            "schema_version": 1,
            "updated_at": "2026-08-04T00:00:00Z",
            "tasks": [
                {
                    "id": "HAD-001",
                    "title": "foundation",
                    "priority": 10,
                    "status": "complete",
                    "risk": "low",
                    "depends_on": [],
                    "oracle": ["unit_tests"],
                    "acceptance": ["works"],
                    "evidence": ["README.md"],
                    "result": {
                        "summary": "done",
                        "completed_at": "2026-08-01T00:00:00Z",
                        "evidence": ["README.md"],
                    },
                },
                {
                    "id": "HAD-002",
                    "title": "next",
                    "priority": 9,
                    "status": "queued",
                    "risk": "medium",
                    "depends_on": ["HAD-001"],
                    "oracle": ["unit_tests"],
                    "acceptance": ["works"],
                    "evidence": [],
                },
            ],
        })
    }

    #[test]
    fn validates_a_clean_ledger() {
        let errors = validate(&sample_ledger());
        assert!(errors.is_empty(), "{errors:?}");
    }

    #[test]
    fn promotes_queued_tasks_when_dependencies_complete() {
        let mut data = sample_ledger();
        promote_unblocked(&mut data);
        let task = &data["tasks"][1];
        assert_eq!(task["status"], "ready");
        assert!(task["ready_at"].as_str().is_some());
    }

    #[test]
    fn detects_unknown_dependency() {
        let mut data = sample_ledger();
        data["tasks"][1]["depends_on"] = json!(["HAD-999"]);
        let errors = validate(&data);
        assert!(
            errors.iter().any(|error| error.contains("depends on unknown task HAD-999")),
            "{errors:?}"
        );
    }

    #[test]
    fn detects_dependency_cycle() {
        let mut data = sample_ledger();
        data["tasks"][0]["depends_on"] = json!(["HAD-002"]);
        let errors = validate(&data);
        assert!(errors.iter().any(|error| error.contains("cycle")), "{errors:?}");
    }

    #[test]
    fn detects_duplicate_ids() {
        let mut data = sample_ledger();
        data["tasks"][1]["id"] = json!("HAD-001");
        let errors = validate(&data);
        assert!(errors.iter().any(|error| error.contains("duplicate task id")), "{errors:?}");
    }

    #[test]
    fn complete_task_requires_matching_evidence() {
        let mut data = sample_ledger();
        data["tasks"][0]["evidence"] = json!(["README.md", "specs/001-parity-contract/spec.md"]);
        let errors = validate(&data);
        assert!(
            errors.iter().any(|error| error.contains("result evidence must match")),
            "{errors:?}"
        );
    }

    #[test]
    fn eligible_tasks_sorts_by_priority_descending() {
        let mut data = sample_ledger();
        data["tasks"][0]["status"] = json!("ready");
        data["tasks"][1]["status"] = json!("ready");
        data["tasks"][1]["depends_on"] = json!([]);
        let eligible = eligible_tasks(&data);
        assert_eq!(eligible.len(), 2);
        assert_eq!(eligible[0]["id"], "HAD-001"); // priority 10 first
    }

    #[test]
    fn timestamp_is_utc_iso8601() {
        let stamp = now();
        assert!(stamp.ends_with('Z'), "{stamp}");
        assert_eq!(stamp.len(), 20, "{stamp}");
        let (year, month, day) = civil_from_days(0);
        assert_eq!((year, month, day), (1970, 1, 1));
        let (year, month, day) = civil_from_days(20_000);
        assert_eq!((year, month, day), (2024, 10, 4));
    }
}
