#![forbid(unsafe_code)]

use hades_app::App;
use hades_core::{Overlay, TurnState};
use ratatui::{
    Frame, Terminal,
    backend::TestBackend,
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span, Text},
    widgets::{Block, Borders, Clear, Paragraph, Wrap},
};

const HERMES_STARTUP_WIDTH: u16 = 120;
const HERMES_STARTUP_HEIGHT: u16 = 40;
const HERMES_STARTUP_FRAME: &str = include_str!("../assets/hermes-startup-120x40.txt");
const HERMES_BUSY_FOOTER: &str = " ─ musing… │ mulling… │ mock model │ <seconds>s │ voice off │ 1 session                                      ─ <reference-cwd> (main)";
const HERMES_INTERRUPT_PROMPT: &str = " ❯ Ctrl+C to interrupt…";
const HERMES_INTERRUPTED_MARKER: &str = " │ interrupted";
const HERMES_INTERRUPTED_FOOTER: &str = " ─ ready │ mock model │ ✓ <seconds>s │ voice off │ 1 session                                      ─ <reference-cwd> (main)";
const HERMES_CLIPBOARD_MISS: &str = "No image found in clipboard";

pub fn draw(frame: &mut Frame<'_>, app: &App) {
    if frame.area().width == HERMES_STARTUP_WIDTH && frame.area().height == HERMES_STARTUP_HEIGHT {
        draw_hermes_startup(frame, app);
    } else {
        draw_bootstrap(frame, app);
    }

    match app.state().overlay {
        Some(Overlay::Sessions) => draw_sessions_overlay(frame),
        Some(Overlay::SetupRequired) => draw_setup_required_overlay(frame, app),
        None => {}
    }
}

fn draw_hermes_startup(frame: &mut Frame<'_>, app: &App) {
    let mut rows: Vec<Line<'static>> =
        HERMES_STARTUP_FRAME.lines().map(|line| Line::raw(line.to_owned())).collect();

    if app.state().turn == TurnState::Busy {
        rows[38] = Line::raw(HERMES_BUSY_FOOTER);
        rows[39] = Line::raw(HERMES_INTERRUPT_PROMPT);
    } else if !app.state().composer.text().is_empty() {
        draw_hermes_composer(&mut rows, app.state().composer.text());
    } else if app.state().status == "Interrupted." {
        rows[37] = Line::raw(HERMES_INTERRUPTED_MARKER);
        rows[38] = Line::raw(HERMES_INTERRUPTED_FOOTER);
        rows[39] = Line::raw(" ❯ <prompt-placeholder>");
    }

    if app.state().completion.is_visible() {
        draw_hermes_completion(&mut rows, app.state().completion.items());
    }
    if app.state().status == HERMES_CLIPBOARD_MISS {
        rows[37] = Line::raw(format!(" │ {HERMES_CLIPBOARD_MISS}"));
    }

    frame.render_widget(Paragraph::new(Text::from(rows)), frame.area());
}

