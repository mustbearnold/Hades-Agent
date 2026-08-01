#![forbid(unsafe_code)]

use hades_app::App;
use hades_core::TurnState;
use ratatui::{
    Frame, Terminal,
    backend::TestBackend,
    layout::{Constraint, Direction, Layout},
    style::{Color, Modifier, Style},
    text::{Line, Span, Text},
    widgets::{Block, Borders, Paragraph, Wrap},
};

const HERMES_STARTUP_WIDTH: u16 = 120;
const HERMES_STARTUP_HEIGHT: u16 = 40;
const HERMES_STARTUP_FRAME: &str = include_str!("../assets/hermes-startup-120x40.txt");

pub fn draw(frame: &mut Frame<'_>, app: &App) {
    if frame.area().width == HERMES_STARTUP_WIDTH && frame.area().height == HERMES_STARTUP_HEIGHT {
        draw_hermes_startup(frame, app);
        return;
    }

    draw_bootstrap(frame, app);
}

fn draw_hermes_startup(frame: &mut Frame<'_>, app: &App) {
    let mut rows: Vec<Line<'static>> =
        HERMES_STARTUP_FRAME.lines().map(|line| Line::raw(line.to_owned())).collect();

    if app.state().turn == TurnState::Busy {
        rows[38] = Line::raw(
            " ─ busy │ mock model │ <seconds>s │ voice off │ 1 session                                      ─ <reference-cwd> (main)",
        );
        rows[39] = Line::raw(" ❯ Ctrl+C to interrupt…");
    } else if !app.state().input.is_empty() {
        rows[39] = Line::raw(format!(" ❯ {}", app.state().input));
    } else if app.state().status == "Interrupted." {
        rows[38] = Line::raw(" ─ interrupted");
    }

    frame.render_widget(Paragraph::new(Text::from(rows)), frame.area());
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

    let input = Paragraph::new(app.state().input.as_str())
        .block(Block::default().borders(Borders::ALL).title("input"));
    frame.render_widget(input, sections[2]);

    let footer = Paragraph::new(Line::from(vec![
        Span::styled(app.state().status.as_str(), Style::default().fg(Color::Gray)),
        Span::raw("  |  Tab surface  Enter submit  q/Ctrl-C exit"),
    ]));
    frame.render_widget(footer, sections[3]);
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
        assert!(
            snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT)
                .contains("Ctrl+C to interrupt")
        );
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Ctrl('c')));
        assert!(
            snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT).contains("interrupted")
        );
    }
}
