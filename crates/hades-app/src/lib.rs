#![forbid(unsafe_code)]

use hades_core::{InputEvent, Key, Message, Overlay, SessionState, TurnState};

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DispatchOutcome {
    Continue,
    Submitted(String),
    Interrupted,
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
                Overlay::SetupRequired => match key {
                    Key::Ctrl('c') if !self.state.input.is_empty() => {
                        self.state.input.clear();
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

        if content == "/help" {
            self.state.overlay = Some(Overlay::SetupRequired);
            self.state.status = "Setup required.".to_owned();
            return DispatchOutcome::Continue;
        }

        self.state.messages.push(Message::user(&content));
        self.state.input.clear();
        self.state.turn = TurnState::Busy;
        self.state.status = "Busy; response adapter not connected.".to_owned();
        DispatchOutcome::Submitted(content)
    }

    fn interrupt(&mut self) -> DispatchOutcome {
        self.state.turn = TurnState::Ready;
        self.state.status = "Interrupted.".to_owned();
        DispatchOutcome::Interrupted
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
        for character in "hello".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }

        assert_eq!(
            app.handle(InputEvent::Key(Key::Enter)),
            DispatchOutcome::Submitted("hello".to_owned())
        );
        assert_eq!(app.state().input, "");
        assert_eq!(app.state().turn, TurnState::Busy);
        assert_eq!(app.state().status, "Busy; response adapter not connected.");
        assert_eq!(app.state().messages.last().unwrap().content, "hello");
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
    fn ctrl_x_opens_sessions_overlay_and_escape_restores_composer() {
        let mut app = App::new();

        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('x'))), DispatchOutcome::Continue);
        assert_eq!(app.state().overlay, Some(Overlay::Sessions));

        app.handle(InputEvent::Key(Key::Char('h')));
        assert_eq!(app.state().input, "");

        assert_eq!(app.handle(InputEvent::Key(Key::Escape)), DispatchOutcome::Continue);
        assert_eq!(app.state().overlay, None);
        app.handle(InputEvent::Key(Key::Char('h')));
        assert_eq!(app.state().input, "h");
    }

    #[test]
    fn help_opens_setup_overlay_and_requires_two_ctrl_c_presses_to_exit() {
        let mut app = App::new();
        for character in "/help".chars() {
            app.handle(InputEvent::Key(Key::Char(character)));
        }

        assert_eq!(app.handle(InputEvent::Key(Key::Enter)), DispatchOutcome::Continue);
        assert_eq!(app.state().overlay, Some(Overlay::SetupRequired));
        assert_eq!(app.state().input, "/help");

        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('c'))), DispatchOutcome::Continue);
        assert_eq!(app.state().overlay, Some(Overlay::SetupRequired));
        assert_eq!(app.state().input, "");
        assert!(!app.state().should_quit);

        assert_eq!(app.handle(InputEvent::Key(Key::Ctrl('c'))), DispatchOutcome::Quit);
        assert!(app.state().should_quit);
    }
}
