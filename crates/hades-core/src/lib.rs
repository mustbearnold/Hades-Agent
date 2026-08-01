#![forbid(unsafe_code)]

use serde::{Deserialize, Serialize};

pub const PRODUCT_NAME: &str = "Hades Agent";

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
    SetupRequired,
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
            self.insert('\n');
            return EnterAction::InsertedNewline;
        }

        EnterAction::Submit(self.text.clone())
    }

    pub fn record_submission(&mut self, text: impl Into<String>) {
        let text = text.into();
        if !text.trim().is_empty() {
            self.history.push(text);
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

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum InputEvent {
    Key(Key),
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
}
