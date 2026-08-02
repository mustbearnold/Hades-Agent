#![forbid(unsafe_code)]

use serde::{Deserialize, Serialize};

pub const PRODUCT_NAME: &str = "Hades Agent";
pub const MAX_INPUT_HISTORY: usize = 1000;
pub const HELP_SETUP_REQUIRED_DELAY_MS: u64 = 8_000;
pub const SETUP_STANDALONE_BANNER: [&str; 6] = [
    "┌─────────────────────────────────────────────────────────┐",
    "│             ⚕ Hermes Agent Setup Wizard                │",
    "├─────────────────────────────────────────────────────────┤",
    "│  Let's configure your Hermes Agent installation.       │",
    "│  Press Ctrl+C at any time to exit.                     │",
    "└─────────────────────────────────────────────────────────┘",
];
pub const SETUP_STANDALONE_PROMPT: &str = "How would you like to set up Hermes?";
pub const SETUP_STANDALONE_CONTROLS: &str = "↑↓ navigate  ENTER/SPACE select  ESC cancel";
pub const SETUP_STANDALONE_CONFIG_TITLE: &str = "◆ Configuration Location";
pub const SETUP_STANDALONE_CONFIG_LINES: [&str; 5] = [
    "Config file:  <config-path>",
    "Secrets file: <secrets-path>",
    "Data folder:  <data-path>",
    "Install dir:  <install-dir>",
    "You can edit these files directly or use 'hermes config edit'",
];
pub const SETUP_STANDALONE_PROVIDER_TITLE: &str = "◆ Inference Provider";
pub const SETUP_STANDALONE_PROVIDER_PROMPT: &str = "Choose how to connect to your main chat model.";
pub const SETUP_STANDALONE_TERMINAL_TITLE: &str = "Terminal Backend";
pub const SETUP_STANDALONE_TERMINAL_LINES: [&str; 3] = [
    "Choose where Hermes runs shell commands and code.",
    "This affects tool execution, file access, and isolation.",
    "Guide: https://hermes-agent.nousresearch.com/docs/user-guide/configuration#terminal-backend-configuration",
];

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

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub enum StartupState {
    #[default]
    Ready,
    Unconfigured,
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
pub const SETUP_TERMINAL_BACKEND_TITLE: &str = "Select terminal backend:";
pub const SETUP_TERMINAL_BACKEND_ROWS: [&str; 8] = [
    "Local - run directly on this machine (default)",
    "Docker - isolated container with configurable resources",
    "Modal - serverless cloud sandbox",
    "SSH - run on a remote machine",
    "Daytona - persistent cloud development environment",
    "Vercel Sandbox - cloud microVM with snapshot filesystem persistence",
    "Singularity/Apptainer - HPC-friendly container",
    "Keep current (local)",
];
pub const SETUP_TERMINAL_BACKEND_CONTROLS: &str = "ENTER/SPACE select   ESC cancel";
pub const SETUP_PLATFORM_PICKER_TITLE: &str = "Select platforms to configure:";
pub const SETUP_PLATFORM_ROWS: [&str; 27] = [
    "💬  Mattermost",
    "📡  Signal",
    "💬  Weixin / WeChat",
    "💬  BlueBubbles (iMessage)",
    "🐧  QQ Bot",
    "💎  Yuanbao",
    "🐝  Buzz",
    "🐳  DingTalk",
    "🎮  Discord",
    "📧  Email",
    "🪽  Feishu / Lark",
    "💬  Google Chat",
    "🏠  Home Assistant",
    "💬  IRC",
    "💚  LINE",
    "🔐  Matrix",
    "🔔  ntfy",
    "📱  iMessage via Photon",
    "🔔  Raft",
    "🔒  SimpleX Chat",
    "💼  Slack",
    "📱  SMS (Twilio)",
    "💼  Microsoft Teams",
    "✈️  Telegram",
    "💼  WeCom (Enterprise WeChat)",
    "💼  WeCom Callback (self-built apps)",
    "💬  WhatsApp",
];
pub const SETUP_PLATFORM_PICKER_CONTROLS: &str =
    "↑↓ navigate  SPACE toggle  ENTER confirm  ESC cancel";
pub const SETUP_STANDALONE_NO_PLATFORMS: &str =
    "No platforms selected. Run 'hermes setup gateway' later to configure.";
pub const SETUP_STANDALONE_TOOL_CONFIGURATION_TITLE: &str = "⚕ Hermes Tool Configuration";
pub const SETUP_STANDALONE_TOOL_CONFIGURATION_LINES: [&str; 2] = [
    "Enable or disable tools per platform.",
    "Tools that need API keys will be configured when enabled.",
];
pub const SETUP_STANDALONE_TOOL_CHECKLIST_TITLE: &str = "Tools for 🖥️  CLI";
pub const SETUP_STANDALONE_TOOL_CHECKLIST_CONTROLS: &str =
    "↑↓ navigate  SPACE toggle  ENTER confirm  ESC cancel";
pub const SETUP_STANDALONE_TOOL_CHECKLIST_ROWS: [&str; 4] = [
    "🔍  Web Search & Scraping  (web_search, web_extract)",
    "🌐  Browser Automation  (navigate, click, type, scroll)",
    "💻  Terminal & Processes  (terminal, process)",
    "📁  File Operations  (read, write, patch, search)",
];
pub const SETUP_STANDALONE_TOOL_PROVIDER_LINES: [&str; 11] = [
    "Configuring 6 tool(s):",
    "  • 🌐 Browser Automation",
    "  • 🖱️  Computer Use (macOS/Windows/Linux)",
    "  • 🎨 Image Generation",
    "  • 🔊 Text-to-Speech",
    "  • 👁️  Vision / Image Analysis",
    "  • 🔍 Web Search & Scraping",
    "  You can skip any tool you don't need right now.",
    "",
    "",
    "  --- 🌐 Browser Automation - Choose a provider ---",
];
pub const SETUP_STANDALONE_TOOL_PROVIDER_TITLE: &str = "Choose a provider:";
pub const SETUP_STANDALONE_TOOL_PROVIDER_CONTROLS: &str =
    "↑↓ navigate  ENTER/SPACE select  ESC cancel";
pub const SETUP_STANDALONE_TOOL_PROVIDER_DEFAULT_INDEX: usize = 0;
pub const SETUP_STANDALONE_TOOL_PROVIDER_OPTIONS: [&str; 7] = [
    "Local Browser [★ recommended · free] — Headless Chromium, no API key needed",
    "Nous Subscription (Browser Use cloud) [subscription] — Managed Browser Use billed to your subscription",
    "Camofox [free · local] — Anti-detection browser (Firefox/Camoufox)",
    "Browser Use [paid] — Cloud browser with remote execution",
    "Browserbase [paid] — Cloud browser with stealth and proxies",
    "Firecrawl [paid] — Cloud browser with remote execution",
    "Skip — keep defaults / configure later",
];

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub enum StandaloneSetupSurface {
    #[default]
    Choices,
    FullSetupContinuation,
    TerminalBackend,
    PlatformPicker,
    ToolConfiguration,
    ToolChecklist,
    ToolProviderBoundary,
    NumberedFallback,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub enum StandaloneSetupFallback {
    #[default]
    SetupChoices,
    TerminalBackend,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum StandaloneSetupAction {
    Continue,
    Moved,
    EnteredFullSetupContinuation,
    SkippedProvider,
    EnteredPlatformPicker,
    ConfirmedEmptyPlatformSelection,
    EnteredToolConfiguration,
    EnteredToolChecklist,
    EnteredToolProviderBoundary,
    SelectedLocalBrowser,
    SkippedToolProvider,
    CancelledToolProvider,
    EnteredFallback,
    Quit,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum StandaloneToolProviderAction {
    LocalBrowserSelected,
    Skipped,
    Cancelled,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct StandaloneSetupState {
    surface: StandaloneSetupSurface,
    fallback: StandaloneSetupFallback,
    cursor: usize,
    selected: usize,
    terminal_backend_cursor: usize,
    tool_cursor: usize,
    tool_enabled: [bool; SETUP_STANDALONE_TOOL_CHECKLIST_ROWS.len()],
    provider_cursor: usize,
    provider_action: Option<StandaloneToolProviderAction>,
}

impl Default for StandaloneSetupState {
    fn default() -> Self {
        Self {
            surface: StandaloneSetupSurface::Choices,
            fallback: StandaloneSetupFallback::SetupChoices,
            cursor: 0,
            selected: 0,
            terminal_backend_cursor: SETUP_TERMINAL_BACKEND_ROWS.len() - 1,
            tool_cursor: 0,
            tool_enabled: [true; SETUP_STANDALONE_TOOL_CHECKLIST_ROWS.len()],
            provider_cursor: SETUP_STANDALONE_TOOL_PROVIDER_DEFAULT_INDEX,
            provider_action: None,
        }
    }
}

impl StandaloneSetupState {
    pub fn surface(&self) -> StandaloneSetupSurface {
        self.surface
    }

    pub fn cursor(&self) -> usize {
        self.cursor
    }

    pub fn selected(&self) -> usize {
        self.selected
    }

    pub fn terminal_backend_cursor(&self) -> usize {
        self.terminal_backend_cursor
    }

    pub fn tool_cursor(&self) -> usize {
        self.tool_cursor
    }

    pub fn tool_enabled(&self, index: usize) -> bool {
        self.tool_enabled.get(index).copied().unwrap_or(false)
    }

    pub fn terminal_backend_fallback(&self) -> bool {
        self.fallback == StandaloneSetupFallback::TerminalBackend
    }

    pub fn is_full_setup_continuation(&self) -> bool {
        self.surface == StandaloneSetupSurface::FullSetupContinuation
    }

    pub fn is_terminal_backend(&self) -> bool {
        self.surface == StandaloneSetupSurface::TerminalBackend
    }

    pub fn is_platform_picker(&self) -> bool {
        self.surface == StandaloneSetupSurface::PlatformPicker
    }

    pub fn is_tool_configuration(&self) -> bool {
        self.surface == StandaloneSetupSurface::ToolConfiguration
    }

    pub fn is_tool_checklist(&self) -> bool {
        self.surface == StandaloneSetupSurface::ToolChecklist
    }

    pub fn is_tool_provider_boundary(&self) -> bool {
        self.surface == StandaloneSetupSurface::ToolProviderBoundary
    }

    pub fn provider_cursor(&self) -> usize {
        self.provider_cursor
    }

    pub fn provider_action(&self) -> Option<StandaloneToolProviderAction> {
        self.provider_action
    }

    pub fn is_numbered_fallback(&self) -> bool {
        self.surface == StandaloneSetupSurface::NumberedFallback
    }

    pub fn handle_key(&mut self, key: Key) -> StandaloneSetupAction {
        match self.surface {
            StandaloneSetupSurface::Choices => match key {
                Key::Enter | Key::Char(' ') if self.cursor == 1 => {
                    self.surface = StandaloneSetupSurface::FullSetupContinuation;
                    StandaloneSetupAction::EnteredFullSetupContinuation
                }
                Key::Down | Key::Char('j') => {
                    self.cursor = (self.cursor + 1).min(SETUP_WIZARD_CHOICES.len() - 1);
                    StandaloneSetupAction::Moved
                }
                Key::Up | Key::Char('k') => {
                    self.cursor = self.cursor.saturating_sub(1);
                    StandaloneSetupAction::Moved
                }
                Key::Escape => {
                    self.fallback = StandaloneSetupFallback::SetupChoices;
                    self.surface = StandaloneSetupSurface::NumberedFallback;
                    StandaloneSetupAction::EnteredFallback
                }
                Key::Ctrl('c') => StandaloneSetupAction::Quit,
                _ => StandaloneSetupAction::Continue,
            },
            StandaloneSetupSurface::FullSetupContinuation => match key {
                Key::Ctrl('c') => {
                    self.surface = StandaloneSetupSurface::TerminalBackend;
                    StandaloneSetupAction::SkippedProvider
                }
                _ => StandaloneSetupAction::Continue,
            },
            StandaloneSetupSurface::TerminalBackend => match key {
                Key::Enter | Key::Char(' ')
                    if self.terminal_backend_cursor + 1 == SETUP_TERMINAL_BACKEND_ROWS.len() =>
                {
                    self.surface = StandaloneSetupSurface::PlatformPicker;
                    StandaloneSetupAction::EnteredPlatformPicker
                }
                Key::Down | Key::Char('j') => {
                    self.terminal_backend_cursor = (self.terminal_backend_cursor + 1)
                        .min(SETUP_TERMINAL_BACKEND_ROWS.len() - 1);
                    StandaloneSetupAction::Moved
                }
                Key::Up | Key::Char('k') => {
                    self.terminal_backend_cursor = self.terminal_backend_cursor.saturating_sub(1);
                    StandaloneSetupAction::Moved
                }
                Key::Ctrl('c') => {
                    self.fallback = StandaloneSetupFallback::TerminalBackend;
                    self.surface = StandaloneSetupSurface::NumberedFallback;
                    StandaloneSetupAction::EnteredFallback
                }
                _ => StandaloneSetupAction::Continue,
            },
            StandaloneSetupSurface::PlatformPicker => match key {
                Key::Enter => StandaloneSetupAction::ConfirmedEmptyPlatformSelection,
                Key::Ctrl('c') => {
                    self.surface = StandaloneSetupSurface::ToolConfiguration;
                    StandaloneSetupAction::EnteredToolConfiguration
                }
                _ => StandaloneSetupAction::Continue,
            },
            StandaloneSetupSurface::ToolConfiguration => match key {
                Key::Escape => {
                    self.surface = StandaloneSetupSurface::ToolChecklist;
                    StandaloneSetupAction::EnteredToolChecklist
                }
                _ => StandaloneSetupAction::Continue,
            },
            StandaloneSetupSurface::ToolChecklist => match key {
                Key::Down | Key::Char('j') => {
                    self.tool_cursor =
                        (self.tool_cursor + 1).min(SETUP_STANDALONE_TOOL_CHECKLIST_ROWS.len() - 1);
                    StandaloneSetupAction::Moved
                }
                Key::Up | Key::Char('k') => {
                    self.tool_cursor = self.tool_cursor.saturating_sub(1);
                    StandaloneSetupAction::Moved
                }
                Key::Char(' ') => {
                    self.tool_enabled[self.tool_cursor] = !self.tool_enabled[self.tool_cursor];
                    StandaloneSetupAction::Continue
                }
                Key::Ctrl('c') => {
                    self.provider_action = None;
                    self.surface = StandaloneSetupSurface::ToolProviderBoundary;
                    StandaloneSetupAction::EnteredToolProviderBoundary
                }
                _ => StandaloneSetupAction::Continue,
            },
            StandaloneSetupSurface::ToolProviderBoundary => match key {
                Key::Down => {
                    self.provider_cursor =
                        (self.provider_cursor + 1) % SETUP_STANDALONE_TOOL_PROVIDER_OPTIONS.len();
                    StandaloneSetupAction::Moved
                }
                Key::Up => {
                    self.provider_cursor = if self.provider_cursor == 0 {
                        SETUP_STANDALONE_TOOL_PROVIDER_OPTIONS.len() - 1
                    } else {
                        self.provider_cursor - 1
                    };
                    StandaloneSetupAction::Moved
                }
                Key::Enter | Key::Char(' ') => match self.provider_cursor {
                    SETUP_STANDALONE_TOOL_PROVIDER_DEFAULT_INDEX => {
                        self.provider_action =
                            Some(StandaloneToolProviderAction::LocalBrowserSelected);
                        StandaloneSetupAction::SelectedLocalBrowser
                    }
                    index if index + 1 == SETUP_STANDALONE_TOOL_PROVIDER_OPTIONS.len() => {
                        self.provider_action = Some(StandaloneToolProviderAction::Skipped);
                        StandaloneSetupAction::SkippedToolProvider
                    }
                    _ => StandaloneSetupAction::Continue,
                },
                Key::Escape => {
                    self.provider_action = Some(StandaloneToolProviderAction::Cancelled);
                    StandaloneSetupAction::CancelledToolProvider
                }
                _ => StandaloneSetupAction::Continue,
            },
            StandaloneSetupSurface::NumberedFallback => match key {
                Key::Ctrl('c') => StandaloneSetupAction::Quit,
                _ => StandaloneSetupAction::Continue,
            },
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub enum SetupWizardSurface {
    #[default]
    Choices,
    NumberedFallback,
    FullSetupProviderMenu,
    ModelNamePrompt,
    TerminalBackendPicker,
    PlatformPicker,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum SetupWizardAction {
    Continue,
    Moved,
    EnteredFallback,
    EnteredProviderMenu,
    EnteredModelNamePrompt,
    EnteredTerminalBackendPicker,
    EnteredPlatformPicker,
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

    pub fn is_terminal_backend_picker(&self) -> bool {
        self.surface == SetupWizardSurface::TerminalBackendPicker
    }

    pub fn is_platform_picker(&self) -> bool {
        self.surface == SetupWizardSurface::PlatformPicker
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
                Key::Enter => {
                    self.surface = SetupWizardSurface::TerminalBackendPicker;
                    SetupWizardAction::EnteredTerminalBackendPicker
                }
                Key::Ctrl('c') => SetupWizardAction::Quit,
                _ => SetupWizardAction::Continue,
            },
            SetupWizardSurface::TerminalBackendPicker => match key {
                Key::Enter | Key::Char(' ') => {
                    self.surface = SetupWizardSurface::PlatformPicker;
                    SetupWizardAction::EnteredPlatformPicker
                }
                Key::Ctrl('c') => SetupWizardAction::Quit,
                _ => SetupWizardAction::Continue,
            },
            SetupWizardSurface::PlatformPicker => match key {
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
    ProviderError { message: String },
    ProviderCancelled,
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

    pub fn assistant(content: impl Into<String>) -> Self {
        Self::new(Role::Assistant, content)
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
    pub startup: StartupState,
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
            startup: StartupState::Ready,
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
pub enum ProviderEvent {
    Started,
    TextDelta(String),
    Completed,
    Failed(String),
    Cancelled,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum InputEvent {
    Key(Key),
    Paste(String),
    Resize { width: u16, height: u16 },
    Tick,
    Provider(ProviderEvent),
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
    fn composer_submit_and_clear_keep_the_draft_boundary_explicit() {
        let mut composer = Composer::default();
        composer.insert_text("queued hello");

        assert_eq!(composer.enter(), EnterAction::Submit("queued hello".to_owned()));
        assert_eq!(composer.text(), "queued hello");

        composer.clear();
        assert_eq!(composer.text(), "");
        assert_eq!(composer.cursor(), 0);
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

    #[test]
    fn setup_wizard_accepts_the_model_default_into_a_display_only_backend_picker() {
        let mut wizard = SetupWizardState::default();

        assert_eq!(wizard.handle_key(Key::Down), SetupWizardAction::Moved);
        assert_eq!(wizard.handle_key(Key::Enter), SetupWizardAction::EnteredProviderMenu);
        assert_eq!(wizard.handle_key(Key::Enter), SetupWizardAction::EnteredModelNamePrompt);
        assert_eq!(wizard.handle_key(Key::Enter), SetupWizardAction::EnteredTerminalBackendPicker);
        assert!(wizard.is_terminal_backend_picker());
        assert_eq!(wizard.provider_cursor(), 0);
        assert_eq!(wizard.provider_cursor_label(), SETUP_PROVIDER_MENU_ROWS[0]);
        assert_eq!(wizard.handle_key(Key::Char(' ')), SetupWizardAction::EnteredPlatformPicker);
        assert!(wizard.is_platform_picker());
        assert_eq!(wizard.handle_key(Key::Char(' ')), SetupWizardAction::Continue);
        assert_eq!(wizard.handle_key(Key::Ctrl('c')), SetupWizardAction::Quit);
    }

    #[test]
    fn standalone_setup_full_branch_follows_the_observed_interrupt_chain() {
        let mut setup = StandaloneSetupState::default();

        assert_eq!(setup.handle_key(Key::Down), StandaloneSetupAction::Moved);
        assert_eq!(
            setup.handle_key(Key::Enter),
            StandaloneSetupAction::EnteredFullSetupContinuation
        );
        assert!(setup.is_full_setup_continuation());

        assert_eq!(setup.handle_key(Key::Ctrl('c')), StandaloneSetupAction::SkippedProvider);
        assert!(setup.is_terminal_backend());
        assert_eq!(setup.terminal_backend_cursor(), SETUP_TERMINAL_BACKEND_ROWS.len() - 1);

        assert_eq!(setup.handle_key(Key::Enter), StandaloneSetupAction::EnteredPlatformPicker);
        assert!(setup.is_platform_picker());
        assert_eq!(
            setup.handle_key(Key::Ctrl('c')),
            StandaloneSetupAction::EnteredToolConfiguration
        );
        assert!(setup.is_tool_configuration());
    }

    #[test]
    fn standalone_setup_non_default_backend_does_not_claim_unobserved_selection() {
        let mut setup = StandaloneSetupState::default();

        setup.handle_key(Key::Down);
        setup.handle_key(Key::Enter);
        setup.handle_key(Key::Ctrl('c'));
        setup.handle_key(Key::Up);

        assert_eq!(setup.handle_key(Key::Enter), StandaloneSetupAction::Continue);
        assert!(setup.is_terminal_backend());
    }

    #[test]
    fn standalone_setup_platform_picker_cancellation_enters_tool_configuration() {
        let mut setup = StandaloneSetupState::default();

        setup.handle_key(Key::Down);
        setup.handle_key(Key::Enter);
        setup.handle_key(Key::Ctrl('c'));
        assert_eq!(setup.handle_key(Key::Enter), StandaloneSetupAction::EnteredPlatformPicker);
        assert_eq!(
            setup.handle_key(Key::Ctrl('c')),
            StandaloneSetupAction::EnteredToolConfiguration
        );
        assert!(setup.is_tool_configuration());
    }

    #[test]
    fn standalone_empty_platform_confirmation_is_typed_noop() {
        let mut setup = StandaloneSetupState::default();

        setup.handle_key(Key::Down);
        setup.handle_key(Key::Enter);
        setup.handle_key(Key::Ctrl('c'));
        assert_eq!(setup.handle_key(Key::Enter), StandaloneSetupAction::EnteredPlatformPicker);
        assert!(setup.is_platform_picker());

        assert_eq!(
            setup.handle_key(Key::Enter),
            StandaloneSetupAction::ConfirmedEmptyPlatformSelection
        );
        assert!(setup.is_platform_picker());
        assert_eq!(
            setup.handle_key(Key::Ctrl('c')),
            StandaloneSetupAction::EnteredToolConfiguration
        );
    }

    #[test]
    fn standalone_tool_configuration_escape_enters_a_non_submitting_checklist() {
        let mut setup = StandaloneSetupState::default();

        setup.handle_key(Key::Down);
        setup.handle_key(Key::Enter);
        setup.handle_key(Key::Ctrl('c'));
        setup.handle_key(Key::Enter);
        assert_eq!(
            setup.handle_key(Key::Ctrl('c')),
            StandaloneSetupAction::EnteredToolConfiguration
        );
        assert_eq!(setup.handle_key(Key::Escape), StandaloneSetupAction::EnteredToolChecklist);
        assert!(setup.is_tool_checklist());
        assert_eq!(setup.tool_cursor(), 0);
        assert!(setup.tool_enabled(0));
        assert_eq!(setup.handle_key(Key::Char('j')), StandaloneSetupAction::Moved);
        assert_eq!(setup.tool_cursor(), 1);
        assert!(setup.tool_enabled(0));
        assert!(setup.tool_enabled(1));
        assert_eq!(
            setup.handle_key(Key::Ctrl('c')),
            StandaloneSetupAction::EnteredToolProviderBoundary
        );
        assert!(setup.is_tool_provider_boundary());
    }

    #[test]
    fn standalone_tool_checklist_space_is_local_and_does_not_confirm() {
        let mut setup = StandaloneSetupState::default();

        setup.handle_key(Key::Down);
        setup.handle_key(Key::Enter);
        setup.handle_key(Key::Ctrl('c'));
        setup.handle_key(Key::Enter);
        setup.handle_key(Key::Ctrl('c'));
        setup.handle_key(Key::Escape);

        assert_eq!(setup.handle_key(Key::Char(' ')), StandaloneSetupAction::Continue);
        assert!(!setup.tool_enabled(0));
        assert!(setup.is_tool_checklist());
        assert_eq!(setup.handle_key(Key::Enter), StandaloneSetupAction::Continue);
        assert!(setup.is_tool_checklist());
    }

    #[test]
    fn standalone_tool_provider_inventory_is_a_display_only_observation() {
        assert_eq!(SETUP_STANDALONE_TOOL_PROVIDER_DEFAULT_INDEX, 0);
        assert_eq!(SETUP_STANDALONE_TOOL_PROVIDER_OPTIONS.len(), 7);
        assert!(SETUP_STANDALONE_TOOL_PROVIDER_OPTIONS[0].contains("Local Browser"));
        assert!(SETUP_STANDALONE_TOOL_PROVIDER_OPTIONS[6].contains("Skip"));
        assert!(SETUP_STANDALONE_TOOL_PROVIDER_CONTROLS.contains("ENTER/SPACE select"));
    }

    #[test]
    fn standalone_tool_provider_down_moves_cursor_without_changing_selection() {
        let mut setup = StandaloneSetupState::default();
        setup.handle_key(Key::Down);
        setup.handle_key(Key::Enter);
        setup.handle_key(Key::Ctrl('c'));
        setup.handle_key(Key::Enter);
        setup.handle_key(Key::Ctrl('c'));
        setup.handle_key(Key::Escape);
        assert_eq!(
            setup.handle_key(Key::Ctrl('c')),
            StandaloneSetupAction::EnteredToolProviderBoundary
        );
        assert_eq!(setup.provider_cursor(), SETUP_STANDALONE_TOOL_PROVIDER_DEFAULT_INDEX);
        assert_eq!(setup.handle_key(Key::Down), StandaloneSetupAction::Moved);
        assert_eq!(setup.provider_cursor(), 1);
        assert_eq!(SETUP_STANDALONE_TOOL_PROVIDER_DEFAULT_INDEX, 0);
        assert!(setup.is_tool_provider_boundary());
        assert_eq!(setup.handle_key(Key::Enter), StandaloneSetupAction::Continue);
        assert_eq!(setup.provider_action(), None);
        assert_eq!(setup.provider_cursor(), 1);
    }

    #[test]
    fn standalone_tool_provider_safe_actions_are_typed_without_provider_side_effects() {
        let provider_boundary = || {
            let mut setup = StandaloneSetupState::default();
            setup.handle_key(Key::Down);
            setup.handle_key(Key::Enter);
            setup.handle_key(Key::Ctrl('c'));
            setup.handle_key(Key::Enter);
            setup.handle_key(Key::Ctrl('c'));
            setup.handle_key(Key::Escape);
            assert_eq!(
                setup.handle_key(Key::Ctrl('c')),
                StandaloneSetupAction::EnteredToolProviderBoundary
            );
            setup
        };

        let mut local_enter = provider_boundary();
        assert_eq!(local_enter.handle_key(Key::Enter), StandaloneSetupAction::SelectedLocalBrowser);
        assert_eq!(
            local_enter.provider_action(),
            Some(StandaloneToolProviderAction::LocalBrowserSelected)
        );
        assert_eq!(local_enter.selected(), SETUP_STANDALONE_TOOL_PROVIDER_DEFAULT_INDEX);

        let mut local_space = provider_boundary();
        assert_eq!(
            local_space.handle_key(Key::Char(' ')),
            StandaloneSetupAction::SelectedLocalBrowser
        );
        assert_eq!(
            local_space.provider_action(),
            Some(StandaloneToolProviderAction::LocalBrowserSelected)
        );

        let mut skip = provider_boundary();
        for _ in 0..SETUP_STANDALONE_TOOL_PROVIDER_OPTIONS.len() - 1 {
            assert_eq!(skip.handle_key(Key::Down), StandaloneSetupAction::Moved);
        }
        assert_eq!(skip.provider_cursor(), SETUP_STANDALONE_TOOL_PROVIDER_OPTIONS.len() - 1);
        assert_eq!(skip.handle_key(Key::Enter), StandaloneSetupAction::SkippedToolProvider);
        assert_eq!(skip.provider_action(), Some(StandaloneToolProviderAction::Skipped));

        let mut cancelled = provider_boundary();
        assert_eq!(cancelled.handle_key(Key::Escape), StandaloneSetupAction::CancelledToolProvider);
        assert_eq!(cancelled.provider_action(), Some(StandaloneToolProviderAction::Cancelled));
    }

    #[test]
    fn standalone_tool_provider_cursor_wraps_without_selecting_a_provider() {
        let mut setup = StandaloneSetupState::default();
        setup.handle_key(Key::Down);
        setup.handle_key(Key::Enter);
        setup.handle_key(Key::Ctrl('c'));
        setup.handle_key(Key::Enter);
        setup.handle_key(Key::Ctrl('c'));
        setup.handle_key(Key::Escape);
        assert_eq!(
            setup.handle_key(Key::Ctrl('c')),
            StandaloneSetupAction::EnteredToolProviderBoundary
        );

        assert_eq!(setup.provider_cursor(), 0);
        assert_eq!(setup.selected(), 0);
        assert_eq!(setup.handle_key(Key::Up), StandaloneSetupAction::Moved);
        assert_eq!(setup.provider_cursor(), 6);
        assert_eq!(setup.selected(), 0);
        assert_eq!(setup.handle_key(Key::Down), StandaloneSetupAction::Moved);
        assert_eq!(setup.provider_cursor(), 0);

        for expected_cursor in 1..=6 {
            assert_eq!(setup.handle_key(Key::Down), StandaloneSetupAction::Moved);
            assert_eq!(setup.provider_cursor(), expected_cursor);
        }
        assert_eq!(setup.handle_key(Key::Down), StandaloneSetupAction::Moved);
        assert_eq!(setup.provider_cursor(), 0);

        assert_eq!(setup.handle_key(Key::Down), StandaloneSetupAction::Moved);
        assert_eq!(setup.provider_cursor(), 1);
        assert_eq!(setup.handle_key(Key::Up), StandaloneSetupAction::Moved);
        assert_eq!(setup.provider_cursor(), 0);
        assert_eq!(setup.selected(), 0);
        assert!(setup.is_tool_provider_boundary());
    }

    #[test]
    fn standalone_setup_escape_keeps_the_initial_numbered_fallback_contract() {
        let mut setup = StandaloneSetupState::default();

        assert_eq!(setup.handle_key(Key::Escape), StandaloneSetupAction::EnteredFallback);
        assert!(setup.is_numbered_fallback());
        assert!(!setup.terminal_backend_fallback());
        assert_eq!(setup.handle_key(Key::Ctrl('c')), StandaloneSetupAction::Quit);
    }
}
