use std::process::Command;

const CLIPBOARD_MAX_BYTES: usize = 4 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct ClipboardCommand {
    program: &'static str,
    args: &'static [&'static str],
}

const POWERSHELL: ClipboardCommand = ClipboardCommand {
    program: "powershell.exe",
    args: &["-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard -Raw"],
};
const WAYLAND: ClipboardCommand =
    ClipboardCommand { program: "wl-paste", args: &["--type", "text"] };
const XCLIP: ClipboardCommand =
    ClipboardCommand { program: "xclip", args: &["-selection", "clipboard", "-out"] };

pub(crate) fn read_usable_text() -> Option<String> {
    let wsl =
        std::env::var_os("WSL_INTEROP").is_some() || std::env::var_os("WSL_DISTRO_NAME").is_some();
    let wayland = std::env::var_os("WAYLAND_DISPLAY").is_some();
    read_usable_text_with(wsl, wayland, run_command)
}

fn read_usable_text_with<F>(wsl: bool, wayland: bool, mut run: F) -> Option<String>
where
    F: FnMut(&ClipboardCommand) -> Result<Vec<u8>, ()>,
{
    let raw = read_raw_text_with(wsl, wayland, &mut run)?;
    if !is_usable_text(&raw) {
        return None;
    }

    Some(strip_trailing_paste_newlines(&raw).to_owned())
}

fn read_raw_text_with<F>(wsl: bool, wayland: bool, mut run: F) -> Option<String>
where
    F: FnMut(&ClipboardCommand) -> Result<Vec<u8>, ()>,
{
    for command in clipboard_commands(wsl, wayland) {
        let Ok(stdout) = run(&command) else {
            continue;
        };
        if stdout.len() > CLIPBOARD_MAX_BYTES {
            continue;
        }

        return Some(String::from_utf8_lossy(&stdout).into_owned());
    }

    None
}

fn clipboard_commands(wsl: bool, wayland: bool) -> Vec<ClipboardCommand> {
    let mut commands = Vec::with_capacity(3);
    if wsl {
        commands.push(POWERSHELL);
    }
    if wayland {
        commands.push(WAYLAND);
    }
    commands.push(XCLIP);
    commands
}

fn run_command(command: &ClipboardCommand) -> Result<Vec<u8>, ()> {
    let output = Command::new(command.program).args(command.args).output().map_err(|_| ())?;
    if output.status.success() { Ok(output.stdout) } else { Err(()) }
}

fn is_usable_text(text: &str) -> bool {
    if text.is_empty() || !text.chars().any(|character| !character.is_whitespace()) {
        return false;
    }
    if text.contains('\0') {
        return false;
    }

    let suspicious = text
        .chars()
        .filter(|character| {
            let code = *character as u32;
            let is_control = code < 0x20 && !matches!(*character, '\n' | '\r' | '\t');
            is_control || *character == '\u{fffd}'
        })
        .count();
    suspicious <= 2.max(text.chars().count() / 50)
}

fn strip_trailing_paste_newlines(text: &str) -> &str {
    if text.chars().any(|character| character != '\n') { text.trim_end_matches('\n') } else { text }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn provider_order_matches_hermes_linux_selection() {
        let names = clipboard_commands(true, true)
            .into_iter()
            .map(|command| command.program)
            .collect::<Vec<_>>();
        assert_eq!(names, ["powershell.exe", "wl-paste", "xclip"]);

        let wayland_names = clipboard_commands(false, true)
            .into_iter()
            .map(|command| command.program)
            .collect::<Vec<_>>();
        assert_eq!(wayland_names, ["wl-paste", "xclip"]);
    }

    #[test]
    fn provider_failure_falls_through_but_success_stops_selection() {
        let mut calls = Vec::new();
        let text = read_raw_text_with(true, true, |command| {
            calls.push(command.program);
            if command.program == "powershell.exe" {
                Err(())
            } else {
                Ok(b"clip-one  \nclip-two\n\n".to_vec())
            }
        });

        assert_eq!(calls, ["powershell.exe", "wl-paste"]);
        assert_eq!(text.as_deref(), Some("clip-one  \nclip-two\n\n"));
    }

    #[test]
    fn usable_text_preserves_internal_content_and_removes_only_trailing_newlines() {
        let text =
            read_usable_text_with(false, false, |_| Ok(b"clip-one  \nclip-two\n\n".to_vec()));
        assert_eq!(text.as_deref(), Some("clip-one  \nclip-two"));
    }

    #[test]
    fn empty_whitespace_and_binary_like_values_are_rejected() {
        assert!(!is_usable_text(""));
        assert!(!is_usable_text(" \t\n"));
        assert!(!is_usable_text("clip\0text"));
        assert!(!is_usable_text("clip\u{1}text\u{2}\u{3}"));
        assert!(is_usable_text("clip\ntext\t"));
    }

    #[test]
    fn newline_only_text_is_not_stripped_into_a_successful_empty_paste() {
        assert_eq!(strip_trailing_paste_newlines("\n\n"), "\n\n");
        assert!(read_usable_text_with(false, false, |_| Ok(b"\n\n".to_vec())).is_none());
    }
}
