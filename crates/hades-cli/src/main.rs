#![forbid(unsafe_code)]

mod clipboard;
mod osc52;

use std::{
    env,
    error::Error,
    fs::{self, OpenOptions},
    io::{self, Write},
    path::PathBuf,
    process::{self, Command},
    sync::mpsc::{self, Receiver, Sender, TryRecvError},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use crossterm::{
    event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers},
    execute,
    style::force_color_output,
    terminal::{
        EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode, size,
    },
};
use hades_app::{App, DispatchOutcome};
use hades_core::{
    InputEvent, Key, PRODUCT_NAME, ProviderEvent, Role, SETUP_STANDALONE_BANNER,
    SETUP_STANDALONE_NO_PLATFORMS, SETUP_STANDALONE_PROMPT,
    SETUP_STANDALONE_TOOL_CONFIGURATION_LINES, SETUP_STANDALONE_TOOL_CONFIGURATION_TITLE,
    SETUP_STANDALONE_TOOL_PROVIDER_CONTROLS, SETUP_STANDALONE_TOOL_PROVIDER_LINES,
    SETUP_STANDALONE_TOOL_PROVIDER_TITLE, SETUP_TERMINAL_BACKEND_ROWS, SETUP_WIZARD_CHOICES,
    StandaloneSetupAction, StandaloneSetupState, StartupState, TurnState,
};
use hades_provider::{
    CancellationToken, ChatMessage, ChatRequest, LocalOpenAiTransport, StreamEvent, TransportError,
};
use hades_tui::{draw, draw_standalone_setup, snapshot, standalone_tool_provider_action_status};
use ratatui::{Terminal, backend::CrosstermBackend};
use signal_hook::{consts::SIGINT, flag};

const DEFAULT_PROVIDER_MODEL: &str = "palette-model";
const PROVIDER_BASE_URL_ENV: &str = "HADES_PROVIDER_BASE_URL";
const PROVIDER_MODEL_ENV: &str = "HADES_MODEL";
const PROVIDER_API_KEY_ENV: &str = "HADES_PROVIDER_API_KEY";
const LOCAL_PROVIDER_CONFIG_FILE: &str = "hades-local-provider.conf";
const STANDALONE_SETUP_STATE_FILE: &str = "hades-setup-boundary.conf";
const STANDALONE_SETUP_STATE_CONTENT: &str = "# Hades Agent setup boundary (Hades-owned, non-secret)\n\
     schema=1\n\
     setup_mode=full\n\
     terminal_backend=local\n\
     platform_selection=none\n\
     provider=unconfigured\n";
const PROVIDER_SYSTEM_PROMPT: &str = "You are Hades Agent. Respond concisely to the user.";

#[derive(Debug, Eq, PartialEq)]
struct ProviderConfig {
    base_url: String,
    model: String,
    api_key: Option<String>,
}

struct ProviderRuntime {
    events: Receiver<ProviderEvent>,
    cancellation: CancellationToken,
}

fn main() -> Result<(), Box<dyn Error>> {
    let arguments = env::args().skip(1).collect::<Vec<_>>();
    match cli_command_from_args(&arguments) {
        Ok(CliCommand::Help) => {
            println!(
                "{PRODUCT_NAME}\n\nUsage: hades [tui|setup [--local <loopback-url> [model]]|--snapshot|--help|--version]"
            );
            Ok(())
        }
        Ok(CliCommand::Version) => {
            println!("{PRODUCT_NAME} 0.1.0");
            Ok(())
        }
        Ok(CliCommand::Snapshot) => {
            println!("{}", snapshot(&App::new(), 120, 40));
            Ok(())
        }
        Ok(CliCommand::Tui) => run_tui(),
        Ok(CliCommand::Setup) => match run_setup()? {
            SetupOutcome::Cancelled => process::exit(1),
            SetupOutcome::SignalInterrupt => process::exit(130),
        },
        Ok(CliCommand::SetupLocal { base_url, model }) => {
            let (config, path) = write_local_provider_config(&base_url, model.as_deref())?;
            println!(
                "Hades local setup complete\nProvider: loopback\nEndpoint: {}\nModel: {}\nSaved: {}",
                config.base_url,
                config.model,
                path.display()
            );
            Ok(())
        }
        Err(error) => Err(error.into()),
    }
}

#[derive(Debug, Eq, PartialEq)]
enum CliCommand {
    Tui,
    Setup,
    SetupLocal { base_url: String, model: Option<String> },
    Snapshot,
    Help,
    Version,
}

fn cli_command(argument: Option<&str>) -> Result<CliCommand, &str> {
    match argument {
        None | Some("tui") => Ok(CliCommand::Tui),
        Some("setup") => Ok(CliCommand::Setup),
        Some("--help") | Some("-h") => Ok(CliCommand::Help),
        Some("--version") | Some("-V") => Ok(CliCommand::Version),
        Some("--snapshot") => Ok(CliCommand::Snapshot),
        Some(argument) => Err(argument),
    }
}

fn cli_command_from_args(arguments: &[String]) -> Result<CliCommand, String> {
    match arguments {
        [] => Ok(CliCommand::Tui),
        [argument] => cli_command(Some(argument)).map_err(|argument| argument.to_owned()),
        [command, local, base_url] if command == "setup" && local == "--local" => {
            Ok(CliCommand::SetupLocal { base_url: base_url.clone(), model: None })
        }
        [command, local, base_url, model] if command == "setup" && local == "--local" => {
            Ok(CliCommand::SetupLocal { base_url: base_url.clone(), model: Some(model.clone()) })
        }
        [command, local, ..] if command == "setup" && local == "--local" => {
            Err("usage: hades setup --local <loopback-url> [model]".to_owned())
        }
        [argument, ..] => Err(format!("unknown argument: {argument}")),
    }
}

