#![forbid(unsafe_code)]

use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use hades_core::{
    CompletionState, Composer, EnterAction, InputEvent, Key, MAX_INPUT_HISTORY, Message,
    ModelPickerAction, ModelPickerStage, Notice, Overlay, ProviderEvent, SessionState,
    SetupWizardAction, SetupWizardState, TurnState,
};

#[derive(Clone, Debug)]
struct HistoryStore {
    path: PathBuf,
    entries: Vec<String>,
}

impl HistoryStore {
    fn open(path: PathBuf) -> Self {
        let entries = Self::load(&path);
        Self { path, entries }
    }

    fn load(path: &Path) -> Vec<String> {
        let Ok(contents) = fs::read_to_string(path) else {
            return Vec::new();
        };

        let mut entries = Vec::new();
        let mut current = Vec::new();
        for line in contents.split('\n') {
            if let Some(rest) = line.strip_prefix('+') {
                current.push(rest.to_owned());
            } else if !current.is_empty() {
                entries.push(current.join("\n"));
                current.clear();
            }
        }
        if !current.is_empty() {
            entries.push(current.join("\n"));
        }

        let start = entries.len().saturating_sub(MAX_INPUT_HISTORY);
        entries.into_iter().skip(start).collect()
    }

    fn append(&mut self, text: &str) {
        self.append_value(text.trim().to_owned());
    }

    fn append_value(&mut self, value: String) {
        if value.is_empty() || self.entries.last().is_some_and(|last| last == &value) {
            return;
        }

        self.entries.push(value.clone());
        if self.entries.len() > MAX_INPUT_HISTORY {
            let excess = self.entries.len() - MAX_INPUT_HISTORY;
            self.entries.drain(..excess);
        }

        let Some(parent) = self.path.parent() else {
            return;
        };
        if fs::create_dir_all(parent).is_err() {
            return;
        }

        let encoded =
            value.split('\n').map(|line| format!("+{line}")).collect::<Vec<_>>().join("\n");
        let record = format!("\n# {}\n{encoded}\n", history_timestamp());
        let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&self.path) else {
            return;
        };
        let _ = file.write_all(record.as_bytes());
    }
}

fn history_timestamp() -> String {
    let elapsed = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    let seconds = elapsed.as_secs();
    let days = (seconds / 86_400) as i64;
    let seconds_today = seconds % 86_400;
    let hour = seconds_today / 3_600;
    let minute = seconds_today / 60 % 60;
    let second = seconds_today % 60;
    let millis = elapsed.subsec_millis();
    let (year, month, day) = civil_date_from_days(days);

    format!("{year:04}-{month:02}-{day:02} {hour:02}:{minute:02}:{second:02}.{millis:03}")
}

fn civil_date_from_days(days_since_epoch: i64) -> (i64, u32, u32) {
    let adjusted = days_since_epoch + 719_468;
    let era = if adjusted >= 0 { adjusted } else { adjusted - 146_096 } / 146_097;
    let day_of_era = adjusted - era * 146_097;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let year = year_of_era + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_part = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * month_part + 2) / 5 + 1;
    let month = month_part + if month_part < 10 { 3 } else { -9 };
    let year = year + i64::from(month <= 2);

    (year, month as u32, day as u32)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DispatchOutcome {
    Continue,
    Submitted(String),
    Interrupted,
    EditorRequested(String),
    Quit,
}

#[derive(Clone, Debug)]
pub struct App {
    state: SessionState,
    history_store: Option<HistoryStore>,
}

impl App {
    pub fn new() -> Self {
        let mut state = SessionState::default();
        state.messages.push(Message::system(
            "Hades Agent bootstrap shell. Reference-backed behavior is not implemented yet.",
        ));
        Self { state, history_store: None }
    }

    pub fn with_history_path(path: impl Into<PathBuf>) -> Self {
        let history_store = HistoryStore::open(path.into());
        let mut app = Self::new();
        app.state.composer = Composer::with_history(history_store.entries.clone());
        app.history_store = Some(history_store);
        app
    }

    pub fn state(&self) -> &SessionState {
        &self.state
    }

    pub fn submit_editor_draft(&mut self, draft: String) -> DispatchOutcome {
        let content = draft.trim_end().to_owned();
        if content.is_empty() {
            return DispatchOutcome::Continue;
        }

        self.submit_content(content)
    }

    pub fn handle(&mut self, event: InputEvent) -> DispatchOutcome {
        match event {
            InputEvent::Resize { width, height } => {
                self.state.status = format!("Terminal size: {width}x{height}.");
                DispatchOutcome::Continue
            }
            InputEvent::Key(key) => self.handle_key(key),
            InputEvent::Paste(text) => self.handle_paste(text),
            InputEvent::Provider(event) => self.handle_provider_event(event),
        }
    }

