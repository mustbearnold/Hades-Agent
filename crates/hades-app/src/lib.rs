#![forbid(unsafe_code)]

use hades_core::{InputEvent, Key, Message, SessionState};

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DispatchOutcome {
    Continue,
    Submitted(String),
    Quit,
}

#[derive(Clone, Debug)]
pub struct App {
    state: SessionState,
}

impl App {
    pub fn new() -> Self {
        let mut state = SessionState::default();
        state.messages.push(Message::system(
            "Hades Agent bootstrap shell. Reference-backed behavior is not implemented yet.",
        ));
        Self { state }
    }

    pub fn state(&self) -> &SessionState {
        &self.state
    }

    pub fn handle(&mut self, event: InputEvent) -> DispatchOutcome {
        match event {
            InputEvent::Resize { width, height } => {
                self.state.status = format!("Terminal size: {width}x{height}.");
                DispatchOutcome::Continue
            }
            InputEvent::Key(key) => self.handle_key(key),
        }
    }

    fn handle_key(&mut self, key: Key) -> DispatchOutcome {
        match key {
            Key::Ctrl('c') | Key::Ctrl('q') => self.quit(),
            Key::Char('q') if self.state.input.is_empty() => self.quit(),
            Key::Char(character) => {
                self.state.input.push(character);
                self.state.status = "Editing input.".to_owned();
                DispatchOutcome::Continue
            }
            Key::Backspace => {
                self.state.input.pop();
                DispatchOutcome::Continue
            }
            Key::Enter => self.submit(),
            Key::Escape => {
                self.state.input.clear();
                self.state.status = "Input cleared.".to_owned();
                DispatchOutcome::Continue
            }
            Key::Tab => {
                self.state.surface = self.state.surface.next();
                self.state.status = format!("Surface: {}.", self.state.surface.label());
                DispatchOutcome::Continue
            }
            Key::Up | Key::Down | Key::Left | Key::Right => DispatchOutcome::Continue,
            Key::Ctrl(_) => DispatchOutcome::Continue,
        }
    }

    fn submit(&mut self) -> DispatchOutcome {
        let content = self.state.input.trim().to_owned();
        if content.is_empty() {
            self.state.status = "Nothing to submit.".to_owned();
            return DispatchOutcome::Continue;
        }

        self.state.messages.push(Message::user(&content));
        self.state.input.clear();
        self.state.status = "Submitted; response adapter not connected.".to_owned();
        DispatchOutcome::Submitted(content)
    }

    fn quit(&mut self) -> DispatchOutcome {
        self.state.should_quit = true;
        DispatchOutcome::Quit
    }
}

impl Default for App {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use hades_core::{InputEvent, Key, Surface};

    #[test]
    fn input_submission_is_deterministic_and_recorded() {
        let mut app = App::new();
        app.handle(InputEvent::Key(Key::Char('h')));
        app.handle(InputEvent::Key(Key::Char('i')));

        assert_eq!(
            app.handle(InputEvent::Key(Key::Enter)),
            DispatchOutcome::Submitted("hi".to_owned())
        );
        assert_eq!(app.state().input, "");
        assert_eq!(app.state().messages.last().unwrap().content, "hi");
    }

    #[test]
    fn tab_cycles_surfaces_and_control_c_quits() {
        let mut app = App::new();
        app.handle(InputEvent::Key(Key::Tab));
        assert_eq!(app.state().surface, Surface::Conversation);
        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('c'))), DispatchOutcome::Quit);
        assert!(app.state().should_quit);
    }
}
