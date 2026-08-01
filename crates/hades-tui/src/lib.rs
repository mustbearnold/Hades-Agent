#![forbid(unsafe_code)]

use hades_app::App;
use hades_core::{
    MODEL_PICKER_MODEL, MODEL_PICKER_PROVIDER, ModelPickerStage, Notice, Overlay, Role,
    SETUP_PLATFORM_PICKER_CONTROLS, SETUP_PLATFORM_PICKER_TITLE, SETUP_PLATFORM_ROWS,
    SETUP_PROVIDER_ACTIVE_PROVIDER, SETUP_PROVIDER_CURRENT_MODEL, SETUP_PROVIDER_MENU_ROWS,
    SETUP_PROVIDER_MODEL_NAME, SETUP_STANDALONE_CONTROLS, SETUP_STANDALONE_PROMPT,
    SETUP_TERMINAL_BACKEND_CONTROLS, SETUP_TERMINAL_BACKEND_ROWS, SETUP_TERMINAL_BACKEND_TITLE,
    SETUP_WIZARD_CHOICES, SetupWizardState, SetupWizardSurface, StartupState, TurnState,
};
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
const HERMES_UNCONFIGURED_MODEL: &str = " │ glm-5.2 · Nous Research          31 tools · 66 skills · /help for commands                                   │";
const HERMES_UNCONFIGURED_FOOTER: &str = " ─ starting agent… │ glm5.2 │ 0s │ voice off │ 1 session                                      ─ <reference-cwd> (main)";
const HERMES_CLIPBOARD_MISS: &str = "No image found in clipboard";
const HERMES_COMPOSER_MAX_CHARS: usize = 117;

#[derive(Clone, Copy, Debug, Default)]
struct HermesPalette;

const HERMES_PALETTE: HermesPalette = HermesPalette;

impl HermesPalette {
    fn brand(self) -> Style {
        Style::default().fg(Color::Indexed(220)).add_modifier(Modifier::BOLD)
    }

    fn secondary(self) -> Style {
        Style::default().fg(Color::Indexed(178))
    }

    fn ready(self) -> Style {
        Style::default().fg(Color::Indexed(72))
    }

    fn composer(self) -> Style {
        Style::default().fg(Color::Indexed(230))
    }

    fn busy_interrupt(self) -> Style {
        Style::default().fg(Color::Rgb(255, 255, 255)).bg(Color::Rgb(184, 134, 11))
    }
}

pub fn draw(frame: &mut Frame<'_>, app: &App) {
    if frame.area().width == HERMES_STARTUP_WIDTH && frame.area().height == HERMES_STARTUP_HEIGHT {
        draw_hermes_startup(frame, app);
    } else {
        draw_bootstrap(frame, app);
    }

    match app.state().overlay {
        Some(Overlay::Sessions) => draw_sessions_overlay(frame),
        Some(Overlay::ModelPicker) => draw_model_picker_overlay(frame, app),
        Some(Overlay::SetupWizard) => draw_setup_wizard_overlay(frame, app),
        Some(Overlay::SetupRequired) => draw_setup_required_overlay(frame, app),
        None => {}
    }
}

pub fn draw_standalone_setup(frame: &mut Frame<'_>, wizard: &SetupWizardState) {
    let mut lines = vec![Line::from(vec![
        Span::styled(SETUP_STANDALONE_PROMPT, HERMES_PALETTE.brand()),
        Span::raw("  "),
        Span::styled(SETUP_STANDALONE_CONTROLS, HERMES_PALETTE.secondary()),
    ])];

    for (index, choice) in SETUP_WIZARD_CHOICES.iter().enumerate() {
        let cursor = if index == wizard.cursor() { "→" } else { " " };
        let selected = if index == wizard.selected() { "●" } else { "○" };
        let style = if index == wizard.cursor() {
            HERMES_PALETTE.ready()
        } else {
            HERMES_PALETTE.secondary()
        };
        lines.push(Line::styled(format!(" {cursor} ({selected}) {choice}"), style));
    }

    frame.render_widget(Paragraph::new(Text::from(lines)), frame.area());
}