    fn handle_provider_event(&mut self, event: ProviderEvent) -> DispatchOutcome {
        if self.state.turn != TurnState::Busy {
            return DispatchOutcome::Continue;
        }

        match event {
            ProviderEvent::Started => {
                self.state.status = "Provider started.".to_owned();
            }
            ProviderEvent::TextDelta(text) => {
                if text.is_empty() {
                    return DispatchOutcome::Continue;
                }

                if let Some(message) = self
                    .state
                    .messages
                    .last_mut()
                    .filter(|message| message.role == hades_core::Role::Assistant)
                {
                    message.content.push_str(&text);
                } else {
                    self.state.messages.push(Message::assistant(text));
                }
                self.state.status = "Receiving response.".to_owned();
            }
            ProviderEvent::Completed => {
                self.state.turn = TurnState::Ready;
                self.state.status = "Response complete.".to_owned();
            }
            ProviderEvent::Failed(message) => {
                self.state.turn = TurnState::Ready;
                self.state.status = if message.is_empty() {
                    "Provider error.".to_owned()
                } else {
                    format!("Provider error: {message}")
                };
                self.state.notice = Some(Notice::ProviderError { message });
            }
            ProviderEvent::Cancelled => {
                self.state.turn = TurnState::Ready;
                self.state.status = "Provider cancelled.".to_owned();
                self.state.notice = Some(Notice::ProviderCancelled);
            }
        }

        DispatchOutcome::Continue
    }

    fn handle_key(&mut self, key: Key) -> DispatchOutcome {
        if let Some(overlay) = self.state.overlay {
            return match overlay {
                Overlay::Sessions => match key {
                    Key::Escape => {
                        self.state.overlay = None;
                        self.state.status = "Sessions overlay closed.".to_owned();
                        DispatchOutcome::Continue
                    }
                    _ => DispatchOutcome::Continue,
                },
                Overlay::ModelPicker => self.handle_model_picker_key(key),
                Overlay::SetupWizard => self.handle_setup_wizard_key(key),
                Overlay::SetupRequired => match key {
                    Key::Ctrl('c') if !self.state.composer.text().is_empty() => {
                        self.state.composer.clear();
                        self.state.status = "Setup required.".to_owned();
                        DispatchOutcome::Continue
                    }
                    Key::Ctrl('c') => self.quit(),
                    _ => DispatchOutcome::Continue,
                },
            };
        }

        match key {
            Key::Ctrl('c') if self.state.turn == TurnState::Busy => self.interrupt(),
            Key::Ctrl('c') | Key::Ctrl('q') => self.quit(),
            Key::Ctrl('x') if self.state.turn == TurnState::Ready => {
                self.state.overlay = Some(Overlay::Sessions);
                self.state.status = "Sessions.".to_owned();
                DispatchOutcome::Continue
            }
            Key::Char('q') if self.state.composer.text().is_empty() => self.quit(),
            Key::Char(character) => {
                self.clear_notice();
                self.state.composer.insert(character);
                self.refresh_completion();
                self.state.status = "Editing input.".to_owned();
                DispatchOutcome::Continue
            }
            Key::Backspace => {
                self.clear_notice();
                self.state.composer.backspace();
                self.refresh_completion();
                DispatchOutcome::Continue
            }
            Key::Enter
                if matches!(
                    self.state.completion.first_item(),
                    Some("/model") | Some("/setup")
                ) =>
            {
                self.apply_completion();
                DispatchOutcome::Continue
            }
            Key::Enter => match self.state.composer.enter() {
                EnterAction::InsertedNewline => {
                    self.clear_notice();
                    self.refresh_completion();
                    self.state.status = "Editing input.".to_owned();
                    DispatchOutcome::Continue
                }
                EnterAction::Submit(content) => self.submit(content),
            },
            Key::ModifiedEnter if self.state.turn == TurnState::Ready => {
                self.clear_notice();
                self.state.composer.insert_newline();
                self.refresh_completion();
                self.state.status = "Editing input.".to_owned();
                DispatchOutcome::Continue
            }
            Key::ModifiedEnter => DispatchOutcome::Continue,
            Key::Escape => {
                self.clear_notice();
                self.state.composer.clear();
                self.clear_completion();
                self.state.status = "Input cleared.".to_owned();
                DispatchOutcome::Continue
            }
            Key::Tab if self.state.completion.is_visible() => {
                self.apply_completion();
                DispatchOutcome::Continue
            }
            Key::Tab => {
                self.state.surface = self.state.surface.next();
                self.state.status = format!("Surface: {}.", self.state.surface.label());
                DispatchOutcome::Continue
            }
            Key::Up => {
                self.clear_notice();
                self.state.composer.history_up();
                self.clear_completion();
                DispatchOutcome::Continue
            }
            Key::Down => {
                self.clear_notice();
                self.state.composer.history_down();
                self.clear_completion();
                DispatchOutcome::Continue
            }
            Key::Left => {
                self.clear_notice();
                self.state.composer.move_left();
                self.clear_completion();
                DispatchOutcome::Continue
            }
            Key::Right => {
                self.clear_notice();
                self.state.composer.move_right();
                self.clear_completion();
                DispatchOutcome::Continue
            }
            Key::Home => {
                self.clear_notice();
                self.state.composer.move_home();
                self.clear_completion();
                DispatchOutcome::Continue
            }
            Key::End => {
                self.clear_notice();
                self.state.composer.move_end();
                self.clear_completion();
                DispatchOutcome::Continue
            }
            Key::Ctrl('a') => {
                self.clear_notice();
                self.state.composer.move_home();
                self.clear_completion();
                DispatchOutcome::Continue
            }
            Key::Ctrl('k') => {
                self.clear_notice();
                self.state.composer.kill_to_end();
                self.clear_completion();
                DispatchOutcome::Continue
            }
            Key::Ctrl('g') if self.state.turn == TurnState::Ready => {
                let draft = self.state.composer.text().to_owned();
                if draft.trim().is_empty() {
                    return DispatchOutcome::Continue;
                }

                self.clear_completion();
                DispatchOutcome::EditorRequested(draft)
            }
            Key::Ctrl('v') if self.state.turn == TurnState::Ready => {
                self.clear_completion();
                self.state.status = "No image found in clipboard".to_owned();
                DispatchOutcome::Continue
            }
            Key::Ctrl(_) => DispatchOutcome::Continue,
        }
    }

