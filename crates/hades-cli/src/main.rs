#![forbid(unsafe_code)]

use std::{
    env,
    error::Error,
    fs::{self, OpenOptions},
    io::{self, Write},
    path::PathBuf,
    process::Command,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use crossterm::{
    event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers},
    execute,
    terminal::{EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode},
};
use hades_app::{App, DispatchOutcome};
use hades_core::{InputEvent, Key, PRODUCT_NAME};
use hades_tui::{draw, snapshot};
use ratatui::{Terminal, backend::CrosstermBackend};

fn main() -> Result<(), Box<dyn Error>> {
    match env::args().nth(1).as_deref() {
        Some("--help") | Some("-h") => {
            println!("{PRODUCT_NAME}\n\nUsage: hades [--snapshot|--help|--version]");
            Ok(())
        }
        Some("--version") | Some("-V") => {
            println!("{PRODUCT_NAME} 0.1.0");
            Ok(())
        }
        Some("--snapshot") => {
            println!("{}", snapshot(&App::new(), 120, 40));
            Ok(())
        }
        Some(argument) => Err(format!("unknown argument: {argument}").into()),
        None => run_tui(),
    }
}

fn run_tui() -> Result<(), Box<dyn Error>> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;

    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;
    let result = event_loop(&mut terminal);
    let cleanup = restore_terminal(&mut terminal);

    result.and(cleanup)
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
    loop {
        terminal.draw(|frame| draw(frame, &app))?;
        if app.state().should_quit {
            return Ok(());
        }

        if event::poll(Duration::from_millis(250))? {
            match event::read()? {
                Event::Key(key) if key.kind == KeyEventKind::Press => {
                    if let Some(mapped) = map_key(key) {
                        dispatch_input(terminal, &mut app, InputEvent::Key(mapped))?;
                    }
                }
                Event::Resize(width, height) => {
                    app.handle(InputEvent::Resize { width, height });
                }
                Event::Paste(text) => {
                    dispatch_input(terminal, &mut app, InputEvent::Paste(text))?;
                }
                _ => {}
            }
        }
    }
}

fn configured_app() -> App {
    history_path().map_or_else(App::new, App::with_history_path)
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

fn dispatch_input(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
    app: &mut App,
    event: InputEvent,
) -> Result<(), Box<dyn Error>> {
    if let DispatchOutcome::EditorRequested(draft) = app.handle(event) {
        run_editor(terminal, app, draft)?;
    }
    Ok(())
}

fn run_editor(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
    app: &mut App,
    draft: String,
) -> Result<(), Box<dyn Error>> {
    let Some(editor) = env::var_os("EDITOR") else {
        return Ok(());
    };

    let path = create_editor_file(&draft)?;
    let editor_result = (|| -> Result<Option<String>, Box<dyn Error>> {
        disable_raw_mode()?;
        execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
        terminal.show_cursor()?;

        let status = Command::new(editor).arg(&path).status()?;
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
    match key.code {
        KeyCode::Char(character) if control => Some(Key::Ctrl(character)),
        KeyCode::Char(character) => Some(Key::Char(character)),
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
}