fn draw_hermes_startup(frame: &mut Frame<'_>, app: &App) {
    let mut rows: Vec<String> = HERMES_STARTUP_FRAME.lines().map(str::to_owned).collect();

    if app.state().startup == StartupState::Unconfigured {
        rows[26] = HERMES_UNCONFIGURED_MODEL.to_owned();
        rows[38] = HERMES_UNCONFIGURED_FOOTER.to_owned();
        if app.state().composer.text().is_empty() {
            rows[39].clear();
        } else {
            draw_hermes_composer(&mut rows, app.state().composer.text());
        }
    } else if app.state().turn == TurnState::Busy {
        rows[38] = HERMES_BUSY_FOOTER.to_owned();
        rows[39] = HERMES_INTERRUPT_PROMPT.to_owned();
    } else if !app.state().composer.text().is_empty() {
        draw_hermes_composer(&mut rows, app.state().composer.text());
    } else if app.state().status == "Interrupted." {
        rows[37] = HERMES_INTERRUPTED_MARKER.to_owned();
        rows[38] = HERMES_INTERRUPTED_FOOTER.to_owned();
        rows[39] = " ❯ <prompt-placeholder>".to_owned();
    }

    draw_hermes_response(&mut rows, app);

    if app.state().completion.is_visible() {
        draw_hermes_completion(&mut rows, app.state().completion.items());
    }
    if app.state().status == HERMES_CLIPBOARD_MISS {
        rows[37] = format!(" │ {HERMES_CLIPBOARD_MISS}");
    }
    if let Some(Notice::UnknownCommand { command }) = &app.state().notice {
        rows[36] = format!(" Unknown command: {command}");
        rows[37] = " Type /help for available commands".to_owned();
    }
    match &app.state().notice {
        Some(Notice::ProviderError { message }) => {
            rows[36] = format!(" Provider error: {}", bounded_composer_line(message));
        }
        Some(Notice::ProviderCancelled) => {
            rows[36] = " Provider response cancelled".to_owned();
        }
        _ => {}
    }

    let styled_rows =
        rows.iter().enumerate().map(|(row, line)| style_hermes_line(row, line)).collect::<Vec<_>>();
    frame.render_widget(Paragraph::new(Text::from(styled_rows)), frame.area());
}

fn draw_hermes_response(rows: &mut [String], app: &App) {
    let Some(message) =
        app.state().messages.iter().rev().find(|message| message.role == Role::Assistant)
    else {
        return;
    };

    let lines = message.content.split('\n').collect::<Vec<_>>();
    let end = 37usize.min(rows.len().saturating_sub(1));
    let available = end.saturating_sub(32) + 1;
    let start = lines.len().saturating_sub(available);
    for (offset, line) in lines[start..].iter().enumerate() {
        let row = 32 + offset;
        if row <= end {
            rows[row] = format!(" {}", bounded_composer_line(line));
        }
    }
}

fn draw_hermes_composer(rows: &mut [String], input: &str) {
    let lines: Vec<&str> = input.split('\n').collect();
    let start = 39usize.saturating_sub(lines.len().saturating_sub(1));
    if start >= rows.len() {
        return;
    }

    for (offset, line) in lines.iter().enumerate() {
        let row = start + offset;
        if row < rows.len() {
            rows[row] = format!(
                " {}{}",
                if offset == 0 { "❯ " } else { "  " },
                bounded_composer_line(line),
            );
        }
    }
}

fn bounded_composer_line(line: &str) -> String {
    if line.chars().count() <= HERMES_COMPOSER_MAX_CHARS {
        return line.to_owned();
    }

    line.chars().rev().take(HERMES_COMPOSER_MAX_CHARS).collect::<String>().chars().rev().collect()
}

fn draw_hermes_completion(rows: &mut [String], items: &[String]) {
    let header_row = 33usize;
    if header_row < rows.len() {
        rows[header_row] = "  completions".to_owned();
    }

    for (index, item) in items.iter().enumerate() {
        let row = header_row + 1 + index;
        if row >= rows.len() {
            break;
        }

        let marker = if index == 0 { "▸ " } else { "  " };
        rows[row] = format!(" {}{}", marker, item);
    }
}

fn style_hermes_line(row: usize, line: &str) -> Line<'static> {
    let mut markers = Vec::new();
    match row {
        7 => markers.push(("Nous Research", HERMES_PALETTE.secondary())),
        11 => markers.push(("Hermes Agent", HERMES_PALETTE.brand())),
        14 => markers.push(("Available Tools", HERMES_PALETTE.brand())),
        25 => markers.push(("Available Skills", HERMES_PALETTE.brand())),
        38 => {
            markers.push(("ready", HERMES_PALETTE.ready()));
            markers.push(("✓", HERMES_PALETTE.secondary()));
        }
        39 if line.contains("Ctrl+C to interrupt") => {
            markers.push(("Ctrl+C to interrupt", HERMES_PALETTE.busy_interrupt()));
        }
        39 if line.contains("❯ ") => {
            return Line::styled(line.to_owned(), HERMES_PALETTE.composer());
        }
        _ => {}
    }

    styled_markers(line, &markers)
}

