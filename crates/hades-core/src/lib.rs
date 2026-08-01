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

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SessionState {
    pub surface: Surface,
    pub turn: TurnState,
    pub input: String,
    pub messages: Vec<Message>,
    pub status: String,
    pub should_quit: bool,
}

impl Default for SessionState {
    fn default() -> Self {
        Self {
            surface: Surface::Home,
            turn: TurnState::Ready,
            input: String::new(),
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