fn draw_hermes_composer(rows: &mut [Line<'static>], input: &str) {
    let lines: Vec<&str> = input.split('\n').collect();
    let start = 39usize.saturating_sub(lines.len().saturating_sub(1));
    if start >= rows.len() {
        return;
    }

    for (offset, line) in lines.iter().enumerate() {
        let row = start + offset;
        if row < rows.len() {
            rows[row] = Line::raw(format!(" {}{}", if offset == 0 { "❯ " } else { "  " }, line));
        }
    }
}

fn draw_hermes_completion(rows: &mut [Line<'static>], items: &[String]) {
    let header_row = 33usize;
    if header_row < rows.len() {
        rows[header_row] = Line::raw("  completions");
    }

    for (index, item) in items.iter().enumerate() {
        let row = header_row + 1 + index;
        if row >= rows.len() {
            break;
        }

        let marker = if index == 0 { "▸ " } else { "  " };
        rows[row] = Line::raw(format!(" {}{}", marker, item));
    }
}

fn draw_sessions_overlay(frame: &mut Frame<'_>) {
    let area = centered_rect(frame.area(), 76, 16);
    let content = Text::from(vec![
        Line::raw(" live 1 · resumable 0"),
        Line::raw(""),
        Line::raw(" + new"),
        Line::raw(""),
        Line::raw(" ● current session"),
        Line::raw(""),
        Line::raw(" Enter switch   Ctrl+N new   Ctrl+R refresh"),
        Line::raw(" Ctrl+D close   Esc close"),
    ]);
    let panel =
        Paragraph::new(content).block(Block::default().borders(Borders::ALL).title(" Sessions "));
    frame.render_widget(Clear, area);
    frame.render_widget(panel, area);
}

fn draw_setup_required_overlay(frame: &mut Frame<'_>, app: &App) {
    let area = centered_rect(frame.area(), 84, 14);
    let content = Text::from(vec![
        Line::raw(" Hermes needs a model provider before the TUI can start a session."),
        Line::raw(""),
        Line::raw(" /model"),
        Line::raw(" /setup"),
        Line::raw(""),
        Line::raw(" Ctrl+C"),
        Line::raw(""),
        Line::raw(format!(" ❯ {}", app.state().composer.text())),
    ]);
    let panel = Paragraph::new(content)
        .block(Block::default().borders(Borders::ALL).title(" Setup Required "));
    frame.render_widget(Clear, area);
    frame.render_widget(panel, area);
}

fn centered_rect(area: Rect, width: u16, height: u16) -> Rect {
    let width = width.min(area.width);
    let height = height.min(area.height);
    Rect {
        x: area.x + area.width.saturating_sub(width) / 2,
        y: area.y + area.height.saturating_sub(height) / 2,
        width,
        height,
    }
}

fn draw_bootstrap(frame: &mut Frame<'_>, app: &App) {
    let area = frame.area();
    let sections = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(3),
            Constraint::Min(5),
            Constraint::Length(3),
            Constraint::Length(1),
        ])
        .split(area);

    let header = Paragraph::new(Line::from(vec![
        Span::styled(
            " HADES AGENT ",
            Style::default().fg(Color::Black).bg(Color::Cyan).add_modifier(Modifier::BOLD),
        ),
        Span::raw(format!("  {}", app.state().surface.label())),
    ]))
    .block(Block::default().borders(Borders::ALL).title("session"));
    frame.render_widget(header, sections[0]);

    let messages: Vec<Line<'_>> = app
        .state()
        .messages
        .iter()
        .map(|message| {
            Line::from(vec![
                Span::styled(
                    format!("{}: ", message.role.label()),
                    Style::default().fg(Color::Yellow),
                ),
                Span::raw(message.content.as_str()),
            ])
        })
        .collect();
    let transcript = Paragraph::new(messages)
        .block(Block::default().borders(Borders::ALL).title("transcript"))
        .wrap(Wrap { trim: false });
    frame.render_widget(transcript, sections[1]);

    let input = Paragraph::new(app.state().composer.text())
        .block(Block::default().borders(Borders::ALL).title("input"));
    frame.render_widget(input, sections[2]);

    if app.state().completion.is_visible() {
        draw_bootstrap_completion(frame, app);
    }

    let footer = Paragraph::new(Line::from(vec![
        Span::styled(app.state().status.as_str(), Style::default().fg(Color::Gray)),
        Span::raw("  |  Tab surface  Enter submit  q/Ctrl-C exit"),
    ]));
    frame.render_widget(footer, sections[3]);
}

fn draw_bootstrap_completion(frame: &mut Frame<'_>, app: &App) {
    let area = centered_rect(frame.area(), 58, 7);
    let lines = app
        .state()
        .completion
        .items()
        .iter()
        .enumerate()
        .map(|(index, item)| {
            let marker = if index == 0 { "▸ " } else { "  " };
            Line::raw(format!(" {}{}", marker, item))
        })
        .collect::<Vec<_>>();
    let panel = Paragraph::new(Text::from(lines))
        .block(Block::default().borders(Borders::ALL).title(" Completions "));
    frame.render_widget(Clear, area);
    frame.render_widget(panel, area);
}

pub fn snapshot(app: &App, width: u16, height: u16) -> String {
    let backend = TestBackend::new(width, height);
    let mut terminal = Terminal::new(backend).expect("TestBackend construction is infallible");
    terminal.draw(|frame| draw(frame, app)).expect("TestBackend rendering is infallible");

    let buffer = terminal.backend().buffer();
    let mut lines = Vec::with_capacity(usize::from(height));
    for y in 0..height {
        let mut line = String::with_capacity(usize::from(width));
        for x in 0..width {
            if let Some(cell) = buffer.cell((x, y)) {
                line.push_str(cell.symbol());
            } else {
                line.push(' ');
            }
        }
        lines.push(line.trim_end().to_owned());
    }
    lines.join("\n")
}