    fn submit(&mut self, draft: String) -> DispatchOutcome {
        self.clear_completion();
        let content = draft.trim().to_owned();
        self.submit_content(content)
    }

    fn submit_content(&mut self, content: String) -> DispatchOutcome {
        if content.is_empty() {
            self.state.status = "Nothing to submit.".to_owned();
            return DispatchOutcome::Continue;
        }

        self.state.composer.record_submission(content.clone());
        if let Some(history_store) = &mut self.history_store {
            history_store.append(&content);
        }

        if content == "/help" {
            self.clear_notice();
            self.state.overlay = Some(Overlay::SetupRequired);
            self.state.status = "Setup required.".to_owned();
            return DispatchOutcome::Continue;
        }

        if content == "/model" {
            self.clear_notice();
            self.state.model_picker = Some(Default::default());
            self.state.overlay = Some(Overlay::ModelPicker);
            self.state.composer.clear();
            self.state.turn = TurnState::Ready;
            self.state.status = "Select provider (step 1/2).".to_owned();
            return DispatchOutcome::Continue;
        }

        if content == "/setup" {
            self.clear_notice();
            self.state.setup_wizard = Some(SetupWizardState::default());
            self.state.overlay = Some(Overlay::SetupWizard);
            self.state.composer.clear();
            self.state.turn = TurnState::Ready;
            self.state.status = "How would you like to set up Hermes?".to_owned();
            return DispatchOutcome::Continue;
        }

        if content.starts_with('/') {
            self.state.messages.push(Message::user(&content));
            self.state.messages.push(Message::system(format!(
                "Unknown command: {content}\nType /help for available commands"
            )));
            self.state.notice = Some(Notice::UnknownCommand { command: content.clone() });
            self.state.composer.clear();
            self.state.turn = TurnState::Ready;
            self.state.status = format!("Unknown command: {content}");
            return DispatchOutcome::Continue;
        }

        self.clear_notice();
        self.state.messages.push(Message::user(&content));
        self.state.composer.clear();
        self.state.turn = TurnState::Busy;
        self.state.status = "Busy; response adapter not connected.".to_owned();
        DispatchOutcome::Submitted(content)
    }

    fn interrupt(&mut self) -> DispatchOutcome {
        self.clear_notice();
        self.clear_completion();
        self.state.turn = TurnState::Ready;
        self.state.status = "Interrupted.".to_owned();
        DispatchOutcome::Interrupted
    }

    fn quit(&mut self) -> DispatchOutcome {
        self.state.should_quit = true;
        DispatchOutcome::Quit
    }

    fn handle_paste(&mut self, text: String) -> DispatchOutcome {
        if self.state.turn != TurnState::Ready || self.state.overlay.is_some() {
            return DispatchOutcome::Continue;
        }

        self.clear_notice();
        self.state.composer.insert_text(&text);
        self.clear_completion();
        self.state.status = "Pasted input.".to_owned();
        DispatchOutcome::Continue
    }