fn run_tui() -> Result<(), Box<dyn Error>> {
    // Hermes keeps its palette active even when the parent process exports NO_COLOR.
    force_color_output(true);
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;

    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;
    let result = event_loop(&mut terminal);
    let cleanup = restore_terminal(&mut terminal);

    result.and(cleanup)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum SetupOutcome {
    Cancelled,
    SignalInterrupt,
}

#[derive(Debug)]
enum SetupTransition {
    NumberedFallback(StandaloneSetupState),
    ToolConfiguration(StandaloneSetupState),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ToolConfigurationEntry {
    Checklist,
    SignalInterrupt,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ToolChecklistOutcome {
    ProviderBoundary,
    SignalInterrupt,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ToolProviderInventoryOutcome {
    SignalInterrupt,
    Completed,
}

fn run_setup() -> Result<SetupOutcome, Box<dyn Error>> {
    force_color_output(true);
    let mut stdout = io::stdout();
    for line in SETUP_STANDALONE_BANNER {
        writeln!(stdout, "{line}")?;
    }
    stdout.flush()?;

    let cancelled = Arc::new(AtomicBool::new(false));
    let _sigint = flag::register(SIGINT, Arc::clone(&cancelled))?;
    enable_raw_mode()?;
    execute!(stdout, EnterAlternateScreen)?;

    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;
    let transition = setup_choice_loop(&mut terminal);
    let cleanup = restore_terminal(&mut terminal);
    let transition = transition?;
    cleanup?;

    match transition {
        SetupTransition::NumberedFallback(wizard) => {
            print_setup_fallback(&wizard)?;
            wait_for_setup_signal(&cancelled);
            Ok(SetupOutcome::Cancelled)
        }
        SetupTransition::ToolConfiguration(mut wizard) => {
            print_tool_configuration()?;
            match wait_for_tool_configuration_entry(&mut wizard, &cancelled)? {
                ToolConfigurationEntry::SignalInterrupt => Ok(SetupOutcome::SignalInterrupt),
                ToolConfigurationEntry::Checklist => {
                    match run_tool_checklist(&mut wizard, &cancelled)? {
                        ToolChecklistOutcome::SignalInterrupt => Ok(SetupOutcome::SignalInterrupt),
                        ToolChecklistOutcome::ProviderBoundary => {
                            match run_tool_provider_inventory(&mut wizard, &cancelled)? {
                                ToolProviderInventoryOutcome::SignalInterrupt => {
                                    Ok(SetupOutcome::SignalInterrupt)
                                }
                                ToolProviderInventoryOutcome::Completed => {
                                    print_tool_provider_action(&wizard)?;
                                    wait_for_setup_signal(&cancelled);
                                    Ok(SetupOutcome::SignalInterrupt)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

fn wait_for_setup_signal(cancelled: &AtomicBool) {
    while !cancelled.load(Ordering::Relaxed) {
        thread::sleep(Duration::from_millis(25));
    }
}

fn setup_choice_loop(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
) -> Result<SetupTransition, Box<dyn Error>> {
    let mut wizard = StandaloneSetupState::default();
    loop {
        terminal.draw(|frame| draw_standalone_setup(frame, &wizard))?;
        if !event::poll(Duration::from_millis(250))? {
            continue;
        }
        let Event::Key(key) = event::read()? else {
            continue;
        };
        if key.kind != KeyEventKind::Press {
            continue;
        }
        let Some(mapped) = map_key(key) else {
            continue;
        };
        let action = wizard.handle_key(mapped);
        match action {
            StandaloneSetupAction::EnteredFullSetupContinuation => {
                create_standalone_setup_config()?;
            }
            StandaloneSetupAction::EnteredFallback => {
                return Ok(SetupTransition::NumberedFallback(wizard));
            }
            StandaloneSetupAction::EnteredToolConfiguration => {
                return Ok(SetupTransition::ToolConfiguration(wizard));
            }
            StandaloneSetupAction::EnteredPlatformPicker => {
                persist_standalone_setup_state()?;
            }
            StandaloneSetupAction::Continue
            | StandaloneSetupAction::Moved
            | StandaloneSetupAction::SkippedProvider
            | StandaloneSetupAction::ConfirmedEmptyPlatformSelection
            | StandaloneSetupAction::EnteredToolChecklist
            | StandaloneSetupAction::EnteredToolProviderBoundary
            | StandaloneSetupAction::SelectedLocalBrowser
            | StandaloneSetupAction::SkippedToolProvider
            | StandaloneSetupAction::CancelledToolProvider
            | StandaloneSetupAction::Quit => {}
        }
    }
}

fn wait_for_tool_configuration_entry(
    wizard: &mut StandaloneSetupState,
    cancelled: &AtomicBool,
) -> Result<ToolConfigurationEntry, Box<dyn Error>> {
    // Keep the plain handoff observable with canonical input and echo before
    // arming the next raw surface. Bytes typed during this short handoff are
    // retained by the terminal line discipline and become events once raw
    // mode is enabled.
    thread::sleep(Duration::from_millis(25));
    if cancelled.load(Ordering::Relaxed) {
        return Ok(ToolConfigurationEntry::SignalInterrupt);
    }
    enable_raw_mode()?;

    loop {
        if cancelled.load(Ordering::Relaxed) {
            disable_raw_mode()?;
            return Ok(ToolConfigurationEntry::SignalInterrupt);
        }
        if !event::poll(Duration::from_millis(250))? {
            continue;
        }
        let Event::Key(key) = event::read()? else {
            continue;
        };
        if key.kind != KeyEventKind::Press {
            continue;
        }
        let Some(mapped) = map_key(key) else {
            continue;
        };
        if mapped == Key::Ctrl('c') {
            disable_raw_mode()?;
            return Ok(ToolConfigurationEntry::SignalInterrupt);
        }
        match wizard.handle_key(mapped) {
            StandaloneSetupAction::EnteredToolChecklist => {
                return Ok(ToolConfigurationEntry::Checklist);
            }
            StandaloneSetupAction::Continue
            | StandaloneSetupAction::Moved
            | StandaloneSetupAction::EnteredFullSetupContinuation
            | StandaloneSetupAction::SkippedProvider
            | StandaloneSetupAction::EnteredPlatformPicker
            | StandaloneSetupAction::EnteredToolConfiguration
            | StandaloneSetupAction::EnteredToolProviderBoundary
            | StandaloneSetupAction::ConfirmedEmptyPlatformSelection
            | StandaloneSetupAction::SelectedLocalBrowser
            | StandaloneSetupAction::SkippedToolProvider
            | StandaloneSetupAction::CancelledToolProvider
            | StandaloneSetupAction::EnteredFallback
            | StandaloneSetupAction::Quit => {}
        }
    }
}

fn run_tool_checklist(
    wizard: &mut StandaloneSetupState,
    cancelled: &AtomicBool,
) -> Result<ToolChecklistOutcome, Box<dyn Error>> {
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;
    let result = tool_checklist_loop(&mut terminal, wizard, cancelled);
    let cleanup = restore_terminal(&mut terminal);
    cleanup?;
    result
}

fn tool_checklist_loop(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
    wizard: &mut StandaloneSetupState,
    cancelled: &AtomicBool,
) -> Result<ToolChecklistOutcome, Box<dyn Error>> {
    loop {
        terminal.draw(|frame| draw_standalone_setup(frame, wizard))?;
        if cancelled.load(Ordering::Relaxed) {
            return Ok(ToolChecklistOutcome::SignalInterrupt);
        }
        if !event::poll(Duration::from_millis(250))? {
            continue;
        }
        let Event::Key(key) = event::read()? else {
            continue;
        };
        if key.kind != KeyEventKind::Press {
            continue;
        }
        let Some(mapped) = map_key(key) else {
            continue;
        };
        match wizard.handle_key(mapped) {
            StandaloneSetupAction::EnteredToolProviderBoundary => {
                return Ok(ToolChecklistOutcome::ProviderBoundary);
            }
            StandaloneSetupAction::Continue
            | StandaloneSetupAction::Moved
            | StandaloneSetupAction::EnteredFullSetupContinuation
            | StandaloneSetupAction::SkippedProvider
            | StandaloneSetupAction::EnteredPlatformPicker
            | StandaloneSetupAction::EnteredToolConfiguration
            | StandaloneSetupAction::EnteredToolChecklist
            | StandaloneSetupAction::ConfirmedEmptyPlatformSelection
            | StandaloneSetupAction::EnteredFallback
            | StandaloneSetupAction::SelectedLocalBrowser
            | StandaloneSetupAction::SkippedToolProvider
            | StandaloneSetupAction::CancelledToolProvider
            | StandaloneSetupAction::Quit => {}
        }
    }
}

fn run_tool_provider_inventory(
    wizard: &mut StandaloneSetupState,
    cancelled: &AtomicBool,
) -> Result<ToolProviderInventoryOutcome, Box<dyn Error>> {
    print_tool_provider_boundary()?;
    thread::sleep(Duration::from_millis(25));
    enable_raw_mode()?;
    let stdout = io::stdout();
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;
    let result = tool_provider_inventory_loop(&mut terminal, wizard, cancelled);
    let cleanup = restore_raw_terminal(&mut terminal);
    cleanup?;
    result
}

fn print_tool_provider_boundary() -> io::Result<()> {
    let mut stdout = io::stdout();
    for line in SETUP_STANDALONE_TOOL_PROVIDER_LINES {
        writeln!(stdout, "{line}")?;
    }
    writeln!(stdout, "{SETUP_STANDALONE_TOOL_PROVIDER_TITLE}")?;
    writeln!(stdout, "{SETUP_STANDALONE_TOOL_PROVIDER_CONTROLS}")?;
    stdout.flush()
}

fn print_tool_provider_action(wizard: &StandaloneSetupState) -> io::Result<()> {
    let mut stdout = io::stdout();
    if let Some(action) = wizard.provider_action() {
        writeln!(stdout, "\n{}", standalone_tool_provider_action_status(action))?;
    }
    stdout.flush()
}

fn tool_provider_inventory_loop(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
    wizard: &mut StandaloneSetupState,
    cancelled: &AtomicBool,
) -> Result<ToolProviderInventoryOutcome, Box<dyn Error>> {
    loop {
        terminal.draw(|frame| draw_standalone_setup(frame, wizard))?;
        if cancelled.load(Ordering::Relaxed) {
            return Ok(ToolProviderInventoryOutcome::SignalInterrupt);
        }
        if !event::poll(Duration::from_millis(250))? {
            continue;
        }
        let Event::Key(key) = event::read()? else {
            continue;
        };
        if key.kind != KeyEventKind::Press {
            continue;
        }
        let Some(mapped) = map_key(key) else {
            continue;
        };
        if mapped == Key::Ctrl('c') {
            return Ok(ToolProviderInventoryOutcome::SignalInterrupt);
        }
        match wizard.handle_key(mapped) {
            StandaloneSetupAction::SelectedLocalBrowser
            | StandaloneSetupAction::SkippedToolProvider
            | StandaloneSetupAction::CancelledToolProvider => {
                return Ok(ToolProviderInventoryOutcome::Completed);
            }
            StandaloneSetupAction::Continue
            | StandaloneSetupAction::Moved
            | StandaloneSetupAction::EnteredFullSetupContinuation
            | StandaloneSetupAction::SkippedProvider
            | StandaloneSetupAction::EnteredPlatformPicker
            | StandaloneSetupAction::EnteredToolConfiguration
            | StandaloneSetupAction::EnteredToolChecklist
            | StandaloneSetupAction::EnteredToolProviderBoundary
            | StandaloneSetupAction::ConfirmedEmptyPlatformSelection
            | StandaloneSetupAction::EnteredFallback
            | StandaloneSetupAction::Quit => {}
        }
    }
}

fn print_setup_fallback(wizard: &StandaloneSetupState) -> io::Result<()> {
    let mut stdout = io::stdout();
    if wizard.terminal_backend_fallback() {
        writeln!(stdout, "Select terminal backend:")?;
        for (index, row) in SETUP_TERMINAL_BACKEND_ROWS.iter().enumerate() {
            let cursor = if index == wizard.terminal_backend_cursor() { "→" } else { " " };
            let selected = if index == wizard.terminal_backend_cursor() { "●" } else { "○" };
            writeln!(stdout, " {cursor} ({selected}) {row}")?;
        }
        writeln!(stdout, "    Enter for default (8)  Ctrl+C to exit")?;
        write!(stdout, "  Select [1-8] (8): ")?;
    } else {
        writeln!(stdout, "{SETUP_STANDALONE_PROMPT}")?;
        for (index, choice) in SETUP_WIZARD_CHOICES.iter().enumerate() {
            let cursor = if index == wizard.cursor() { "→" } else { " " };
            let selected = if index == wizard.selected() { "●" } else { "○" };
            writeln!(stdout, " {cursor} ({selected}) {choice}")?;
        }
        writeln!(stdout, "    Enter for default (1)  Ctrl+C to exit")?;
        write!(stdout, "  Select [1-3] (1): ")?;
    }
    stdout.flush()
}

fn print_tool_configuration() -> io::Result<()> {
    let mut stdout = io::stdout();
    writeln!(stdout, "{SETUP_STANDALONE_NO_PLATFORMS}")?;
    writeln!(stdout, "{SETUP_STANDALONE_TOOL_CONFIGURATION_TITLE}")?;
    for line in SETUP_STANDALONE_TOOL_CONFIGURATION_LINES {
        writeln!(stdout, "{line}")?;
    }
    stdout.flush()
}

fn create_standalone_setup_config() -> io::Result<()> {
    let Some(path) = standalone_setup_config_path_from(
        env::var_os("HERMES_HOME").map(PathBuf::from),
        env::var_os("HOME").map(PathBuf::from),
    ) else {
        return Ok(());
    };
    if path.exists() {
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(
        path,
        "# Hades Agent setup baseline\nsetup:\n  mode: full\n  provider: unconfigured\n",
    )
}

fn standalone_setup_config_path_from(
    hermes_home: Option<PathBuf>,
    home: Option<PathBuf>,
) -> Option<PathBuf> {
    hermes_home
        .or_else(|| home.map(|path| path.join(".hermes")))
        .map(|path| path.join("config.yaml"))
}

fn persist_standalone_setup_state() -> io::Result<()> {
    let Some(path) = standalone_setup_state_path_from(
        env::var_os("HERMES_HOME").map(PathBuf::from),
        env::var_os("HOME").map(PathBuf::from),
    ) else {
        return Ok(());
    };
    write_standalone_setup_state_at(&path)
}

fn standalone_setup_state_path_from(
    hermes_home: Option<PathBuf>,
    home: Option<PathBuf>,
) -> Option<PathBuf> {
    standalone_setup_config_path_from(hermes_home, home)
        .and_then(|path| path.parent().map(|parent| parent.join(STANDALONE_SETUP_STATE_FILE)))
}

fn write_standalone_setup_state_at(path: &std::path::Path) -> io::Result<()> {
    let Some(parent) = path.parent() else {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "standalone setup state path has no parent",
        ));
    };
    fs::create_dir_all(parent)?;
    let stamp = SystemTime::now().duration_since(UNIX_EPOCH).map_err(io::Error::other)?.as_nanos();
    let temporary =
        parent.join(format!(".{STANDALONE_SETUP_STATE_FILE}.{}.{stamp}.tmp", process::id()));
    let result = (|| -> io::Result<()> {
        let mut file = OpenOptions::new().create_new(true).write(true).open(&temporary)?;
        file.write_all(STANDALONE_SETUP_STATE_CONTENT.as_bytes())?;
        file.sync_all()?;
        fs::rename(&temporary, path)
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn local_provider_config_path() -> Option<PathBuf> {
    local_provider_config_path_from(
        env::var_os("HERMES_HOME").map(PathBuf::from),
        env::var_os("HOME").map(PathBuf::from),
    )
}

fn local_provider_config_path_from(
    hermes_home: Option<PathBuf>,
    home: Option<PathBuf>,
) -> Option<PathBuf> {
    standalone_setup_config_path_from(hermes_home, home)
        .and_then(|path| path.parent().map(|parent| parent.join(LOCAL_PROVIDER_CONFIG_FILE)))
}

fn write_local_provider_config(
    base_url: &str,
    model: Option<&str>,
) -> Result<(ProviderConfig, PathBuf), String> {
    let path = local_provider_config_path()
        .ok_or_else(|| "HOME or HERMES_HOME is required for local setup".to_owned())?;
    let config = local_provider_config_from_input(base_url, model)?;
    write_local_provider_config_at(&path, &config)?;
    Ok((config, path))
}

fn local_provider_config_from_input(
    base_url: &str,
    model: Option<&str>,
) -> Result<ProviderConfig, String> {
    let config = provider_config_from(Some(base_url), model, None)?
        .ok_or_else(|| "a loopback provider URL is required".to_owned())?;
    validate_local_config_value("endpoint", &config.base_url)?;
    validate_local_config_value("model", &config.model)?;
    LocalOpenAiTransport::new(&config.base_url, None)
        .map_err(|error| format!("local provider endpoint rejected: {error}"))?;
    Ok(config)
}

fn validate_local_config_value(name: &str, value: &str) -> Result<(), String> {
    if value.trim().is_empty() {
        return Err(format!("{name} must not be empty"));
    }
    if value.chars().any(char::is_control) {
        return Err(format!("{name} must not contain control characters"));
    }
    Ok(())
}

fn write_local_provider_config_at(
    path: &std::path::Path,
    config: &ProviderConfig,
) -> Result<(), String> {
    let Some(parent) = path.parent() else {
        return Err("local provider config path has no parent".to_owned());
    };
    fs::create_dir_all(parent)
        .map_err(|error| format!("could not create config directory: {error}"))?;
    let contents = format!(
        "# Hades Agent local loopback provider\nbase_url={}\nmodel={}\n",
        config.base_url, config.model
    );
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| format!("could not create config write token: {error}"))?
        .as_nanos();
    let temporary =
        parent.join(format!(".{LOCAL_PROVIDER_CONFIG_FILE}.{}.{stamp}.tmp", process::id()));
    fs::write(&temporary, contents)
        .map_err(|error| format!("could not write local setup: {error}"))?;
    if let Err(error) = fs::rename(&temporary, path) {
        let _ = fs::remove_file(&temporary);
        return Err(format!("could not commit local setup: {error}"));
    }
    Ok(())
}

fn read_local_provider_config() -> Result<Option<ProviderConfig>, String> {
    let Some(path) = local_provider_config_path() else {
        return Ok(None);
    };
    read_local_provider_config_at(&path)
}

fn read_local_provider_config_at(path: &std::path::Path) -> Result<Option<ProviderConfig>, String> {
    let contents = match fs::read_to_string(path) {
        Ok(contents) => contents,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(format!("could not read local provider setup: {error}")),
    };
    let mut base_url = None;
    let mut model = None;
    for (line_number, line) in contents.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            return Err(format!("local provider setup line {} is malformed", line_number + 1));
        };
        let value = value.trim();
        match key.trim() {
            "base_url" if base_url.is_none() => base_url = Some(value.to_owned()),
            "model" if model.is_none() => model = Some(value.to_owned()),
            "api_key" => return Err("local provider setup must not contain api_key".to_owned()),
            "base_url" | "model" => {
                return Err(format!("local provider setup line {} is duplicated", line_number + 1));
            }
            key => return Err(format!("local provider setup has unknown key: {key}")),
        }
    }
    let base_url = base_url.ok_or_else(|| "local provider setup has no base_url".to_owned())?;
    let config = local_provider_config_from_input(&base_url, model.as_deref())?;
    Ok(Some(config))
}

fn restore_terminal(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
) -> Result<(), Box<dyn Error>> {
    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()?;
    Ok(())
}

fn restore_raw_terminal(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
) -> Result<(), Box<dyn Error>> {
    disable_raw_mode()?;
    terminal.show_cursor()?;
    Ok(())
}

fn event_loop(terminal: &mut Terminal<CrosstermBackend<io::Stdout>>) -> Result<(), Box<dyn Error>> {
    let mut app = configured_app();
    let mut provider_runtime = None;
    let mut last_size = size()?;
    loop {
        drain_provider_events(&mut app, &mut provider_runtime);
        let current_size = size()?;
        if current_size != last_size {
            app.handle(InputEvent::Resize { width: current_size.0, height: current_size.1 });
            last_size = current_size;
        }
        app.handle(InputEvent::Tick);
        terminal.draw(|frame| draw(frame, &app))?;
        if app.state().should_quit {
            cancel_provider(&mut provider_runtime);
            return Ok(());
        }

        if event::poll(Duration::from_millis(250))? {
            match event::read()? {
                Event::Key(key) if key.kind == KeyEventKind::Press => {
                    if let Some(mapped) = map_key(key) {
                        dispatch_input(
                            terminal,
                            &mut app,
                            &mut provider_runtime,
                            InputEvent::Key(mapped),
                        )?;
                    }
                }
                Event::Resize(width, height) => {
                    last_size = (width, height);
                    app.handle(InputEvent::Resize { width, height });
                }
                Event::Paste(text) => {
                    dispatch_input(
                        terminal,
                        &mut app,
                        &mut provider_runtime,
                        InputEvent::Paste(text),
                    )?;
                }
                _ => {}
            }
        }
    }
}

fn configured_app() -> App {
    let startup = startup_state_from_provider_configuration(provider_config());
    history_path().map_or_else(
        || App::with_startup_state(startup),
        |path| App::with_history_path_and_startup(path, startup),
    )
}

fn startup_state_from_provider_configuration(
    config: Result<Option<ProviderConfig>, String>,
) -> StartupState {
    match config {
        Ok(Some(_)) | Err(_) => StartupState::Ready,
        Ok(None) => StartupState::Unconfigured,
    }
}

fn history_path() -> Option<PathBuf> {
    history_path_from(
        env::var_os("HERMES_HOME").map(PathBuf::from),
        env::var_os("HOME").map(|home| PathBuf::from(home).join(".hermes")),
    )
}

fn history_path_from(
    hermes_home: Option<PathBuf>,
    home_hermes_dir: Option<PathBuf>,
) -> Option<PathBuf> {
    hermes_home.or(home_hermes_dir).map(|home| home.join(".hermes_history"))
}

fn configured_editor() -> Option<Vec<String>> {
    let visual = env::var("VISUAL").ok();
    let editor = env::var("EDITOR").ok();
    configured_editor_from(visual.as_deref(), editor.as_deref())
}

fn configured_editor_from(visual: Option<&str>, editor: Option<&str>) -> Option<Vec<String>> {
    [visual, editor].into_iter().flatten().find_map(|value| {
        let command = value.split_whitespace().map(str::to_owned).collect::<Vec<_>>();
        (!command.is_empty()).then_some(command)
    })
}

fn dispatch_input(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
    app: &mut App,
    provider_runtime: &mut Option<ProviderRuntime>,
    event: InputEvent,
) -> Result<(), Box<dyn Error>> {
    let event = resolve_clipboard_event(terminal, app, event);
    match app.handle(event) {
        DispatchOutcome::Submitted(_) => start_provider(app, provider_runtime),
        DispatchOutcome::Interrupted => {
            cancel_provider(provider_runtime);
        }
        DispatchOutcome::EditorRequested(draft) => {
            run_editor(terminal, app, draft)?;
            start_provider_from_latest_user(app, provider_runtime);
        }
        DispatchOutcome::Continue | DispatchOutcome::Quit => {}
    }
    Ok(())
}

fn provider_config() -> Result<Option<ProviderConfig>, String> {
    let base_url = env::var(PROVIDER_BASE_URL_ENV).ok();
    let model = env::var(PROVIDER_MODEL_ENV).ok();
    let api_key = env::var(PROVIDER_API_KEY_ENV).ok();
    if base_url.as_deref().is_some_and(|value| !value.trim().is_empty()) {
        return provider_config_from(base_url.as_deref(), model.as_deref(), api_key.as_deref());
    }

    let Some(saved) = read_local_provider_config()? else {
        return Ok(None);
    };
    provider_config_from(
        Some(&saved.base_url),
        model.as_deref().or(Some(saved.model.as_str())),
        api_key.as_deref(),
    )
}

fn provider_config_from(
    base_url: Option<&str>,
    model: Option<&str>,
    api_key: Option<&str>,
) -> Result<Option<ProviderConfig>, String> {
    let Some(base_url) = base_url.map(str::trim).filter(|value| !value.is_empty()) else {
        return Ok(None);
    };
    let model =
        model.map(str::trim).filter(|value| !value.is_empty()).unwrap_or(DEFAULT_PROVIDER_MODEL);
    let api_key = api_key.filter(|value| !value.is_empty()).map(str::to_owned);
    Ok(Some(ProviderConfig { base_url: base_url.to_owned(), model: model.to_owned(), api_key }))
}

fn start_provider_from_latest_user(app: &mut App, provider_runtime: &mut Option<ProviderRuntime>) {
    if app.state().turn != TurnState::Busy {
        return;
    }
    let has_latest_user =
        app.state().messages.last().is_some_and(|message| message.role == Role::User);
    if !has_latest_user {
        app.handle(InputEvent::Provider(ProviderEvent::Failed(
            "provider request has no user message".to_owned(),
        )));
        return;
    }
    start_provider(app, provider_runtime);
}

fn start_provider(app: &mut App, provider_runtime: &mut Option<ProviderRuntime>) {
    cancel_provider(provider_runtime);
    let config = match provider_config() {
        Ok(Some(config)) => config,
        Ok(None) => {
            app.handle(InputEvent::Provider(ProviderEvent::Failed(format!(
                "{PROVIDER_BASE_URL_ENV} is not set"
            ))));
            return;
        }
        Err(error) => {
            app.handle(InputEvent::Provider(ProviderEvent::Failed(error)));
            return;
        }
    };

    let transport = match LocalOpenAiTransport::new(&config.base_url, config.api_key) {
        Ok(transport) => transport,
        Err(error) => {
            app.handle(InputEvent::Provider(ProviderEvent::Failed(error.to_string())));
            return;
        }
    };
    let model = provider_request_model(app, &config.model);
    let request = ChatRequest::new(model, provider_request_messages(app), Vec::new());
    let cancellation = CancellationToken::new();
    let worker_cancellation = cancellation.clone();
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || run_provider_worker(transport, request, sender, worker_cancellation));
    *provider_runtime = Some(ProviderRuntime { events: receiver, cancellation });
}

fn provider_request_messages(app: &App) -> Vec<ChatMessage> {
    let mut messages = vec![ChatMessage::new("system", PROVIDER_SYSTEM_PROMPT)];
    messages.extend(app.provider_conversation().into_iter().map(|message| {
        let role = match message.role {
            Role::System => "system",
            Role::User => "user",
            Role::Assistant => "assistant",
        };
        ChatMessage::new(role, message.content)
    }));
    messages
}

fn provider_request_model(app: &App, configured_model: &str) -> String {
    app.selected_model().unwrap_or(configured_model).to_owned()
}

fn cancel_provider(provider_runtime: &mut Option<ProviderRuntime>) {
    if let Some(runtime) = provider_runtime.take() {
        runtime.cancellation.cancel();
    }
}

fn run_provider_worker(
    transport: LocalOpenAiTransport,
    request: ChatRequest,
    sender: Sender<ProviderEvent>,
    cancellation: CancellationToken,
) {
    if sender.send(ProviderEvent::Started).is_err() {
        return;
    }
    let mut stream = match transport.open_stream(&request, &cancellation) {
        Ok(stream) => stream,
        Err(TransportError::Cancelled) => return,
        Err(error) => {
            let _ = sender.send(ProviderEvent::Failed(error.to_string()));
            return;
        }
    };
    loop {
        match stream.next_event() {
            Ok(Some(event)) => {
                let is_done = event == StreamEvent::Done;
                if sender.send(translate_stream_event(event)).is_err() {
                    return;
                }
                if is_done {
                    return;
                }
            }
            Ok(None) => return,
            Err(TransportError::Cancelled) => return,
            Err(error) => {
                let _ = sender.send(ProviderEvent::Failed(error.to_string()));
                return;
            }
        }
    }
}

fn translate_stream_event(event: StreamEvent) -> ProviderEvent {
    match event {
        StreamEvent::TextDelta(text) => ProviderEvent::TextDelta(text),
        StreamEvent::Done => ProviderEvent::Completed,
    }
}

fn drain_provider_events(app: &mut App, provider_runtime: &mut Option<ProviderRuntime>) {
    let Some(runtime) = provider_runtime.as_ref() else {
        return;
    };
    loop {
        match runtime.events.try_recv() {
            Ok(event) => {
                let terminal = matches!(
                    event,
                    ProviderEvent::Completed | ProviderEvent::Failed(_) | ProviderEvent::Cancelled
                );
                app.handle(InputEvent::Provider(event));
                if terminal && app.state().turn == TurnState::Ready {
                    provider_runtime.take();
                    return;
                }
            }
            Err(TryRecvError::Empty) => return,
            Err(TryRecvError::Disconnected) => {
                provider_runtime.take();
                if app.state().turn == TurnState::Busy {
                    app.handle(InputEvent::Provider(ProviderEvent::Failed(
                        "provider worker stopped unexpectedly".to_owned(),
                    )));
                }
                return;
            }
        }
    }
}

fn resolve_clipboard_event(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
    app: &App,
    event: InputEvent,
) -> InputEvent {
    resolve_clipboard_event_with_providers(
        app,
        event,
        || osc52::read_usable_text(terminal.backend_mut()),
        clipboard::read_usable_text,
    )
}

#[cfg(test)]
fn resolve_clipboard_event_with<F>(app: &App, event: InputEvent, read: F) -> InputEvent
where
    F: FnOnce() -> Option<String>,
{
    resolve_clipboard_event_with_providers(app, event, || None, read)
}

fn resolve_clipboard_event_with_providers<R, N>(
    app: &App,
    event: InputEvent,
    remote_read: R,
    native_read: N,
) -> InputEvent
where
    R: FnOnce() -> Option<String>,
    N: FnOnce() -> Option<String>,
{
    match event {
        InputEvent::Key(Key::Ctrl('v'))
            if app.state().turn == TurnState::Ready && app.state().overlay.is_none() =>
        {
            remote_read()
                .or_else(native_read)
                .map_or(InputEvent::Key(Key::Ctrl('v')), InputEvent::Paste)
        }
        other => other,
    }
}

fn run_editor(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
    app: &mut App,
    draft: String,
) -> Result<(), Box<dyn Error>> {
    let Some(editor) = configured_editor() else {
        return Ok(());
    };

    let path = create_editor_file(&draft)?;
    let editor_result = (|| -> Result<Option<String>, Box<dyn Error>> {
        disable_raw_mode()?;
        execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
        terminal.show_cursor()?;

        let (program, arguments) = editor.split_first().expect("configured editor is non-empty");
        let status = Command::new(program).args(arguments).arg(&path).status()?;
        if !status.success() {
            return Ok(None);
        }

        Ok(Some(fs::read_to_string(&path)?))
    })();
    let restore_result = restore_editor_terminal(terminal);
    let remove_result = fs::remove_file(&path);

    restore_result?;
    remove_result?;
    if let Some(edited_draft) = editor_result? {
        app.submit_editor_draft(edited_draft);
    }
    Ok(())
}

fn create_editor_file(draft: &str) -> Result<PathBuf, Box<dyn Error>> {
    let timestamp = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let path = env::temp_dir().join(format!("hades-editor-{}-{timestamp}.txt", std::process::id()));
    let mut file = OpenOptions::new().create_new(true).write(true).open(&path)?;
    file.write_all(draft.as_bytes())?;
    file.flush()?;
    Ok(path)
}

fn restore_editor_terminal(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
) -> Result<(), Box<dyn Error>> {
    enable_raw_mode()?;
    execute!(terminal.backend_mut(), EnterAlternateScreen)?;
    terminal.clear()?;
    terminal.hide_cursor()?;
    Ok(())
}

fn map_key(key: KeyEvent) -> Option<Key> {
    let control = key.modifiers.contains(KeyModifiers::CONTROL);
    let modified_enter = key.modifiers.intersects(KeyModifiers::SHIFT | KeyModifiers::ALT);
    match key.code {
        KeyCode::Char(character) if control => Some(Key::Ctrl(character)),
        KeyCode::Char(character) => Some(Key::Char(character)),
        KeyCode::Enter if modified_enter => Some(Key::ModifiedEnter),
        KeyCode::Enter => Some(Key::Enter),
        KeyCode::Backspace => Some(Key::Backspace),
        KeyCode::Esc => Some(Key::Escape),
        KeyCode::Tab => Some(Key::Tab),
        KeyCode::Up => Some(Key::Up),
        KeyCode::Down => Some(Key::Down),
        KeyCode::Left => Some(Key::Left),
        KeyCode::Right => Some(Key::Right),
        KeyCode::Home => Some(Key::Home),
        KeyCode::End => Some(Key::End),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cli_dispatch_keeps_default_and_explicit_tui_on_the_same_path() {
        assert_eq!(cli_command(None), Ok(CliCommand::Tui));
        assert_eq!(cli_command(Some("tui")), Ok(CliCommand::Tui));
    }

    #[test]
    fn cli_dispatch_preserves_non_tui_modes_and_unknown_arguments() {
        assert_eq!(cli_command(Some("--help")), Ok(CliCommand::Help));
        assert_eq!(cli_command(Some("--version")), Ok(CliCommand::Version));
        assert_eq!(cli_command(Some("--snapshot")), Ok(CliCommand::Snapshot));
        assert_eq!(cli_command(Some("setup")), Ok(CliCommand::Setup));
        assert_eq!(cli_command(Some("wat")), Err("wat"));
    }

    #[test]
    fn cli_dispatch_accepts_explicit_local_setup_arguments() {
        let arguments = ["setup", "--local", "http://127.0.0.1:8765/v1", "palette-model"]
            .into_iter()
            .map(str::to_owned)
            .collect::<Vec<_>>();
        assert_eq!(
            cli_command_from_args(&arguments),
            Ok(CliCommand::SetupLocal {
                base_url: "http://127.0.0.1:8765/v1".to_owned(),
                model: Some("palette-model".to_owned()),
            })
        );
    }

    #[test]
    fn standalone_setup_config_path_prefers_hermes_home_without_reading_existing_state() {
        assert_eq!(
            standalone_setup_config_path_from(
                Some(PathBuf::from("/synthetic/hermes")),
                Some(PathBuf::from("/synthetic/home")),
            ),
            Some(PathBuf::from("/synthetic/hermes/config.yaml"))
        );
        assert_eq!(
            standalone_setup_config_path_from(None, Some(PathBuf::from("/synthetic/home"))),
            Some(PathBuf::from("/synthetic/home/.hermes/config.yaml"))
        );
        assert_eq!(standalone_setup_config_path_from(None, None), None);
    }

    #[test]
    fn standalone_setup_state_path_is_a_hades_owned_sidecar() {
        assert_eq!(
            standalone_setup_state_path_from(
                Some(PathBuf::from("/synthetic/hermes")),
                Some(PathBuf::from("/synthetic/home")),
            ),
            Some(PathBuf::from("/synthetic/hermes/hades-setup-boundary.conf"))
        );
        assert_eq!(
            standalone_setup_state_path_from(None, Some(PathBuf::from("/synthetic/home"))),
            Some(PathBuf::from("/synthetic/home/.hermes/hades-setup-boundary.conf"))
        );
        assert_eq!(standalone_setup_state_path_from(None, None), None);
    }

    #[test]
    fn standalone_setup_state_write_is_atomic_duplicate_safe_and_non_secret() {
        let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let directory = env::temp_dir().join(format!("hades-setup-state-test-{stamp}"));
        let path = directory.join(STANDALONE_SETUP_STATE_FILE);

        write_standalone_setup_state_at(&path).unwrap();
        let first = fs::read_to_string(&path).unwrap();
        assert_eq!(first, STANDALONE_SETUP_STATE_CONTENT);
        assert!(!first.contains("api_key"));
        assert!(!first.to_lowercase().contains("oauth"));
        assert!(!first.to_lowercase().contains("token"));

        write_standalone_setup_state_at(&path).unwrap();
        let second = fs::read_to_string(&path).unwrap();
        assert_eq!(second, first);
        let entries = fs::read_dir(&directory).unwrap().collect::<Result<Vec<_>, _>>().unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].file_name(), STANDALONE_SETUP_STATE_FILE);

        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn local_provider_config_path_stays_separate_from_hermes_config() {
        assert_eq!(
            local_provider_config_path_from(
                Some(PathBuf::from("/synthetic/hermes")),
                Some(PathBuf::from("/synthetic/home")),
            ),
            Some(PathBuf::from("/synthetic/hermes/hades-local-provider.conf"))
        );
    }

    #[test]
    fn local_setup_round_trips_only_loopback_provider_and_model() {
        let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let path = env::temp_dir().join(format!("hades-local-setup-test-{stamp}.conf"));
        let config =
            local_provider_config_from_input(" http://127.0.0.1:8765/v1 ", Some(" demo-model "))
                .unwrap();
        write_local_provider_config_at(&path, &config).unwrap();
        let loaded = read_local_provider_config_at(&path).unwrap().unwrap();
        assert_eq!(loaded.base_url, "http://127.0.0.1:8765/v1");
        assert_eq!(loaded.model, "demo-model");
        let contents = fs::read_to_string(&path).unwrap();
        assert!(contents.contains("base_url=http://127.0.0.1:8765/v1"));
        assert!(contents.contains("model=demo-model"));
        assert!(!contents.contains("api_key"));
        let _ = fs::remove_file(path);
    }

    #[test]
    fn local_setup_rejects_non_loopback_provider() {
        let error = local_provider_config_from_input("https://example.com/v1", None).unwrap_err();
        assert!(error.contains("local provider endpoint rejected"));
    }

    #[test]
    fn provider_config_is_opt_in_and_defaults_the_model_without_logging_key_material() {
        assert!(provider_config_from(None, None, None).unwrap().is_none());

        let config = provider_config_from(
            Some(" http://127.0.0.1:8765/v1 "),
            Some("  "),
            Some("synthetic-key"),
        )
        .unwrap()
        .unwrap();
        assert_eq!(config.base_url, "http://127.0.0.1:8765/v1");
        assert_eq!(config.model, DEFAULT_PROVIDER_MODEL);
        assert_eq!(config.api_key.as_deref(), Some("synthetic-key"));
    }

    #[test]
    fn startup_state_treats_saved_or_invalid_provider_configuration_as_configured_boundary() {
        assert_eq!(startup_state_from_provider_configuration(Ok(None)), StartupState::Unconfigured);
        assert_eq!(
            startup_state_from_provider_configuration(Ok(Some(ProviderConfig {
                base_url: "http://127.0.0.1:8765/v1".to_owned(),
                model: "palette-model".to_owned(),
                api_key: None,
            }))),
            StartupState::Ready
        );
        assert_eq!(
            startup_state_from_provider_configuration(Err("invalid saved setup".to_owned())),
            StartupState::Ready
        );
    }

    #[test]
    fn stream_events_translate_to_core_provider_events() {
        assert_eq!(
            translate_stream_event(StreamEvent::TextDelta("hello".to_owned())),
            ProviderEvent::TextDelta("hello".to_owned())
        );
        assert_eq!(translate_stream_event(StreamEvent::Done), ProviderEvent::Completed);
    }

    #[test]
    fn provider_channel_drains_a_turn_and_drops_the_runtime_on_completion() {
        let mut app = App::new();
        app.handle(InputEvent::Key(Key::Char('h')));
        app.handle(InputEvent::Key(Key::Enter));
        let (sender, receiver) = mpsc::channel();
        let mut runtime =
            Some(ProviderRuntime { events: receiver, cancellation: CancellationToken::new() });
        sender.send(ProviderEvent::Started).unwrap();
        sender.send(ProviderEvent::TextDelta("hello".to_owned())).unwrap();
        sender.send(ProviderEvent::Completed).unwrap();

        drain_provider_events(&mut app, &mut runtime);

        assert!(runtime.is_none());
        assert_eq!(app.state().turn, TurnState::Ready);
        assert_eq!(app.state().messages.last().unwrap().content, "hello");
    }

    #[test]
    fn provider_request_contains_one_system_prompt_and_completed_context() {
        let mut app = App::new();
        app.submit_editor_draft("first".to_owned());
        app.handle(InputEvent::Provider(ProviderEvent::Started));
        app.handle(InputEvent::Provider(ProviderEvent::TextDelta("answer".to_owned())));
        app.handle(InputEvent::Provider(ProviderEvent::Completed));
        app.submit_editor_draft("second".to_owned());

        assert_eq!(
            provider_request_messages(&app),
            vec![
                ChatMessage::new("system", PROVIDER_SYSTEM_PROMPT),
                ChatMessage::new("user", "first"),
                ChatMessage::new("assistant", "answer"),
                ChatMessage::new("user", "second")
            ]
        );
    }

    #[test]
    fn provider_request_model_prefers_session_selection_without_mutating_configuration() {
        let mut app = App::new();
        for character in "/model".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        app.handle(InputEvent::Key(Key::Enter));
        app.handle(InputEvent::Key(Key::Enter));
        for character in "palette".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        app.handle(InputEvent::Key(Key::Enter));
        app.handle(InputEvent::Key(Key::Enter));

        let configured_model = "vertical-model";
        assert_eq!(provider_request_model(&app, configured_model), "palette-model");
        assert_eq!(configured_model, "vertical-model");
        assert_eq!(provider_request_model(&App::new(), configured_model), configured_model);
    }

    #[test]
    fn control_key_mapping_is_explicit() {
        let key = KeyEvent::new(KeyCode::Char('c'), KeyModifiers::CONTROL);
        assert_eq!(map_key(key), Some(Key::Ctrl('c')));
    }

    #[test]
    fn cursor_key_mapping_is_explicit() {
        assert_eq!(map_key(KeyEvent::new(KeyCode::Home, KeyModifiers::NONE)), Some(Key::Home));
        assert_eq!(map_key(KeyEvent::new(KeyCode::End, KeyModifiers::NONE)), Some(Key::End));
        assert_eq!(map_key(KeyEvent::new(KeyCode::Tab, KeyModifiers::NONE)), Some(Key::Tab));
    }

    #[test]
    fn modified_enter_mapping_preserves_shift_and_alt_newline_inputs() {
        assert_eq!(
            map_key(KeyEvent::new(KeyCode::Enter, KeyModifiers::SHIFT)),
            Some(Key::ModifiedEnter)
        );
        assert_eq!(
            map_key(KeyEvent::new(KeyCode::Enter, KeyModifiers::ALT)),
            Some(Key::ModifiedEnter)
        );
        assert_eq!(map_key(KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE)), Some(Key::Enter));
    }

    #[test]
    fn history_path_prefers_hermes_home_and_falls_back_to_home() {
        assert_eq!(
            history_path_from(
                Some(PathBuf::from("/tmp/hermes")),
                Some(PathBuf::from("/tmp/home/.hermes"))
            ),
            Some(PathBuf::from("/tmp/hermes/.hermes_history"))
        );
        assert_eq!(
            history_path_from(None, Some(PathBuf::from("/tmp/home/.hermes"))),
            Some(PathBuf::from("/tmp/home/.hermes/.hermes_history"))
        );
        assert_eq!(history_path_from(None, None), None);
    }

    #[test]
    fn configured_editor_prefers_nonempty_visual_and_splits_arguments() {
        assert_eq!(
            configured_editor_from(Some("perl -0pi"), Some("/bin/true")),
            Some(vec!["perl".to_owned(), "-0pi".to_owned()])
        );
        assert_eq!(
            configured_editor_from(Some("  "), Some("/bin/true")),
            Some(vec!["/bin/true".to_owned()])
        );
        assert_eq!(configured_editor_from(None, None), None);
    }

    #[test]
    fn ready_ctrl_v_resolves_usable_text_to_a_non_submitting_paste_event() {
        let app = App::new();
        let event = resolve_clipboard_event_with_providers(
            &app,
            InputEvent::Key(Key::Ctrl('v')),
            || Some("remote-one".to_owned()),
            || Some("native-two".to_owned()),
        );

        assert_eq!(event, InputEvent::Paste("remote-one".to_owned()));
    }

    #[test]
    fn remote_clipboard_falls_back_to_native_text_when_remote_is_unavailable() {
        let app = App::new();
        let event = resolve_clipboard_event_with_providers(
            &app,
            InputEvent::Key(Key::Ctrl('v')),
            || None,
            || Some("native-two".to_owned()),
        );

        assert_eq!(event, InputEvent::Paste("native-two".to_owned()));
    }

    #[test]
    fn empty_clipboard_keeps_the_existing_fallback_event() {
        let app = App::new();
        let event = resolve_clipboard_event_with(&app, InputEvent::Key(Key::Ctrl('v')), || None);

        assert_eq!(event, InputEvent::Key(Key::Ctrl('v')));
    }

    #[test]
    fn clipboard_is_not_read_for_busy_or_overlay_states() {
        let mut busy = App::new();
        busy.handle(InputEvent::Key(Key::Char('x')));
        busy.handle(InputEvent::Key(Key::Enter));
        let busy_event =
            resolve_clipboard_event_with(&busy, InputEvent::Key(Key::Ctrl('v')), || {
                panic!("busy clipboard must not be read")
            });
        assert_eq!(busy_event, InputEvent::Key(Key::Ctrl('v')));

        let mut overlay = App::new();
        overlay.handle(InputEvent::Key(Key::Ctrl('x')));
        let overlay_event =
            resolve_clipboard_event_with(&overlay, InputEvent::Key(Key::Ctrl('v')), || {
                panic!("overlay clipboard must not be read")
            });
        assert_eq!(overlay_event, InputEvent::Key(Key::Ctrl('v')));
    }
}