pub fn normalize_cells(frame: &str, width: u16, height: u16) -> String {
    frame
        .split('\n')
        .take(usize::from(height))
        .map(|row| row.chars().take(usize::from(width)).collect::<String>())
        .map(|row| row.trim_end_matches(' ').to_owned())
        .collect::<Vec<_>>()
        .join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bootstrap_snapshot_has_stable_landmarks() {
        let rendered = snapshot(&App::new(), 80, 24);

        assert_eq!(rendered.lines().count(), 24);
        assert!(rendered.contains("HADES AGENT"));
        assert!(rendered.contains("transcript"));
        assert!(rendered.contains("Reference behavior pending capture."));
    }

    #[test]
    fn hermes_startup_surface_matches_normalized_golden_frame() {
        let rendered = snapshot(&App::new(), HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        let golden = include_str!("../../../tests/fixtures/parity/OBS-0001-startup-120x40.txt");

        assert_eq!(
            normalize_cells(&rendered, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT),
            normalize_cells(golden, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT)
        );
    }

    #[test]
    fn hermes_startup_surface_reflects_input_and_busy_turn() {
        let mut app = App::new();
        for character in "hello".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }
        assert!(snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT).contains("hello"));

        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        let busy = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(busy.contains("musing…"));
        assert!(busy.contains("mulling…"));
        assert!(busy.contains("Ctrl+C to interrupt…"));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Ctrl('c')));
        let interrupted = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(interrupted.contains("interrupted"));
        assert!(interrupted.contains("✓ <seconds>s"));
    }

    #[test]
    fn hermes_startup_surface_renders_and_closes_sessions_overlay() {
        let mut app = App::new();
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Ctrl('x')));

        let overlay = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        for marker in [
            "Sessions",
            "live 1",
            "resumable 0",
            "+ new",
            "current session",
            "Enter switch",
            "Ctrl+N new",
            "Ctrl+R refresh",
            "Ctrl+D close",
            "Esc close",
        ] {
            assert!(overlay.contains(marker), "missing overlay marker: {marker}");
        }

        app.handle(hades_core::InputEvent::Key(hades_core::Key::Escape));
        let closed = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(!closed.contains("current session"));
        assert!(closed.contains("<prompt-placeholder>"));
    }

    #[test]
    fn hermes_startup_surface_renders_setup_required_overlay_and_clears_input() {
        let mut app = App::new();
        for character in "/help".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));

        let setup = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        for marker in [
            "Setup Required",
            "Hermes needs a model provider before the TUI can start a session.",
            "/model",
            "/setup",
            "Ctrl+C",
            "/help",
        ] {
            assert!(setup.contains(marker), "missing setup marker: {marker}");
        }

        app.handle(hades_core::InputEvent::Key(hades_core::Key::Ctrl('c')));
        let cleared = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(cleared.contains("Setup Required"));
        assert!(!cleared.contains("/help"));
    }

    #[test]
    fn hermes_startup_surface_renders_multiline_composer() {
        let mut app = App::new();
        for character in "line-one\\".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        for character in "line-two".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }

        let rendered = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(rendered.contains("line-one"));
        assert!(rendered.contains("line-two"));
    }

    #[test]
    fn hermes_startup_surface_renders_bracketed_paste_as_multiline_draft() {
        let mut app = App::new();
        app.handle(hades_core::InputEvent::Paste("paste-one\npaste-two".to_owned()));

        let rendered = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(rendered.contains("paste-one"));
        assert!(rendered.contains("paste-two"));
        assert!(!rendered.contains("musing…"));
    }

    #[test]
    fn hermes_startup_surface_renders_empty_clipboard_message() {
        let mut app = App::new();
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Char('x')));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Ctrl('v')));

        let rendered = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(rendered.contains("x"));
        assert!(rendered.contains("No image found in clipboard"));
        assert!(!rendered.contains("musing…"));
    }

    #[test]
    fn hermes_startup_surface_renders_and_applies_slash_completion() {
        let mut app = App::new();
        for character in "/he".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }

        let completion = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        for marker in ["completions", "/help", "/hermes-agent", "/hermes-agent-skill-authoring"] {
            assert!(completion.contains(marker), "missing completion marker: {marker}");
        }

        app.handle(hades_core::InputEvent::Key(hades_core::Key::Tab));
        let applied = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(applied.contains("❯ /help"));
        assert!(!applied.contains("/hermes-agent"));
        assert!(!app.state().completion.is_visible());
    }
}
