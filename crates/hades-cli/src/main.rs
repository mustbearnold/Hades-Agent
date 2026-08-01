#![forbid(unsafe_code)]

use std::{env, error::Error, io, time::Duration};

use crossterm::{
    event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers},
    execute,
    terminal::{EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode},
};
use hades_app::App;
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
    let mut app = App::new();
    loop {
        terminal.draw(|frame| draw(frame, &app))?;
        if app.state().should_quit {
            return Ok(());
        }

        if event::poll(Duration::from_millis(250))? {
            match event::read()? {
                Event::Key(key) if key.kind == KeyEventKind::Press => {
                    if let Some(mapped) = map_key(key) {
                        app.handle(InputEvent::Key(mapped));
                    }
                }
                Event::Resize(width, height) => {
                    app.handle(InputEvent::Resize { width, height });
                }
                _ => {}
            }
        }
    }
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
    }
}
