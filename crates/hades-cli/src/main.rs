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
    SETUP_STANDALONE_PROMPT, SETUP_WIZARD_CHOICES, SetupWizardState, StartupState, TurnState,
};
use hades_provider::{
    CancellationToken, ChatMessage, ChatRequest, LocalOpenAiTransport, StreamEvent, TransportError,
};
use hades_tui::{draw, draw_standalone_setup, snapshot};
use ratatui::{Terminal, backend::CrosstermBackend};
use signal_hook::{consts::SIGINT, flag};

const DEFAULT_PROVIDER_MODEL: &str = "palette-model";
const PROVIDER_BASE_URL_ENV: &str = "HADES_PROVIDER_BASE_URL";
const PROVIDER_MODEL_ENV: &str = "HADES_MODEL";
const PROVIDER_API_KEY_ENV: &str = "HADES_PROVIDER_API_KEY";
const PROVIDER_SYSTEM_PROMPT: &str = "You are Hades Agent. Respond concisely to the user.";

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
    match cli_command(env::args().nth(1).as_deref()) {
        Ok(CliCommand::Help) => {
            println!("{PRODUCT_NAME}\n\nUsage: hades [tui|setup|--snapshot|--help|--version]");
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
        Ok(CliCommand::Setup) => {
            if matches!(run_setup()?, SetupOutcome::Cancelled) {
                process::exit(1);
            }
            Ok(())
        }
        Err(argument) => Err(format!("unknown argument: {argument}").into()),
    }
}

#[derive(Debug, Eq, PartialEq)]
enum CliCommand {
    Tui,
    Setup,
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
}

#[derive(Debug)]
enum SetupTransition {
    NumberedFallback(SetupWizardState),
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
            while !cancelled.load(Ordering::Relaxed) {
                thread::sleep(Duration::from_millis(25));
            }
            Ok(SetupOutcome::Cancelled)
        }
    }
}

fn setup_choice_loop(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
) -> Result<SetupTransition, Box<dyn Error>> {
    let mut wizard = SetupWizardState::default();
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
        if mapped == Key::Escape {
            wizard.handle_key(mapped);
            return Ok(SetupTransition::NumberedFallback(wizard));
        }
        wizard.handle_key(mapped);
    }
}

fn print_setup_fallback(wizard: &SetupWizardState) -> io::Result<()> {
    let mut stdout = io::stdout();
    writeln!(stdout, "{SETUP_STANDALONE_PROMPT}")?;
    for (index, choice) in SETUP_WIZARD_CHOICES.iter().enumerate() {
        let cursor = if index == wizard.cursor() { "→" } else { " " };
        let selected = if index == wizard.selected() { "●" } else { "○" };
        writeln!(stdout, " {cursor} ({selected}) {choice}")?;
    }
    writeln!(stdout, "    Enter for default (1)  Ctrl+C to exit")?;
    write!(stdout, "  Select [1-3] (1): ")?;
    stdout.flush()
}

fn restore_terminal(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
) -> Result<(), Box<dyn Error>> {
    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
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
    let startup =
        startup_state_from_provider_endpoint(env::var(PROVIDER_BASE_URL_ENV).ok().as_deref());
    history_path().map_or_else(
        || App::with_startup_state(startup),
        |path| App::with_history_path_and_startup(path, startup),
    )
}

fn startup_state_from_provider_endpoint(endpoint: Option<&str>) -> StartupState {
    endpoint
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map_or(StartupState::Unconfigured, |_| StartupState::Ready)
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
        DispatchOutcome::Submitted(content) => start_provider(app, provider_runtime, content),
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
    provider_config_from(base_url.as_deref(), model.as_deref(), api_key.as_deref())
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
    let Some(content) = app
        .state()
        .messages
        .last()
        .filter(|message| message.role == Role::User)
        .map(|message| message.content.clone())
    else {
        app.handle(InputEvent::Provider(ProviderEvent::Failed(
            "provider request has no user message".to_owned(),
        )));
        return;
    };
    start_provider(app, provider_runtime, content);
}

fn start_provider(app: &mut App, provider_runtime: &mut Option<ProviderRuntime>, content: String) {
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
    let request = ChatRequest::new(
        config.model,
        vec![ChatMessage::new("system", PROVIDER_SYSTEM_PROMPT), ChatMessage::new("user", content)],
        Vec::new(),
    );
    let cancellation = CancellationToken::new();
    let worker_cancellation = cancellation.clone();
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || run_provider_worker(transport, request, sender, worker_cancellation));
    *provider_runtime = Some(ProviderRuntime { events: receiver, cancellation });
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
    fn startup_state_is_unconfigured_without_a_provider_endpoint() {
        assert_eq!(startup_state_from_provider_endpoint(None), StartupState::Unconfigured);
        assert_eq!(startup_state_from_provider_endpoint(Some("  ")), StartupState::Unconfigured);
        assert_eq!(
            startup_state_from_provider_endpoint(Some("http://127.0.0.1:8765/v1")),
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
