#![forbid(unsafe_code)]

use hades_app::App;
use ratatui::{
    Frame, Terminal,
    backend::TestBackend,
    layout::{Constraint, Direction, Layout},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph, Wrap},
};

pub fn draw(frame: &mut Frame<'_>, app: &App) {
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
}