    fn handle_model_picker_key(&mut self, key: Key) -> DispatchOutcome {
        let Some(picker) = &mut self.state.model_picker else {
            self.state.overlay = None;
            return DispatchOutcome::Continue;
        };
        let action = picker.handle_key(key);
        let stage = picker.stage();
        let filter = picker.filter().to_owned();

        match action {
            ModelPickerAction::Closed => {
                self.state.overlay = None;
                self.state.model_picker = None;
                self.state.status = "Model picker closed.".to_owned();
            }
            ModelPickerAction::ClearedFilter => {
                self.state.status = format!("{} filter cleared.", stage.label());
            }
            ModelPickerAction::ReturnedToProvider => {
                self.state.status = "Select provider (step 1/2).".to_owned();
            }
            ModelPickerAction::Continue => {
                self.state.status = match (stage, filter.is_empty()) {
                    (ModelPickerStage::Provider, true) => "Select provider (step 1/2).".to_owned(),
                    (ModelPickerStage::Provider, false) => {
                        format!("Filtering providers: {filter}.")
                    }
                    (ModelPickerStage::Model, true) => "Select model (step 2/2).".to_owned(),
                    (ModelPickerStage::Model, false) => format!("Filtering models: {filter}."),
                };
            }
        }
        DispatchOutcome::Continue
    }

    fn handle_setup_wizard_key(&mut self, key: Key) -> DispatchOutcome {
        let Some(wizard) = &mut self.state.setup_wizard else {
            self.state.overlay = None;
            return DispatchOutcome::Continue;
        };
        let action = wizard.handle_key(key);

        match action {
            SetupWizardAction::Quit => {
                self.state.overlay = None;
                self.state.setup_wizard = None;
                self.quit()
            }
            SetupWizardAction::EnteredFallback => {
                self.state.status = "Enter for default (1)  Ctrl+C to exit".to_owned();
                DispatchOutcome::Continue
            }
            SetupWizardAction::EnteredProviderMenu => {
                self.state.status = "Select provider:".to_owned();
                DispatchOutcome::Continue
            }
            SetupWizardAction::EnteredModelNamePrompt => {
                self.state.status = "Model name [palette-model]:".to_owned();
                DispatchOutcome::Continue
            }
            SetupWizardAction::EnteredTerminalBackendPicker => {
                self.state.status = "Select terminal backend:".to_owned();
                DispatchOutcome::Continue
            }
            SetupWizardAction::EnteredPlatformPicker => {
                self.state.status = "Select platforms to configure:".to_owned();
                DispatchOutcome::Continue
            }
            SetupWizardAction::Moved => {
                self.state.status = if wizard.is_provider_menu() {
                    "Provider menu navigation.".to_owned()
                } else {
                    "Setup wizard navigation.".to_owned()
                };
                DispatchOutcome::Continue
            }
            SetupWizardAction::Continue => DispatchOutcome::Continue,
        }
    }

    fn refresh_completion(&mut self) {
        if self.state.turn != TurnState::Ready {
            self.clear_completion();
            return;
        }

        let draft = self.state.composer.text().to_owned();
        self.state.completion = CompletionState::for_draft(&draft);
    }

    fn clear_completion(&mut self) {
        self.state.completion = CompletionState::default();
    }

    fn clear_notice(&mut self) {
        self.state.notice = None;
    }

    fn apply_completion(&mut self) {
        let Some(item) = self.state.completion.first_item().map(str::to_owned) else {
            return;
        };

        self.state.composer.replace(item);
        self.clear_completion();
        self.state.status = "Completion applied.".to_owned();
    }
}

impl Default for App {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use std::{
        env, fs,
        time::{SystemTime, UNIX_EPOCH},
    };

    use super::*;
    use hades_core::{InputEvent, Key, Surface};

    fn test_history_path(label: &str) -> PathBuf {
        let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        env::temp_dir().join(format!("hades-history-{label}-{}-{stamp}.log", std::process::id()))
    }

    fn remove_test_history(path: &Path) {
        let _ = fs::remove_file(path);
    }

    #[test]
    fn input_submission_is_deterministic_and_recorded() {
        let mut app = App::new();
        for character in "hello".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }

        assert_eq!(
            app.handle(InputEvent::Key(Key::Enter)),
            DispatchOutcome::Submitted("hello".to_owned())
        );
        assert_eq!(app.state().composer.text(), "");
        assert_eq!(app.state().turn, TurnState::Busy);
        assert_eq!(app.state().status, "Busy; response adapter not connected.");
        assert_eq!(app.state().messages.last().unwrap().content, "hello");
    }

    #[test]
    fn provider_deltas_accumulate_into_an_assistant_message_until_completion() {
        let mut app = App::new();
        for character in "hello".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        assert!(matches!(
            app.handle(InputEvent::Key(Key::Enter)),
            DispatchOutcome::Submitted(content) if content == "hello"
        ));

        app.handle(InputEvent::Provider(ProviderEvent::Started));
        app.handle(InputEvent::Provider(ProviderEvent::TextDelta("Synthetic ".to_owned())));
        app.handle(InputEvent::Provider(ProviderEvent::TextDelta("response.".to_owned())));
        assert_eq!(app.state().turn, TurnState::Busy);
        assert_eq!(app.state().status, "Receiving response.");
        assert_eq!(app.state().messages.last().unwrap().role, hades_core::Role::Assistant);
        assert_eq!(app.state().messages.last().unwrap().content, "Synthetic response.");

        app.handle(InputEvent::Provider(ProviderEvent::Completed));
        assert_eq!(app.state().turn, TurnState::Ready);
        assert_eq!(app.state().status, "Response complete.");
    }

    #[test]
    fn provider_failure_and_cancellation_are_terminal_and_ignored_when_ready() {
        let mut app = App::new();
        app.handle(InputEvent::Provider(ProviderEvent::Failed("offline".to_owned())));
        assert_eq!(app.state().status, "Reference behavior pending capture.");
        assert_eq!(app.state().notice, None);

        for character in "hello".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        app.handle(InputEvent::Key(Key::Enter));
        app.handle(InputEvent::Provider(ProviderEvent::Failed("offline".to_owned())));
        assert_eq!(app.state().turn, TurnState::Ready);
        assert_eq!(app.state().status, "Provider error: offline");
        assert_eq!(
            app.state().notice,
            Some(Notice::ProviderError { message: "offline".to_owned() })
        );

        for character in "again".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        app.handle(InputEvent::Key(Key::Enter));
        app.handle(InputEvent::Provider(ProviderEvent::Cancelled));
        assert_eq!(app.state().turn, TurnState::Ready);
        assert_eq!(app.state().status, "Provider cancelled.");
        assert_eq!(app.state().notice, Some(Notice::ProviderCancelled));
    }

    #[test]
    fn ctrl_c_interrupts_busy_turn_before_quitting() {
        let mut app = App::new();
        for character in "hello".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        assert_eq!(
            app.handle(InputEvent::Key(Key::Enter)),
            DispatchOutcome::Submitted("hello".to_owned())
        );

        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('c'))), DispatchOutcome::Interrupted);
        assert_eq!(app.state().turn, TurnState::Ready);
        assert_eq!(app.state().status, "Interrupted.");
        assert!(!app.state().should_quit);
        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('c'))), DispatchOutcome::Quit);
        assert!(app.state().should_quit);
    }

    #[test]
    fn tab_cycles_surfaces_and_control_c_quits() {
        let mut app = App::new();
        app.handle(InputEvent::Key(Key::Tab));
        assert_eq!(app.state().surface, Surface::Conversation);
        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('c'))), DispatchOutcome::Quit);
        assert!(app.state().should_quit);
    }

    #[test]
    fn slash_completion_consumes_tab_before_surface_navigation() {
        let mut app = App::new();
        for character in "/he".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }

        assert_eq!(app.state().completion.items().len(), 3);
        assert_eq!(app.state().surface, Surface::Home);
        assert_eq!(app.handle(InputEvent::Key(Key::Tab)), DispatchOutcome::Continue);
        assert_eq!(app.state().composer.text(), "/help");
        assert!(!app.state().completion.is_visible());
        assert_eq!(app.state().surface, Surface::Home);
    }

    #[test]
    fn ctrl_x_opens_sessions_overlay_and_escape_restores_composer() {
        let mut app = App::new();

        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('x'))), DispatchOutcome::Continue);
        assert_eq!(app.state().overlay, Some(Overlay::Sessions));

        app.handle(InputEvent::Key(Key::Char('h')));
        assert_eq!(app.state().composer.text(), "");

        assert_eq!(app.handle(InputEvent::Key(Key::Escape)), DispatchOutcome::Continue);
        assert_eq!(app.state().overlay, None);
        app.handle(InputEvent::Key(Key::Char('h')));
        assert_eq!(app.state().composer.text(), "h");
    }

    #[test]
    fn help_opens_setup_overlay_and_requires_two_ctrl_c_presses_to_exit() {
        let mut app = App::new();
        for character in "/help".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }

        assert_eq!(app.handle(InputEvent::Key(Key::Enter)), DispatchOutcome::Continue);
        assert_eq!(app.state().overlay, Some(Overlay::SetupRequired));
        assert_eq!(app.state().composer.text(), "/help");

        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('c'))), DispatchOutcome::Continue);
        assert_eq!(app.state().overlay, Some(Overlay::SetupRequired));
        assert_eq!(app.state().composer.text(), "");
        assert!(!app.state().should_quit);

        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('c'))), DispatchOutcome::Quit);
        assert!(app.state().should_quit);
    }

    #[test]
    fn unknown_slash_command_stays_ready_and_reports_the_reference_error() {
        let mut app = App::new();
        for character in "/not-a-real-hermes-command".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }

        assert_eq!(app.handle(InputEvent::Key(Key::Enter)), DispatchOutcome::Continue);
        assert_eq!(app.state().turn, TurnState::Ready);
        assert_eq!(app.state().overlay, None);
        assert_eq!(app.state().composer.text(), "");
        assert_eq!(
            app.state().notice,
            Some(Notice::UnknownCommand { command: "/not-a-real-hermes-command".to_owned() })
        );
        assert_eq!(
            app.state().messages.last().map(|message| message.content.as_str()),
            Some("Unknown command: /not-a-real-hermes-command\nType /help for available commands")
        );
        assert_eq!(app.state().status, "Unknown command: /not-a-real-hermes-command");
    }

    #[test]
    fn model_picker_follows_the_two_step_entry_and_escape_contract() {
        let mut app = App::new();
        for character in "/model".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        assert_eq!(app.state().completion.items(), &vec!["/model".to_owned()]);

        assert_eq!(app.handle(InputEvent::Key(Key::Enter)), DispatchOutcome::Continue);
        assert_eq!(app.state().overlay, None);
        assert_eq!(app.state().composer.text(), "/model");

        assert_eq!(app.handle(InputEvent::Key(Key::Enter)), DispatchOutcome::Continue);
        assert_eq!(app.state().overlay, Some(Overlay::ModelPicker));
        assert_eq!(app.state().model_picker.as_ref().unwrap().stage(), ModelPickerStage::Provider);
        assert_eq!(app.state().turn, TurnState::Ready);
        assert_eq!(app.state().composer.text(), "");

        for character in "palette".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        assert_eq!(app.state().model_picker.as_ref().unwrap().filter(), "palette");
        app.handle(InputEvent::Key(Key::Enter));
        assert_eq!(app.state().model_picker.as_ref().unwrap().stage(), ModelPickerStage::Model);
        assert_eq!(app.state().model_picker.as_ref().unwrap().filter(), "");

        for character in "palette".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        app.handle(InputEvent::Key(Key::Escape));
        assert_eq!(app.state().model_picker.as_ref().unwrap().stage(), ModelPickerStage::Model);
        assert_eq!(app.state().model_picker.as_ref().unwrap().filter(), "");
        app.handle(InputEvent::Key(Key::Escape));
        assert_eq!(app.state().model_picker.as_ref().unwrap().stage(), ModelPickerStage::Provider);
        app.handle(InputEvent::Key(Key::Char('q')));
        assert_eq!(app.state().overlay, None);
        assert!(app.state().model_picker.is_none());
        assert!(!app.state().should_quit);
        assert_eq!(app.state().turn, TurnState::Ready);
    }

    #[test]
    fn setup_wizard_follows_the_two_step_entry_and_escape_fallback_contract() {
        let mut app = App::new();
        for character in "/setup".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        assert_eq!(app.state().completion.items(), &vec!["/setup".to_owned()]);

        assert_eq!(app.handle(InputEvent::Key(Key::Enter)), DispatchOutcome::Continue);
        assert_eq!(app.state().overlay, None);
        assert_eq!(app.state().composer.text(), "/setup");

        assert_eq!(app.handle(InputEvent::Key(Key::Enter)), DispatchOutcome::Continue);
        assert_eq!(app.state().overlay, Some(Overlay::SetupWizard));
        assert_eq!(app.state().turn, TurnState::Ready);
        assert_eq!(app.state().composer.text(), "");
        let wizard = app.state().setup_wizard.as_ref().unwrap();
        assert_eq!(wizard.cursor(), 0);
        assert_eq!(wizard.selected(), 0);
        assert!(!wizard.is_fallback());

        app.handle(InputEvent::Key(Key::Down));
        let wizard = app.state().setup_wizard.as_ref().unwrap();
        assert_eq!(wizard.cursor(), 1);
        assert_eq!(wizard.selected(), 0);

        assert_eq!(app.handle(InputEvent::Key(Key::Escape)), DispatchOutcome::Continue);
        assert!(app.state().setup_wizard.as_ref().unwrap().is_fallback());
        assert_eq!(app.state().status, "Enter for default (1)  Ctrl+C to exit");

        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('c'))), DispatchOutcome::Quit);
        assert!(app.state().should_quit);
        assert_eq!(app.state().overlay, None);
        assert!(app.state().setup_wizard.is_none());
    }

    #[test]
    fn full_setup_enters_bounded_provider_menu_without_submitting_a_provider() {
        let mut app = App::new();
        for character in "/setup".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        app.handle(InputEvent::Key(Key::Enter));
        app.handle(InputEvent::Key(Key::Enter));
        app.handle(InputEvent::Key(Key::Down));

        assert_eq!(app.handle(InputEvent::Key(Key::Enter)), DispatchOutcome::Continue);
        let wizard = app.state().setup_wizard.as_ref().unwrap();
        assert!(wizard.is_provider_menu());
        assert_eq!(wizard.provider_cursor(), 0);
        assert_eq!(app.state().status, "Select provider:");
        assert_eq!(wizard.selected(), 0);

        app.handle(InputEvent::Key(Key::Down));
        assert_eq!(app.state().setup_wizard.as_ref().unwrap().provider_cursor(), 1);
        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('c'))), DispatchOutcome::Quit);
        assert!(app.state().setup_wizard.is_none());
    }

    #[test]
    fn full_setup_active_provider_reaches_display_only_model_name_prompt() {
        let mut app = App::new();
        for character in "/setup".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        app.handle(InputEvent::Key(Key::Enter));
        app.handle(InputEvent::Key(Key::Enter));
        app.handle(InputEvent::Key(Key::Down));
        app.handle(InputEvent::Key(Key::Enter));

        assert_eq!(app.handle(InputEvent::Key(Key::Enter)), DispatchOutcome::Continue);
        let wizard = app.state().setup_wizard.as_ref().unwrap();
        assert!(wizard.is_model_name_prompt());
        assert_eq!(wizard.provider_cursor(), 0);
        assert_eq!(app.state().status, "Model name [palette-model]:");
        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('c'))), DispatchOutcome::Quit);
        assert!(app.state().setup_wizard.is_none());
    }

    #[test]
    fn full_setup_model_default_reaches_display_only_terminal_backend_picker() {
        let mut app = App::new();
        for character in "/setup".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        app.handle(InputEvent::Key(Key::Enter));
        app.handle(InputEvent::Key(Key::Enter));
        app.handle(InputEvent::Key(Key::Down));
        app.handle(InputEvent::Key(Key::Enter));
        app.handle(InputEvent::Key(Key::Enter));

        assert_eq!(app.handle(InputEvent::Key(Key::Enter)), DispatchOutcome::Continue);
        let wizard = app.state().setup_wizard.as_ref().unwrap();
        assert!(wizard.is_terminal_backend_picker());
        assert_eq!(app.state().status, "Select terminal backend:");
        assert_eq!(app.handle(InputEvent::Key(Key::Char(' '))), DispatchOutcome::Continue);
        assert!(app.state().setup_wizard.as_ref().unwrap().is_platform_picker());
        assert_eq!(app.state().status, "Select platforms to configure:");
        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('c'))), DispatchOutcome::Quit);
        assert!(app.state().setup_wizard.is_none());
    }

    #[test]
    fn composer_replays_observed_editing_sequence() {
        let mut app = App::new();
        for character in "abc".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        app.handle(InputEvent::Key(Key::Left));
        app.handle(InputEvent::Key(Key::Char('X')));
        assert_eq!(app.state().composer.text(), "abXc");

        app.handle(InputEvent::Key(Key::Backspace));
        app.handle(InputEvent::Key(Key::Home));
        app.handle(InputEvent::Key(Key::Char('z')));
        app.handle(InputEvent::Key(Key::End));
        app.handle(InputEvent::Key(Key::Char('!')));
        assert_eq!(app.state().composer.text(), "zabc!");

        app.handle(InputEvent::Key(Key::Ctrl('a')));
        app.handle(InputEvent::Key(Key::Ctrl('k')));
        assert_eq!(app.state().composer.text(), "");
    }

    #[test]
    fn interrupted_submission_is_recallable_and_down_restores_empty_draft() {
        let mut app = App::new();
        for character in "alpha".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        assert_eq!(
            app.handle(InputEvent::Key(Key::Enter)),
            DispatchOutcome::Submitted("alpha".to_owned())
        );
        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('c'))), DispatchOutcome::Interrupted);

        app.handle(InputEvent::Key(Key::Up));
        assert_eq!(app.state().composer.text(), "alpha");
        app.handle(InputEvent::Key(Key::Down));
        assert_eq!(app.state().composer.text(), "");
    }

    #[test]
    fn backslash_enter_inserts_multiline_draft_without_submitting() {
        let mut app = App::new();
        for character in "line-one\\".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }

        assert_eq!(app.handle(InputEvent::Key(Key::Enter)), DispatchOutcome::Continue);
        app.handle(InputEvent::Key(Key::Char('x')));
        assert_eq!(app.state().composer.text(), "line-one\nx");
        assert_eq!(app.state().turn, TurnState::Ready);
        assert!(app.state().messages.iter().all(|message| message.content != "line-one\nx"));
    }

    #[test]
    fn modified_enter_inserts_multiline_draft_without_submitting() {
        let mut app = App::new();
        app.handle(InputEvent::Key(Key::Char('s')));
        app.handle(InputEvent::Key(Key::Char('h')));
        app.handle(InputEvent::Key(Key::Char('i')));
        app.handle(InputEvent::Key(Key::Char('f')));
        app.handle(InputEvent::Key(Key::Char('t')));

        assert_eq!(app.handle(InputEvent::Key(Key::ModifiedEnter)), DispatchOutcome::Continue);
        app.handle(InputEvent::Key(Key::Char('a')));
        app.handle(InputEvent::Key(Key::Char('f')));
        app.handle(InputEvent::Key(Key::Char('t')));
        app.handle(InputEvent::Key(Key::Char('e')));
        app.handle(InputEvent::Key(Key::Char('r')));

        assert_eq!(app.state().composer.text(), "shift\nafter");
        assert_eq!(app.state().turn, TurnState::Ready);
        assert_eq!(app.state().status, "Editing input.");
        assert!(app.state().messages.iter().all(|message| message.content != "shift\nafter"));
    }

    #[test]
    fn bracketed_paste_preserves_newlines_without_submitting() {
        let mut app = App::new();

        assert_eq!(
            app.handle(InputEvent::Paste("paste-one\npaste-two".to_owned())),
            DispatchOutcome::Continue
        );
        assert_eq!(app.state().composer.text(), "paste-one\npaste-two");
        assert_eq!(app.state().turn, TurnState::Ready);
        assert!(
            app.state()
                .messages
                .iter()
                .all(|message| { message.content != "paste-one\npaste-two" })
        );
    }

    #[test]
    fn ctrl_g_requests_editor_for_the_unchanged_draft() {
        let mut app = App::new();
        for character in "editor-probe".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }

        assert_eq!(
            app.handle(InputEvent::Key(Key::Ctrl('g'))),
            DispatchOutcome::EditorRequested("editor-probe".to_owned())
        );
        assert_eq!(app.state().composer.text(), "editor-probe");
        assert_eq!(app.state().turn, TurnState::Ready);

        assert_eq!(
            app.submit_editor_draft("editor-probe".to_owned()),
            DispatchOutcome::Submitted("editor-probe".to_owned())
        );
        assert_eq!(app.state().turn, TurnState::Busy);
    }

    #[test]
    fn editor_submission_preserves_trimmed_multiline_content_and_history_bytes() {
        let path = test_history_path("editor-outcome");
        let mut app = App::with_history_path(path.clone());

        assert_eq!(
            app.submit_editor_draft("  edge-one  \nedge-two\n".to_owned()),
            DispatchOutcome::Submitted("  edge-one  \nedge-two".to_owned())
        );
        assert_eq!(app.state().composer.text(), "");
        assert_eq!(app.state().messages.last().unwrap().content, "  edge-one  \nedge-two");

        let history = fs::read_to_string(&path).unwrap();
        assert!(history.contains("+edge-one  \n+edge-two\n"));
        remove_test_history(&path);
    }

    #[test]
    fn empty_editor_output_preserves_the_existing_draft() {
        let mut app = App::new();
        for character in "empty-probe".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }
        let status = app.state().status.clone();

        assert_eq!(app.submit_editor_draft("\n  \n".to_owned()), DispatchOutcome::Continue);
        assert_eq!(app.state().composer.text(), "empty-probe");
        assert_eq!(app.state().status, status);
        assert!(app.state().messages.iter().all(|message| message.content != "empty-probe"));
    }

    #[test]
    fn ctrl_v_reports_empty_clipboard_without_changing_the_draft() {
        let mut app = App::new();
        for character in "clipboard-probe".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }

        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('v'))), DispatchOutcome::Continue);
        assert_eq!(app.state().composer.text(), "clipboard-probe");
        assert_eq!(app.state().status, "No image found in clipboard");
        assert_eq!(app.state().turn, TurnState::Ready);
    }

    #[test]
    fn history_store_round_trips_multiline_and_suppresses_consecutive_duplicates() {
        let path = test_history_path("round-trip");
        let mut store = HistoryStore::open(path.clone());

        store.append("  alpha  ");
        let first_write = fs::read(&path).unwrap();
        store.append("alpha");
        assert_eq!(fs::read(&path).unwrap(), first_write);

        store.append("one\ntwo");
        let contents = fs::read_to_string(&path).unwrap();
        assert!(contents.contains("+alpha\n"));
        assert!(contents.contains("+one\n+two\n"));
        assert_eq!(HistoryStore::load(&path), vec!["alpha", "one\ntwo"]);

        remove_test_history(&path);
    }

    #[test]
    fn history_store_loads_only_the_newest_thousand_entries() {
        let path = test_history_path("cap");
        let contents =
            (1..=1001).map(|index| format!("\n# timestamp\n+cap-{index:04}\n")).collect::<String>();
        fs::write(&path, contents).unwrap();

        let entries = HistoryStore::load(&path);
        assert_eq!(entries.len(), MAX_INPUT_HISTORY);
        assert_eq!(entries.first().map(String::as_str), Some("cap-0002"));
        assert_eq!(entries.last().map(String::as_str), Some("cap-1001"));

        remove_test_history(&path);
    }

    #[test]
    fn app_history_survives_a_new_process_boundary() {
        let path = test_history_path("process-boundary");
        let mut first = App::with_history_path(path.clone());
        for character in "restart-alpha".chars() {
            first.handle(InputEvent::Key(Key::Char(character)));
        }
        assert_eq!(
            first.handle(InputEvent::Key(Key::Enter)),
            DispatchOutcome::Submitted("restart-alpha".to_owned())
        );
        assert_eq!(first.handle(InputEvent::Key(Key::Ctrl('c'))), DispatchOutcome::Interrupted);

        let mut second = App::with_history_path(path.clone());
        second.handle(InputEvent::Key(Key::Up));
        assert_eq!(second.state().composer.text(), "restart-alpha");
        second.handle(InputEvent::Key(Key::Down));
        assert_eq!(second.state().composer.text(), "");

        remove_test_history(&path);
    }
}