fn styled_markers(line: &str, markers: &[(&str, Style)]) -> Line<'static> {
    let mut matches = markers
        .iter()
        .filter_map(|(marker, style)| {
            line.find(marker).map(|start| (start, start + marker.len(), *style))
        })
        .collect::<Vec<_>>();
    matches.sort_by_key(|(start, _, _)| *start);

    if matches.is_empty() {
        return Line::raw(line.to_owned());
    }

    let mut spans = Vec::new();
    let mut cursor = 0;
    for (start, end, style) in matches {
        if start < cursor {
            continue;
        }
        if start > cursor {
            spans.push(Span::raw(line[cursor..start].to_owned()));
        }
        spans.push(Span::styled(line[start..end].to_owned(), style));
        cursor = end;
    }
    if cursor < line.len() {
        spans.push(Span::raw(line[cursor..].to_owned()));
    }
    Line::from(spans)
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
        Line::styled(
            " Hermes needs a model provider before the TUI can start a session.",
            HERMES_PALETTE.secondary(),
        ),
        Line::raw(""),
        Line::styled(" /model", HERMES_PALETTE.secondary()),
        Line::styled(" /setup", HERMES_PALETTE.secondary()),
        Line::raw(""),
        Line::styled(" Ctrl+C", HERMES_PALETTE.secondary()),
        Line::raw(""),
        Line::styled(format!(" ❯ {}", app.state().composer.text()), HERMES_PALETTE.composer()),
    ]);
    let panel = Paragraph::new(content).style(HERMES_PALETTE.secondary()).block(
        Block::default()
            .borders(Borders::ALL)
            .title_style(HERMES_PALETTE.brand())
            .title(" Setup Required "),
    );
    frame.render_widget(Clear, area);
    frame.render_widget(panel, area);
}

fn draw_setup_wizard_overlay(frame: &mut Frame<'_>, app: &App) {
    let Some(wizard) = app.state().setup_wizard.as_ref() else {
        return;
    };
    if wizard.is_platform_picker() {
        draw_setup_platform_picker_overlay(frame);
        return;
    }
    if wizard.is_terminal_backend_picker() {
        draw_setup_terminal_backend_picker_overlay(frame);
        return;
    }
    if wizard.is_model_name_prompt() {
        draw_setup_model_name_prompt_overlay(frame, wizard);
        return;
    }
    if wizard.is_provider_menu() {
        draw_setup_provider_menu_overlay(frame, wizard);
        return;
    }

    let area = centered_rect(frame.area(), 116, 20);
    let mut lines = vec![
        Line::styled(" Hermes Agent Setup Wizard", HERMES_PALETTE.brand()),
        Line::raw(""),
        Line::raw(" Let's configure your Hermes Agent installation."),
        Line::raw(" Press Ctrl+C at any time to exit."),
        Line::raw(""),
        Line::styled(" How would you like to set up Hermes?", HERMES_PALETTE.brand()),
    ];

    for (index, choice) in SETUP_WIZARD_CHOICES.iter().enumerate() {
        let cursor = if index == wizard.cursor() { "→" } else { " " };
        let selected = if index == wizard.selected() { "●" } else { "○" };
        let style = if index == wizard.cursor() {
            HERMES_PALETTE.ready()
        } else {
            HERMES_PALETTE.secondary()
        };
        lines.push(Line::styled(format!(" {cursor} ({selected}) {choice}"), style));
    }

    lines.push(Line::raw(""));
    if wizard.surface() == SetupWizardSurface::NumberedFallback {
        lines.extend([
            Line::styled(" Enter for default (1)  Ctrl+C to exit", HERMES_PALETTE.secondary()),
            Line::styled(" Select [1-3] (1):", HERMES_PALETTE.secondary()),
        ]);
    } else {
        lines.push(Line::styled(
            " ↑↓ navigate  ENTER/SPACE select  ESC cancel",
            HERMES_PALETTE.secondary(),
        ));
    }

    let panel = Paragraph::new(Text::from(lines))
        .block(Block::default().borders(Borders::ALL).title(" Setup wizard "));
    frame.render_widget(Clear, area);
    frame.render_widget(panel, area);
}

fn draw_setup_model_name_prompt_overlay(
    frame: &mut Frame<'_>,
    wizard: &hades_core::SetupWizardState,
) {
    let area = centered_rect(frame.area(), 116, 30);
    let mut lines = vec![
        Line::styled(" Hermes Agent Setup Wizard", HERMES_PALETTE.brand()),
        Line::raw(""),
        Line::styled(" Inference Provider", HERMES_PALETTE.brand()),
        Line::styled(
            format!(" Current model: {SETUP_PROVIDER_CURRENT_MODEL}"),
            HERMES_PALETTE.secondary(),
        ),
        Line::styled(
            format!(" Active provider: {SETUP_PROVIDER_ACTIVE_PROVIDER}"),
            HERMES_PALETTE.secondary(),
        ),
        Line::styled(" Select provider:", HERMES_PALETTE.brand()),
    ];

    for (index, row) in SETUP_PROVIDER_MENU_ROWS.iter().enumerate() {
        let cursor = if index == wizard.provider_cursor() { "→" } else { " " };
        let selected = if index == 0 { "●" } else { "○" };
        let style = if index == wizard.provider_cursor() {
            HERMES_PALETTE.ready()
        } else {
            HERMES_PALETTE.secondary()
        };
        lines.push(Line::styled(format!(" {cursor} ({selected}) {row}"), style));
    }

    lines.extend([
        Line::raw(""),
        Line::styled(format!(" {SETUP_PROVIDER_MODEL_NAME}"), HERMES_PALETTE.ready()),
        Line::styled(" Ctrl+C cancel", HERMES_PALETTE.secondary()),
    ]);

    let panel = Paragraph::new(Text::from(lines))
        .block(Block::default().borders(Borders::ALL).title(" Full setup "));
    frame.render_widget(Clear, area);
    frame.render_widget(panel, area);
}

