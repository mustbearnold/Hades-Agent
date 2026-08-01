#![forbid(unsafe_code)]

use serde::{Deserialize, Serialize};

pub const PRODUCT_NAME: &str = "Hades Agent";
pub const MAX_INPUT_HISTORY: usize = 1000;

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub enum Surface {
    #[default]
    Home,
    Conversation,
    Settings,
}

impl Surface {
    pub const ALL: [Self; 3] = [Self::Home, Self::Conversation, Self::Settings];

    pub const fn label(self) -> &'static str {
        match self {
            Self::Home => "Home",
            Self::Conversation => "Conversation",
            Self::Settings => "Settings",
        }
    }

    pub const fn next(self) -> Self {
        match self {
            Self::Home => Self::Conversation,
            Self::Conversation => Self::Settings,
            Self::Settings => Self::Home,
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum Role {
    System,
    User,
    Assistant,
}

impl Role {
    pub const fn label(self) -> &'static str {
        match self {
            Self::System => "system",
            Self::User => "you",
            Self::Assistant => "hades",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub enum TurnState {
    #[default]
    Ready,
    Busy,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum Overlay {
    Sessions,
    ModelPicker,
    SetupWizard,
    SetupRequired,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub enum ModelPickerStage {
    #[default]
    Provider,
    Model,
}

impl ModelPickerStage {
    pub const fn label(self) -> &'static str {
        match self {
            Self::Provider => "Provider",
            Self::Model => "Model",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ModelPickerAction {
    Continue,
    ClearedFilter,
    ReturnedToProvider,
    Closed,
}

pub const MODEL_PICKER_PROVIDER: &str = "palette-loopback";
pub const MODEL_PICKER_MODEL: &str = "palette-model";

pub const SETUP_WIZARD_CHOICES: [&str; 3] = [
    "Quick Setup (Nous Portal) — free OAuth login, no API keys, model + tools (recommended)",
    "Full setup — configure every provider, tool & option yourself (bring your own keys)",
    "Blank Slate — everything off except the bare minimum; opt in to each capability",
];

pub const SETUP_PROVIDER_CURRENT_MODEL: &str = "palette-model";
pub const SETUP_PROVIDER_ACTIVE_PROVIDER: &str = "palette-loopback";
pub const SETUP_PROVIDER_MODEL_NAME: &str = "Model name [palette-model]:";
pub const SETUP_PROVIDER_MENU_ROWS: [&str; 5] = [
    "palette-loopback (loopback) — palette-model  ← currently active",
    "Custom endpoint (enter URL manually)",
    "Remove a saved custom provider",
    "Configure auxiliary models...",
    "Leave unchanged",
];

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub enum SetupWizardSurface {
    #[default]
    Choices,
    NumberedFallback,
    FullSetupProviderMenu,
    ModelNamePrompt,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum SetupWizardAction {
    Continue,
    Moved,
    EnteredFallback,
    EnteredProviderMenu,
    EnteredModelNamePrompt,
    Quit,
}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct SetupWizardState {
    surface: SetupWizardSurface,
    cursor: usize,
    selected: usize,
    provider_cursor: usize,
}

impl SetupWizardState {
    pub fn surface(&self) -> SetupWizardSurface {
        self.surface
    }

    pub fn cursor(&self) -> usize {
        self.cursor
    }

    pub fn selected(&self) -> usize {
        self.selected
    }

    pub fn cursor_label(&self) -> &'static str {
        SETUP_WIZARD_CHOICES[self.cursor]
    }

    pub fn selected_label(&self) -> &'static str {
        SETUP_WIZARD_CHOICES[self.selected]
    }

    pub fn is_fallback(&self) -> bool {
        self.surface == SetupWizardSurface::NumberedFallback
    }

    pub fn is_provider_menu(&self) -> bool {
        self.surface == SetupWizardSurface::FullSetupProviderMenu
    }

    pub fn is_model_name_prompt(&self) -> bool {
        self.surface == SetupWizardSurface::ModelNamePrompt
    }

    pub fn provider_cursor(&self) -> usize {
        self.provider_cursor
    }

    pub fn provider_cursor_label(&self) -> &'static str {
        SETUP_PROVIDER_MENU_ROWS[self.provider_cursor]
    }

    pub fn handle_key(&mut self, key: Key) -> SetupWizardAction {
        match self.surface {
            SetupWizardSurface::Choices => match key {
                Key::Enter | Key::Char(' ') if self.cursor == 1 => {
                    self.surface = SetupWizardSurface::FullSetupProviderMenu;
                    self.provider_cursor = 0;
                    SetupWizardAction::EnteredProviderMenu
                }
                Key::Down => {
                    self.cursor = (self.cursor + 1).min(SETUP_WIZARD_CHOICES.len() - 1);
                    SetupWizardAction::Moved
                }
                Key::Up => {
                    self.cursor = self.cursor.saturating_sub(1);
                    SetupWizardAction::Moved
                }
                Key::Escape => {
                    self.surface = SetupWizardSurface::NumberedFallback;
                    SetupWizardAction::EnteredFallback
                }
                Key::Ctrl('c') => SetupWizardAction::Quit,
                _ => SetupWizardAction::Continue,
            },
            SetupWizardSurface::NumberedFallback => match key {
                Key::Ctrl('c') => SetupWizardAction::Quit,
                _ => SetupWizardAction::Continue,
            },
            SetupWizardSurface::FullSetupProviderMenu => match key {
                Key::Enter | Key::Char(' ') if self.provider_cursor == 0 => {
                    self.surface = SetupWizardSurface::ModelNamePrompt;
                    SetupWizardAction::EnteredModelNamePrompt
                }
                Key::Down => {
                    self.provider_cursor =
                        (self.provider_cursor + 1).min(SETUP_PROVIDER_MENU_ROWS.len() - 1);
                    SetupWizardAction::Moved
                }
                Key::Up => {
                    self.provider_cursor = self.provider_cursor.saturating_sub(1);
                    SetupWizardAction::Moved
                }
                Key::Ctrl('c') => SetupWizardAction::Quit,
                _ => SetupWizardAction::Continue,
            },
            SetupWizardSurface::ModelNamePrompt => match key {
                Key::Ctrl('c') => SetupWizardAction::Quit,
                _ => SetupWizardAction::Continue,
            },
        }
    }
}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct ModelPickerState {
    stage: ModelPickerStage,
    filter: String,
}

impl ModelPickerState {
    pub fn stage(&self) -> ModelPickerStage {
        self.stage
    }

    pub fn filter(&self) -> &str {
        &self.filter
    }

    pub fn provider_matches(&self) -> bool {
        matches_filter(MODEL_PICKER_PROVIDER, &self.filter)
    }

    pub fn model_matches(&self) -> bool {
        matches_filter(MODEL_PICKER_MODEL, &self.filter)
    }

    pub fn handle_key(&mut self, key: Key) -> ModelPickerAction {
        match key {
            Key::Char('q') if self.filter.is_empty() => ModelPickerAction::Closed,
            Key::Char(character) if !character.is_control() => {
                self.filter.push(character);
                ModelPickerAction::Continue
            }
            Key::Backspace => {
                self.filter.pop();
                ModelPickerAction::Continue
            }
            Key::Enter if self.stage == ModelPickerStage::Provider && self.provider_matches() => {
                self.stage = ModelPickerStage::Model;
                self.filter.clear();
                ModelPickerAction::Continue
            }
            Key::Escape if !self.filter.is_empty() => {
                self.filter.clear();
                ModelPickerAction::ClearedFilter
            }
            Key::Escape if self.stage == ModelPickerStage::Model => {
                self.stage = ModelPickerStage::Provider;
                self.filter.clear();
                ModelPickerAction::ReturnedToProvider
            }
            Key::Escape => ModelPickerAction::Closed,
            _ => ModelPickerAction::Continue,
        }
    }
}

fn matches_filter(value: &str, filter: &str) -> bool {
    filter.is_empty() || value.to_ascii_lowercase().contains(&filter.to_ascii_lowercase())
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum Notice {
    UnknownCommand { command: String },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct Message {
    pub role: Role,
    pub content: String,
}

impl Message {
    pub fn new(role: Role, content: impl Into<String>) -> Self {
        Self { role, content: content.into() }
    }

    pub fn system(content: impl Into<String>) -> Self {
        Self::new(Role::System, content)
    }

    pub fn user(content: impl Into<String>) -> Self {
        Self::new(Role::User, content)
    }
}

pub const OBSERVED_SLASH_COMPLETIONS: [&str; 3] =
    ["/help", "/hermes-agent", "/hermes-agent-skill-authoring"];

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct CompletionState {
    items: Vec<String>,
}

impl CompletionState {
    pub fn for_draft(draft: &str) -> Self {
        if draft == "/model" {
            return Self { items: vec!["/model".to_owned()] };
        }

        if draft == "/setup" {
            return Self { items: vec!["/setup".to_owned()] };
        }

        if draft == "/he" {
            return Self {
                items: OBSERVED_SLASH_COMPLETIONS.iter().map(|item| (*item).to_owned()).collect(),
            };
        }

        Self::default()
    }

    pub fn is_visible(&self) -> bool {
        !self.items.is_empty()
    }

    pub fn items(&self) -> &[String] {
        &self.items
    }

    pub fn first_item(&self) -> Option<&str> {
        self.items.first().map(String::as_str)
    }
}

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct Composer {
    text: String,
    cursor: usize,
    history: Vec<String>,
    history_index: Option<usize>,
    history_draft: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EnterAction {
    Submit(String),
    InsertedNewline,
}

impl Composer {
    pub fn with_history(history: Vec<String>) -> Self {
        let start = history.len().saturating_sub(MAX_INPUT_HISTORY);

        Self { history: history.into_iter().skip(start).collect(), ..Self::default() }
    }

    pub fn text(&self) -> &str {
        &self.text
    }

    pub const fn cursor(&self) -> usize {
        self.cursor
    }

    pub fn insert(&mut self, character: char) {
        let byte = self.byte_index_at(self.cursor);
        self.text.insert(byte, character);
        self.cursor += 1;
        self.reset_history_navigation();
    }

    pub fn insert_text(&mut self, text: &str) {
        if text.is_empty() {
            return;
        }

        let byte = self.byte_index_at(self.cursor);
        self.text.insert_str(byte, text);
        self.cursor += text.chars().count();
        self.reset_history_navigation();
    }

    pub fn insert_newline(&mut self) {
        self.insert('\n');
    }

    pub const fn move_left(&mut self) {
        self.cursor = self.cursor.saturating_sub(1);
    }

    pub fn move_right(&mut self) {
        self.cursor = (self.cursor + 1).min(self.text.chars().count());
    }

    pub const fn move_home(&mut self) {
        self.cursor = 0;
    }

    pub fn move_end(&mut self) {
        self.cursor = self.text.chars().count();
    }

    pub fn backspace(&mut self) {
        if self.cursor == 0 {
            return;
        }

        self.remove_before_cursor();
        self.reset_history_navigation();
    }

    pub const fn kill_to_start(&mut self) {
        self.cursor = 0;
    }

    pub fn kill_to_end(&mut self) {
        self.text.truncate(self.byte_index_at(self.cursor));
        self.reset_history_navigation();
    }

    pub fn enter(&mut self) -> EnterAction {
        if self.character_before_cursor() == Some('\\') {
            self.remove_before_cursor();
            self.insert_newline();
            return EnterAction::InsertedNewline;
        }

        EnterAction::Submit(self.text.clone())
    }

    pub fn record_submission(&mut self, text: impl Into<String>) {
        let text = text.into().trim().to_owned();
        if !text.is_empty() && self.history.last() != Some(&text) {
            self.history.push(text);
            if self.history.len() > MAX_INPUT_HISTORY {
                let excess = self.history.len() - MAX_INPUT_HISTORY;
                self.history.drain(..excess);
            }
        }
        self.reset_history_navigation();
    }

    pub fn clear(&mut self) {
        self.text.clear();
        self.cursor = 0;
        self.reset_history_navigation();
    }

    pub fn replace(&mut self, text: impl Into<String>) {
        self.replace_text(text.into());
        self.reset_history_navigation();
    }

    pub fn history_up(&mut self) -> bool {
        if self.history.is_empty() {
            return false;
        }

        let index = match self.history_index {
            Some(index) if index > 0 => index - 1,
            Some(_) => return false,
            None => {
                self.history_draft = self.text.clone();
                self.history.len() - 1
            }
        };
        self.history_index = Some(index);
        self.replace_with_history(index);
        true
    }

    pub fn history_down(&mut self) -> bool {
        let Some(index) = self.history_index else {
            return false;
        };

        if index + 1 < self.history.len() {
            self.history_index = Some(index + 1);
            self.replace_with_history(index + 1);
        } else {
            let draft = std::mem::take(&mut self.history_draft);
            self.history_index = None;
            self.replace_text(draft);
        }
        true
    }

    fn replace_with_history(&mut self, index: usize) {
        self.replace_text(self.history[index].clone());
    }

    fn replace_text(&mut self, text: String) {
        self.text = text;
        self.cursor = self.text.chars().count();
    }

    fn reset_history_navigation(&mut self) {
        self.history_index = None;
        self.history_draft.clear();
    }

    fn character_before_cursor(&self) -> Option<char> {
        (self.cursor > 0).then(|| self.text.chars().nth(self.cursor - 1)).flatten()
    }

    fn remove_before_cursor(&mut self) {
        let start = self.byte_index_at(self.cursor - 1);
        let end = self.byte_index_at(self.cursor);
        self.text.replace_range(start..end, "");
        self.cursor -= 1;
    }

    fn byte_index_at(&self, character_index: usize) -> usize {
        self.text.char_indices().nth(character_index).map_or(self.text.len(), |(byte, _)| byte)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SessionState {
    pub surface: Surface,
    pub turn: TurnState,
    pub overlay: Option<Overlay>,
    pub model_picker: Option<ModelPickerState>,
    pub setup_wizard: Option<SetupWizardState>,
    pub notice: Option<Notice>,
    pub composer: Composer,
    pub completion: CompletionState,
    pub messages: Vec<Message>,
    pub status: String,
    pub should_quit: bool,
}

impl Default for SessionState {
    fn default() -> Self {
        Self {
            surface: Surface::Home,
            turn: TurnState::Ready,
            overlay: None,
            model_picker: None,
            setup_wizard: None,
            notice: None,
            composer: Composer::default(),
            completion: CompletionState::default(),
            messages: Vec::new(),
            status: "Reference behavior pending capture.".to_owned(),
            should_quit: false,
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum Key {
    Char(char),
    Enter,
    ModifiedEnter,
    Backspace,
    Escape,
    Tab,
    Up,
    Down,
    Left,
    Right,
    Home,
    End,
    Ctrl(char),
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum InputEvent {
    Key(Key),
    Paste(String),
    Resize { width: u16, height: u16 },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TraceStep {
    pub input: InputEvent,
    pub expected_surface: Option<Surface>,
    pub expected_status: Option<String>,
    pub expected_input: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct InteractionTrace {
    pub schema_version: u32,
    pub observation_id: String,
    pub steps: Vec<TraceStep>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn composer_edits_at_character_boundaries() {
        let mut composer = Composer::default();
        for character in "abc".chars() {
            composer.insert(character);
        }

        composer.move_left();
        composer.insert('X');
        assert_eq!(composer.text(), "abXc");

        composer.backspace();
        assert_eq!(composer.text(), "abc");

        composer.move_home();
        composer.insert('z');
        composer.move_end();
        composer.insert('!');
        assert_eq!(composer.text(), "zabc!");
        assert_eq!(composer.cursor(), 5);
    }

    #[test]
    fn composer_handles_unicode_without_slicing_inside_a_character() {
        let mut composer = Composer::default();
        for character in "é猫".chars() {
            composer.insert(character);
        }

        composer.move_left();
        composer.insert('X');
        assert_eq!(composer.text(), "éX猫");
        composer.backspace();
        assert_eq!(composer.text(), "é猫");
    }

    #[test]
    fn composer_history_returns_to_the_draft_after_the_newest_entry() {
        let mut composer = Composer::default();
        composer.insert('d');
        composer.record_submission("alpha");
        composer.clear();

        assert!(composer.history_up());
        assert_eq!(composer.text(), "alpha");
        assert!(composer.history_down());
        assert_eq!(composer.text(), "");
    }

    #[test]
    fn composer_history_keeps_the_newest_thousand_entries() {
        let history = (1..=1001).map(|index| format!("cap-{index:04}")).collect();
        let mut composer = Composer::with_history(history);

        assert!(composer.history_up());
        assert_eq!(composer.text(), "cap-1001");
        for _ in 0..999 {
            composer.history_up();
        }
        assert_eq!(composer.text(), "cap-0002");
        assert!(!composer.history_up());
        assert_eq!(composer.text(), "cap-0002");
    }

    #[test]
    fn composer_history_trims_and_suppresses_consecutive_duplicates() {
        let mut composer = Composer::default();

        composer.record_submission("  alpha  ");
        composer.record_submission("alpha");
        composer.record_submission("beta");
        composer.record_submission("alpha");

        assert!(composer.history_up());
        assert_eq!(composer.text(), "alpha");
        assert!(composer.history_down());
        assert_eq!(composer.text(), "");
        assert!(composer.history_up());
        assert_eq!(composer.text(), "alpha");
        assert!(composer.history_up());
        assert_eq!(composer.text(), "beta");
    }

    #[test]
    fn composer_backslash_enter_inserts_a_newline_instead_of_submitting() {
        let mut composer = Composer::default();
        for character in "line-one\\".chars() {
            composer.insert(character);
        }

        assert_eq!(composer.enter(), EnterAction::InsertedNewline);
        composer.insert('x');
        assert_eq!(composer.text(), "line-one\nx");
    }

    #[test]
    fn composer_modified_enter_inserts_a_newline_at_the_cursor() {
        let mut composer = Composer::default();
        composer.insert_text("first");

        composer.insert_newline();
        composer.insert_text("second");

        assert_eq!(composer.text(), "first\nsecond");
        assert_eq!(composer.cursor(), 12);
    }

    #[test]
    fn completion_state_is_exactly_scoped_to_observed_slash_prefix() {
        let completion = CompletionState::for_draft("/he");

        assert_eq!(
            completion.items(),
            &[
                "/help".to_owned(),
                "/hermes-agent".to_owned(),
                "/hermes-agent-skill-authoring".to_owned(),
            ]
        );
        assert!(!CompletionState::for_draft("/h").is_visible());
        assert!(!CompletionState::for_draft("/hel").is_visible());
    }

    #[test]
    fn composer_replace_moves_cursor_to_the_applied_completion() {
        let mut composer = Composer::default();
        composer.insert('/');
        composer.insert('h');
        composer.insert('e');

        composer.replace("/help");

        assert_eq!(composer.text(), "/help");
        assert_eq!(composer.cursor(), 5);
    }

    #[test]
    fn composer_paste_preserves_newlines_at_the_cursor() {
        let mut composer = Composer::default();
        composer.insert_text("left-right");
        composer.move_left();

        composer.insert_text("paste-one\npaste-two");

        assert_eq!(composer.text(), "left-righpaste-one\npaste-twot");
        assert_eq!(composer.cursor(), 28);
    }

    #[test]
    fn surface_cycle_is_closed_and_deterministic() {
        let mut surface = Surface::Home;
        for expected in [Surface::Conversation, Surface::Settings, Surface::Home] {
            surface = surface.next();
            assert_eq!(surface, expected);
        }
    }

    #[test]
    fn messages_keep_role_and_content_separate() {
        assert_eq!(
            Message::user("hello"),
            Message { role: Role::User, content: "hello".to_owned() }
        );
    }

    #[test]
    fn model_picker_filters_then_escapes_back_through_typed_stages() {
        let mut picker = ModelPickerState::default();
        for character in "palette".chars() {
            assert_eq!(picker.handle_key(Key::Char(character)), ModelPickerAction::Continue);
        }
        assert_eq!(picker.filter(), "palette");
        assert!(picker.provider_matches());

        assert_eq!(picker.handle_key(Key::Enter), ModelPickerAction::Continue);
        assert_eq!(picker.stage(), ModelPickerStage::Model);
        assert_eq!(picker.filter(), "");

        for character in "palette".chars() {
            picker.handle_key(Key::Char(character));
        }
        assert!(picker.model_matches());
        assert_eq!(picker.handle_key(Key::Escape), ModelPickerAction::ClearedFilter);
        assert_eq!(picker.stage(), ModelPickerStage::Model);
        assert_eq!(picker.filter(), "");
        assert_eq!(picker.handle_key(Key::Escape), ModelPickerAction::ReturnedToProvider);
        assert_eq!(picker.stage(), ModelPickerStage::Provider);
        assert_eq!(picker.handle_key(Key::Escape), ModelPickerAction::Closed);
    }

    #[test]
    fn setup_wizard_moves_cursor_without_committing_then_enters_numbered_fallback() {
        let mut wizard = SetupWizardState::default();

        assert_eq!(wizard.cursor_label(), SETUP_WIZARD_CHOICES[0]);
        assert_eq!(wizard.selected_label(), SETUP_WIZARD_CHOICES[0]);
        assert_eq!(wizard.handle_key(Key::Down), SetupWizardAction::Moved);
        assert_eq!(wizard.cursor_label(), SETUP_WIZARD_CHOICES[1]);
        assert_eq!(wizard.selected_label(), SETUP_WIZARD_CHOICES[0]);
        assert_eq!(wizard.handle_key(Key::Escape), SetupWizardAction::EnteredFallback);
        assert!(wizard.is_fallback());
        assert_eq!(wizard.handle_key(Key::Ctrl('c')), SetupWizardAction::Quit);
    }

    #[test]
    fn setup_wizard_enters_bounded_full_provider_menu_without_selecting_a_provider() {
        let mut wizard = SetupWizardState::default();

        assert_eq!(wizard.handle_key(Key::Down), SetupWizardAction::Moved);
        assert_eq!(wizard.handle_key(Key::Enter), SetupWizardAction::EnteredProviderMenu);
        assert!(wizard.is_provider_menu());
        assert_eq!(wizard.provider_cursor(), 0);
        assert_eq!(wizard.provider_cursor_label(), SETUP_PROVIDER_MENU_ROWS[0]);
        assert_eq!(wizard.selected_label(), SETUP_WIZARD_CHOICES[0]);

        assert_eq!(wizard.handle_key(Key::Down), SetupWizardAction::Moved);
        assert_eq!(wizard.provider_cursor(), 1);
        assert_eq!(wizard.handle_key(Key::Up), SetupWizardAction::Moved);
        assert_eq!(wizard.provider_cursor(), 0);
        assert_eq!(wizard.handle_key(Key::Enter), SetupWizardAction::EnteredModelNamePrompt);
        assert!(wizard.is_model_name_prompt());
        assert_eq!(wizard.handle_key(Key::Ctrl('c')), SetupWizardAction::Quit);
    }
}