fn draw_setup_terminal_backend_picker_overlay(frame: &mut Frame<'_>) {
    let area = centered_rect(frame.area(), 116, 30);
    let mut lines = vec![
        Line::styled(" Hermes Agent Setup Wizard", HERMES_PALETTE.brand()),
        Line::raw(""),
        Line::styled(" Inference Provider", HERMES_PALETTE.brand()),
        Line::styled(
            format!(" Current model: {SETUP_PROVIDER_CURRENT_MODEL}"),
            HERMES_PALETTE.secondary(),
        ),
        Line::styled(
            format!(" Active provider: {SETUP_PROVIDER_ACTIVE_PROVIDER}"),
            HERMES_PALETTE.secondary(),
        ),
        Line::raw(""),
        Line::styled(format!(" {SETUP_TERMINAL_BACKEND_TITLE}"), HERMES_PALETTE.brand()),
    ];

    lines.extend(
        SETUP_TERMINAL_BACKEND_ROWS
            .iter()
            .map(|row| Line::styled(format!(" {row}"), HERMES_PALETTE.secondary())),
    );
    lines.extend([
        Line::raw(""),
        Line::styled(format!(" {SETUP_TERMINAL_BACKEND_CONTROLS}"), HERMES_PALETTE.secondary()),
    ]);

    let panel = Paragraph::new(Text::from(lines))
        .block(Block::default().borders(Borders::ALL).title(" Full setup "));
    frame.render_widget(Clear, area);
    frame.render_widget(panel, area);
}

fn draw_setup_platform_picker_overlay(frame: &mut Frame<'_>) {
    let area = centered_rect(frame.area(), 116, 38);
    let mut lines = vec![
        Line::styled(" Hermes Agent Setup Wizard", HERMES_PALETTE.brand()),
        Line::raw(""),
        Line::styled(format!(" {SETUP_PLATFORM_PICKER_TITLE}"), HERMES_PALETTE.brand()),
        Line::styled(format!(" {SETUP_PLATFORM_PICKER_CONTROLS}"), HERMES_PALETTE.secondary()),
        Line::raw(""),
    ];
    for (index, row) in SETUP_PLATFORM_ROWS.iter().enumerate() {
        let cursor = if index == 0 { "→" } else { " " };
        lines.push(Line::styled(
            format!(" {cursor} [ ] {row}  (not configured)"),
            if index == 0 { HERMES_PALETTE.ready() } else { HERMES_PALETTE.secondary() },
        ));
    }

    let panel = Paragraph::new(Text::from(lines))
        .block(Block::default().borders(Borders::ALL).title(" Full setup "));
    frame.render_widget(Clear, area);
    frame.render_widget(panel, area);
}

fn draw_setup_provider_menu_overlay(frame: &mut Frame<'_>, wizard: &hades_core::SetupWizardState) {
    let area = centered_rect(frame.area(), 116, 30);
    let mut lines = vec![
        Line::styled(" Hermes Agent Setup Wizard", HERMES_PALETTE.brand()),
        Line::raw(""),
        Line::styled(" Configuration Location", HERMES_PALETTE.brand()),
        Line::styled(" Config file: <config-path>", HERMES_PALETTE.secondary()),
        Line::styled(" Secrets file: <secrets-path>", HERMES_PALETTE.secondary()),
        Line::styled(" Data folder: <data-path>", HERMES_PALETTE.secondary()),
        Line::styled(" Install dir: <install-dir>", HERMES_PALETTE.secondary()),
        Line::raw(""),
        Line::styled(
            " You can edit these files directly or use 'hermes config edit'",
            HERMES_PALETTE.secondary(),
        ),
        Line::raw(""),
        Line::styled(" Inference Provider", HERMES_PALETTE.brand()),
        Line::styled(" Choose how to connect to your main chat model.", HERMES_PALETTE.secondary()),
        Line::raw(""),
        Line::styled(
            format!(" Current model: {SETUP_PROVIDER_CURRENT_MODEL}"),
            HERMES_PALETTE.secondary(),
        ),
        Line::styled(
            format!(" Active provider: {SETUP_PROVIDER_ACTIVE_PROVIDER}"),
            HERMES_PALETTE.secondary(),
        ),
        Line::styled(" Select provider:", HERMES_PALETTE.brand()),
    ];

    for (index, row) in SETUP_PROVIDER_MENU_ROWS.iter().enumerate() {
        let cursor = if index == wizard.provider_cursor() { "→" } else { " " };
        let selected = if index == 0 { "●" } else { "○" };
        let style = if index == wizard.provider_cursor() {
            HERMES_PALETTE.ready()
        } else {
            HERMES_PALETTE.secondary()
        };
        lines.push(Line::styled(format!(" {cursor} ({selected}) {row}"), style));
    }

    lines.extend([
        Line::raw(""),
        Line::styled(" ↑↓ navigate  ENTER/SPACE select  Ctrl+C cancel", HERMES_PALETTE.secondary()),
    ]);

    let panel = Paragraph::new(Text::from(lines))
        .block(Block::default().borders(Borders::ALL).title(" Full setup "));
    frame.render_widget(Clear, area);
    frame.render_widget(panel, area);
}

fn draw_model_picker_overlay(frame: &mut Frame<'_>, app: &App) {
    let Some(picker) = app.state().model_picker.as_ref() else {
        return;
    };
    let area = centered_rect(frame.area(), 92, 18);
    let filter_line = if picker.filter().is_empty() {
        " type to filter · ↑/↓ select".to_owned()
    } else {
        format!(" filter: {}▎", picker.filter())
    };
    let mut lines = vec![Line::styled(
        match picker.stage() {
            ModelPickerStage::Provider => " Select provider (step 1/2)".to_owned(),
            ModelPickerStage::Model => " Select model (step 2/2)".to_owned(),
        },
        HERMES_PALETTE.brand(),
    )];

    match picker.stage() {
        ModelPickerStage::Provider => {
            lines.extend([
                Line::styled(
                    " Full model IDs on the next step · Enter to continue",
                    HERMES_PALETTE.secondary(),
                ),
                Line::styled(" Current: palette-model", HERMES_PALETTE.secondary()),
                Line::styled(filter_line, HERMES_PALETTE.secondary()),
                Line::raw(" "),
            ]);
            if picker.provider_matches() {
                lines.push(Line::styled(
                    format!(" ▸ 1. * {MODEL_PICKER_PROVIDER} · 1 models"),
                    HERMES_PALETTE.secondary(),
                ));
            } else {
                lines.push(Line::styled(" no providers match", HERMES_PALETTE.secondary()));
            }
            lines.extend([
                Line::raw(" "),
                Line::styled(" persist: session · ^g toggle", HERMES_PALETTE.secondary()),
                Line::styled(
                    " ↑/↓ select · Enter choose · ^d disconnect · Esc clear/back · q close",
                    HERMES_PALETTE.secondary(),
                ),
            ]);
        }
        ModelPickerStage::Model => {
            lines.extend([
                Line::styled(
                    format!(" {MODEL_PICKER_PROVIDER} · Esc back"),
                    HERMES_PALETTE.secondary(),
                ),
                Line::styled(filter_line, HERMES_PALETTE.secondary()),
                Line::raw(" "),
            ]);
            if picker.model_matches() {
                lines.push(Line::styled(
                    format!(" ▸ 1. * {MODEL_PICKER_MODEL}"),
                    HERMES_PALETTE.secondary(),
                ));
            } else {
                lines.push(Line::styled(" no models match filter", HERMES_PALETTE.secondary()));
            }
            lines.extend([
                Line::raw(" "),
                Line::styled(" persist: session · ^g toggle", HERMES_PALETTE.secondary()),
                Line::styled(
                    " ↑/↓ select · Enter switch · Esc clear/back · q close",
                    HERMES_PALETTE.secondary(),
                ),
            ]);
        }
    }

    let panel = Paragraph::new(Text::from(lines))
        .block(Block::default().borders(Borders::ALL).title(" Model picker "));
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
    use std::time::{Duration, Instant};

    use super::*;

    fn hermes_cell_style(app: &App, column: u16, row: u16) -> (Color, Color, Modifier) {
        let backend = TestBackend::new(HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        let mut terminal = Terminal::new(backend).expect("TestBackend construction is infallible");
        terminal.draw(|frame| draw(frame, app)).expect("rendering is infallible");
        let cell = terminal
            .backend()
            .buffer()
            .cell((column, row))
            .expect("landmark cell is inside the startup surface");
        (cell.fg, cell.bg, cell.modifier)
    }

    #[test]
    fn bootstrap_snapshot_has_stable_landmarks() {
        let rendered = snapshot(&App::new(), 80, 24);

        assert_eq!(rendered.lines().count(), 24);
        assert!(rendered.contains("HADES AGENT"));
        assert!(rendered.contains("transcript"));
        assert!(rendered.contains("Reference behavior pending capture."));
    }

    #[test]
    fn standalone_setup_surface_renders_the_reference_choice_landmarks() {
        let backend = TestBackend::new(HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        let mut terminal = Terminal::new(backend).expect("TestBackend construction is infallible");
        let wizard = SetupWizardState::default();
        terminal
            .draw(|frame| draw_standalone_setup(frame, &wizard))
            .expect("rendering is infallible");

        let rendered = (0..HERMES_STARTUP_HEIGHT)
            .map(|row| {
                (0..HERMES_STARTUP_WIDTH)
                    .map(|column| {
                        terminal
                            .backend()
                            .buffer()
                            .cell((column, row))
                            .expect("cell is inside the test surface")
                            .symbol()
                            .to_owned()
                    })
                    .collect::<String>()
            })
            .collect::<Vec<_>>()
            .join("\n");

        assert!(rendered.contains("How would you like to set up Hermes?"));
        assert!(rendered.contains("Quick Setup (Nous Portal)"));
        assert!(rendered.contains("Full setup"));
        assert!(rendered.contains("Blank Slate"));
        assert!(rendered.contains("ESC cancel"));
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
    fn hermes_startup_surface_renders_the_unconfigured_boundary() {
        let app = App::with_startup_state(StartupState::Unconfigured);
        let rendered = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);

        assert!(rendered.contains("glm-5.2 · Nous Research"));
        assert!(rendered.contains("starting agent…"));
        assert!(!rendered.contains("─ ready │"));
        assert!(!rendered.contains("<prompt-placeholder>"));
    }

    #[test]
    fn hermes_startup_surface_renders_an_unconfigured_draft_without_ready_state() {
        let mut app = App::with_startup_state(StartupState::Unconfigured);
        for character in "queued hello".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));

        let with_draft = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(with_draft.contains("❯ queued hello"));
        assert!(with_draft.contains("starting agent…"));
        assert!(!with_draft.contains("─ ready │"));

        app.handle(hades_core::InputEvent::Key(hades_core::Key::Ctrl('c')));
        let after_clear = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(!after_clear.contains("❯ queued hello"));
        assert!(after_clear.contains("starting agent…"));
    }

    #[test]
    fn hermes_startup_surface_renders_delayed_setup_required_help_route() {
        let start = Instant::now();
        let mut app = App::with_startup_state(StartupState::Unconfigured);
        for character in "/help".chars() {
            app.handle_at(hades_core::InputEvent::Key(hades_core::Key::Char(character)), start);
        }
        app.handle_at(hades_core::InputEvent::Key(hades_core::Key::Enter), start);

        let waiting = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(waiting.contains("❯ /help"));
        assert!(waiting.contains("starting agent…"));
        assert!(!waiting.contains("Setup Required"));

        app.handle_at(
            hades_core::InputEvent::Tick,
            start + Duration::from_millis(hades_core::HELP_SETUP_REQUIRED_DELAY_MS),
        );
        let setup_required = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(setup_required.contains("Setup Required"));
        assert!(setup_required.contains("/model"));
        assert!(setup_required.contains("/setup"));
        assert!(setup_required.contains("Ctrl+C"));

        app.handle(hades_core::InputEvent::Key(hades_core::Key::Ctrl('c')));
        assert_eq!(app.state().overlay, Some(Overlay::SetupRequired));
        assert_eq!(app.state().composer.text(), "");
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
    fn hermes_startup_surface_renders_streamed_assistant_response() {
        let mut app = App::new();
        for character in "hello".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        app.handle(hades_core::InputEvent::Provider(hades_core::ProviderEvent::Started));
        app.handle(hades_core::InputEvent::Provider(hades_core::ProviderEvent::TextDelta(
            "Synthetic ".to_owned(),
        )));
        app.handle(hades_core::InputEvent::Provider(hades_core::ProviderEvent::TextDelta(
            "response.".to_owned(),
        )));
        app.handle(hades_core::InputEvent::Provider(hades_core::ProviderEvent::Completed));

        let rendered = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(rendered.contains("Synthetic response."));
        assert!(!rendered.contains("musing…"));
        assert_eq!(app.state().turn, TurnState::Ready);
    }

    #[test]
    fn hermes_startup_surface_renders_provider_failure_and_cancellation() {
        let mut failed = App::new();
        failed.handle(hades_core::InputEvent::Key(hades_core::Key::Char('x')));
        failed.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        failed.handle(hades_core::InputEvent::Provider(hades_core::ProviderEvent::Failed(
            "loopback offline".to_owned(),
        )));
        assert!(
            snapshot(&failed, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT)
                .contains("Provider error: loopback offline")
        );

        let mut cancelled = App::new();
        cancelled.handle(hades_core::InputEvent::Key(hades_core::Key::Char('x')));
        cancelled.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        cancelled.handle(hades_core::InputEvent::Provider(hades_core::ProviderEvent::Cancelled));
        assert!(
            snapshot(&cancelled, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT)
                .contains("Provider response cancelled")
        );
    }

    #[test]
    fn hermes_startup_surface_uses_the_observed_palette_landmarks() {
        let app = App::new();
        let (brand_fg, brand_bg, brand_modifier) = hermes_cell_style(&app, 59, 11);
        assert_eq!(brand_fg, Color::Indexed(220));
        assert_eq!(brand_bg, Color::Reset);
        assert!(brand_modifier.contains(Modifier::BOLD));

        let (secondary_fg, _, _) = hermes_cell_style(&app, 3, 7);
        assert_eq!(secondary_fg, Color::Indexed(178));

        let (ready_fg, _, _) = hermes_cell_style(&app, 3, 38);
        assert_eq!(ready_fg, Color::Indexed(72));

        let mut composer = App::new();
        composer.handle(hades_core::InputEvent::Key(hades_core::Key::Char('x')));
        let (composer_fg, _, _) = hermes_cell_style(&composer, 3, 39);
        assert_eq!(composer_fg, Color::Indexed(230));

        composer.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        let (busy_fg, busy_bg, _) = hermes_cell_style(&composer, 3, 39);
        assert_eq!(busy_fg, Color::Rgb(255, 255, 255));
        assert_eq!(busy_bg, Color::Rgb(184, 134, 11));

        composer.handle(hades_core::InputEvent::Key(hades_core::Key::Ctrl('c')));
        let completion_column = HERMES_INTERRUPTED_FOOTER
            .chars()
            .position(|character| character == '✓')
            .expect("interrupted footer has a completion marker")
            as u16;
        let (completion_fg, _, _) = hermes_cell_style(&composer, completion_column, 38);
        assert_eq!(completion_fg, Color::Indexed(178));
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
    fn hermes_startup_surface_renders_model_picker_stages_and_back_controls() {
        let mut app = App::new();
        for character in "/model".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));

        let provider = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        for marker in [
            "Select provider (step 1/2)",
            "Current: palette-model",
            "type to filter",
            "persist: session",
            "Esc clear/back",
            "q close",
        ] {
            assert!(provider.contains(marker), "missing provider marker: {marker}");
        }

        for character in "palette".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }
        assert!(
            snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT).contains("filter: palette")
        );
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));

        let model = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        for marker in [
            "Select model (step 2/2)",
            "palette-loopback",
            "palette-model",
            "type to filter",
            "persist: session",
            "Esc clear/back",
            "q close",
        ] {
            assert!(model.contains(marker), "missing model marker: {marker}");
        }

        for character in "palette".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }
        assert!(
            snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT).contains("filter: palette")
        );
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Escape));
        let cleared = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(cleared.contains("Select model (step 2/2)"));
        assert!(cleared.contains("type to filter"));
        assert!(!cleared.contains("filter: palette"));

        app.handle(hades_core::InputEvent::Key(hades_core::Key::Escape));
        assert!(
            snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT)
                .contains("Select provider (step 1/2)")
        );
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Char('q')));
        let closed = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(!closed.contains("Select provider (step 1/2)"));
        assert!(closed.contains("─ ready │ mock model"));
    }

    #[test]
    fn hermes_startup_surface_renders_setup_wizard_navigation_and_fallback() {
        let mut app = App::new();
        for character in "/setup".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));

        let initial = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        for marker in [
            "Hermes Agent Setup Wizard",
            "Let's configure your Hermes Agent installation.",
            "Press Ctrl+C at any time to exit.",
            "How would you like to set up Hermes?",
            "Quick Setup (Nous Portal)",
            "Full setup",
            "Blank Slate",
            "●",
            "ESC cancel",
        ] {
            assert!(initial.contains(marker), "missing setup wizard marker: {marker}");
        }
        assert!(initial.contains("→ (●) Quick Setup"));

        app.handle(hades_core::InputEvent::Key(hades_core::Key::Down));
        let moved = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(moved.contains("→ (○) Full setup"));
        assert!(moved.contains("(●) Quick Setup"));

        app.handle(hades_core::InputEvent::Key(hades_core::Key::Escape));
        let fallback = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(fallback.contains("Enter for default (1)  Ctrl+C to exit"));
        assert!(fallback.contains("Select [1-3] (1):"));
        assert!(!fallback.contains("ESC cancel"));

        assert_eq!(
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Ctrl('c'))),
            hades_app::DispatchOutcome::Quit
        );
    }

    #[test]
    fn hermes_startup_surface_renders_bounded_full_setup_provider_menu() {
        let mut app = App::new();
        for character in "/setup".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Down));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));

        let provider = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        for marker in [
            "Configuration Location",
            "Config file: <config-path>",
            "Secrets file: <secrets-path>",
            "Data folder: <data-path>",
            "Install dir: <install-dir>",
            "You can edit these files directly or use 'hermes config edit'",
            "Inference Provider",
            "Choose how to connect to your main chat model.",
            "Current model: palette-model",
            "Active provider: palette-loopback",
            "Select provider:",
            "palette-loopback (loopback)",
            "palette-model",
            "Custom endpoint (enter URL manually)",
            "Remove a saved custom provider",
            "↑↓ navigate",
            "Ctrl+C cancel",
        ] {
            assert!(provider.contains(marker), "missing provider marker: {marker}");
        }
        assert!(provider.contains("→ (●) palette-loopback"));
        assert!(!provider.contains("musing…"));
        assert!(!provider.contains("API key"));

        app.handle(hades_core::InputEvent::Key(hades_core::Key::Down));
        let moved = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(moved.contains("→ (○) Custom endpoint"));
        assert!(moved.contains("(●) palette-loopback"));
        assert_eq!(
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Ctrl('c'))),
            hades_app::DispatchOutcome::Quit
        );
    }

    #[test]
    fn hermes_startup_surface_renders_display_only_model_name_prompt() {
        let mut app = App::new();
        for character in "/setup".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Down));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));

        let prompt = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        for marker in [
            "Inference Provider",
            "Current model: palette-model",
            "Active provider: palette-loopback",
            "palette-loopback (loopback)",
            "Model name [palette-model]:",
            "Ctrl+C cancel",
        ] {
            assert!(prompt.contains(marker), "missing model prompt marker: {marker}");
        }
        assert!(!prompt.contains("musing…"));
        assert!(!prompt.contains("API key"));
        assert_eq!(
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Ctrl('c'))),
            hades_app::DispatchOutcome::Quit
        );
    }

    #[test]
    fn hermes_startup_surface_renders_display_only_terminal_backend_picker() {
        let mut app = App::new();
        for character in "/setup".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Down));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));

        let picker = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        for marker in [
            "Select terminal backend:",
            "Local - run directly on this machine (default)",
            "Docker - isolated container with configurable resources",
            "Modal - serverless cloud sandbox",
            "SSH - run on a remote machine",
            "Daytona - persistent cloud development environment",
            "Vercel Sandbox - cloud microVM with snapshot filesystem persistence",
            "Singularity/Apptainer - HPC-friendly container",
            "Keep current (local)",
            "ENTER/SPACE select",
            "ESC cancel",
            "Current model: palette-model",
            "Active provider: palette-loopback",
        ] {
            assert!(picker.contains(marker), "missing terminal backend marker: {marker}");
        }
        assert!(!picker.contains("musing…"));
        assert!(!picker.contains("API key"));
        assert_eq!(
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Ctrl('c'))),
            hades_app::DispatchOutcome::Quit
        );
    }

    #[test]
    fn hermes_startup_surface_renders_bounded_platform_picker() {
        let mut app = App::new();
        for character in "/setup".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }
        for key in [
            hades_core::Key::Enter,
            hades_core::Key::Enter,
            hades_core::Key::Down,
            hades_core::Key::Enter,
            hades_core::Key::Enter,
            hades_core::Key::Enter,
            hades_core::Key::Enter,
        ] {
            app.handle(hades_core::InputEvent::Key(key));
        }

        let picker = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        for marker in [
            "Select platforms to configure:",
            "SPACE toggle",
            "ENTER confirm",
            "ESC cancel",
            "Mattermost",
            "Signal",
            "(not configured)",
        ] {
            assert!(picker.contains(marker), "missing platform picker marker: {marker}");
        }
        assert!(!picker.contains("musing…"));
        assert!(!picker.contains("API key"));
        assert_eq!(
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Ctrl('c'))),
            hades_app::DispatchOutcome::Quit
        );
    }

    #[test]
    fn hermes_startup_surface_renders_unknown_command_without_busy_state() {
        let mut app = App::new();
        for character in "/not-a-real-hermes-command".chars() {
            app.handle(hades_core::InputEvent::Key(hades_core::Key::Char(character)));
        }
        app.handle(hades_core::InputEvent::Key(hades_core::Key::Enter));

        let rendered = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        assert!(rendered.contains("Unknown command: /not-a-real-hermes-command"));
        assert!(rendered.contains("Type /help for available commands"));
        assert!(rendered.contains("─ ready │ mock model"));
        assert!(!rendered.contains("musing…"));
        assert!(!rendered.contains("❯ /not-a-real-hermes-command"));
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
    fn hermes_startup_surface_keeps_a_large_paste_visible_without_rendering_a_giant_line() {
        let mut app = App::new();
        app.handle(hades_core::InputEvent::Paste(
            format!("{}large-response-end", "l".repeat(256),),
        ));

        let rendered = snapshot(&app, HERMES_STARTUP_WIDTH, HERMES_STARTUP_HEIGHT);
        let line = rendered
            .lines()
            .find(|line| line.contains("large-response-end"))
            .expect("the bounded composer tail should remain visible");
        assert!(line.chars().count() <= usize::from(HERMES_STARTUP_WIDTH));
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
