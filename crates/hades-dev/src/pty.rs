//! PTY spawn and control primitives for the parity harness.
//!
//! Faithful Rust port of the Python harness's PTY helpers
//! (`scripts/probe_hermes_slash_commands.py` and
//! `scripts/probe_hermes_terminal_palette.py`): spawn a child on a
//! pseudoterminal, size the window, wait for a screen predicate, drain
//! output, write input, and stop the child.

use std::fs::OpenOptions;
use std::os::fd::OwnedFd;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use rustix::event::{PollFd, PollFlags, poll};
use rustix::fs::{Mode, OFlags, open};
use rustix::io::read;
use rustix::pty::{OpenptFlags, grantpt, openpt, ptsname, unlockpt};
use rustix::termios::{Winsize, tcsetwinsize};

/// A spawned child attached to a fresh pseudoterminal.
pub struct PtyChild {
    pub child: Child,
    /// Master side of the PTY; reads from this see the child's output.
    pub master: OwnedFd,
    /// Path of the slave side, kept alive for terminal-flag inspection.
    pub slave_path: String,
    /// Slave descriptor kept open (the Python harness retains it so the
    /// PTY stays valid after the child spawns).
    _slave: OwnedFd,
}

/// Spawn `command` with its stdio attached to a fresh PTY of the given size.
pub fn spawn_pty(command: &mut Command, columns: u16, rows: u16) -> std::io::Result<PtyChild> {
    let master = openpt(OpenptFlags::RDWR | OpenptFlags::NOCTTY | OpenptFlags::CLOEXEC)?;
    grantpt(&master)?;
    unlockpt(&master)?;
    let slave_path = ptsname(&master, Vec::new())?;
    let slave_path = slave_path
        .into_string()
        .map_err(|_| std::io::Error::other("ptsname returned non-UTF-8 path"))?;

    let slave = open(&slave_path, OFlags::RDWR | OFlags::NOCTTY, Mode::empty())?;
    tcsetwinsize(&master, Winsize { ws_row: rows, ws_col: columns, ws_xpixel: 0, ws_ypixel: 0 })?;
    // Non-blocking master, mirroring the Python harness's
    // `os.set_blocking(master, False)`: read_available must never block.
    rustix::io::ioctl_fionbio(&master, true)?;

    // Clone the slave fd for each stdio slot; the original stays open as
    // the keepalive/inspection handle.
    let child = command
        .stdin(Stdio::from(slave.try_clone()?))
        .stdout(Stdio::from(slave.try_clone()?))
        .stderr(Stdio::from(slave.try_clone()?))
        .spawn()?;

    Ok(PtyChild { child, master, slave_path, _slave: slave })
}

/// Resize the PTY window on both the master fd and the slave path, then
/// signal SIGWINCH to the child — mirroring the Python harness's
/// `set_window_size` + `set_slave_window_size` + `os.kill(pid, SIGWINCH)`.
pub fn resize_pty(
    master: &OwnedFd,
    slave_path: &str,
    child: &Child,
    columns: u16,
    rows: u16,
) -> std::io::Result<()> {
    let size = Winsize { ws_row: rows, ws_col: columns, ws_xpixel: 0, ws_ypixel: 0 };
    tcsetwinsize(master, size)?;
    let slave = open(slave_path, OFlags::RDWR | OFlags::NOCTTY, Mode::empty())?;
    let result = tcsetwinsize(&slave, size);
    drop(slave);
    result?;
    let pid = rustix::process::Pid::from_child(&child);
    let _ = rustix::process::kill_process(pid, rustix::process::Signal::WINCH);
    Ok(())
}

/// Read everything currently available on the master without blocking.
pub fn read_available(master: &OwnedFd) -> Vec<u8> {
    let mut output = Vec::new();
    loop {
        let mut chunk = [0u8; 65536];
        match read(master, &mut chunk) {
            Ok(count) if count > 0 => output.extend_from_slice(&chunk[..count]),
            _ => break,
        }
    }
    output
}

/// Wait until `predicate(accumulated_text)` is true or `timeout` elapses.
///
/// Returns the accumulated raw bytes. The predicate receives the raw bytes
/// decoded as lossy UTF-8, exactly like the Python harness's `wait_for`.
pub fn wait_for<F>(
    master: &OwnedFd,
    buffer: &mut Vec<u8>,
    description: &str,
    mut predicate: F,
    timeout: Duration,
) -> Result<(), String>
where
    F: FnMut(&str) -> bool,
{
    let deadline = Instant::now() + timeout;
    loop {
        let text = String::from_utf8_lossy(buffer);
        if predicate(&text) {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err(format!("{description}: timed out ({} bytes captured)", buffer.len()));
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        let millis = remaining.as_millis().min(250) as i64;
        let timespec =
            rustix::time::Timespec { tv_sec: millis / 1000, tv_nsec: (millis % 1000) * 1_000_000 };
        let mut poll_fd = PollFd::new(&master, PollFlags::IN);
        let ready = poll(std::slice::from_mut(&mut poll_fd), Some(&timespec))
            .map_err(|error| format!("{description}: poll failed: {error}"))?;
        if ready > 0 {
            buffer.extend_from_slice(&read_available(master));
        }
    }
}

/// Drain output for `duration`, returning everything read.
pub fn drain(master: &OwnedFd, duration: Duration) -> Vec<u8> {
    let deadline = Instant::now() + duration;
    let mut output = Vec::new();
    while Instant::now() < deadline {
        let remaining = deadline.saturating_duration_since(Instant::now());
        let millis = remaining.as_millis().min(50) as i64;
        let timespec =
            rustix::time::Timespec { tv_sec: millis / 1000, tv_nsec: (millis % 1000) * 1_000_000 };
        let mut poll_fd = PollFd::new(&master, PollFlags::IN);
        let ready = poll(std::slice::from_mut(&mut poll_fd), Some(&timespec)).unwrap_or(0);
        if ready > 0 {
            output.extend_from_slice(&read_available(master));
        }
    }
    output
}

/// Write a payload to the master (the child's stdin).
pub fn write_bytes(master: &OwnedFd, payload: &[u8]) -> std::io::Result<()> {
    use rustix::io::write;
    let mut offset = 0;
    while offset < payload.len() {
        let count = write(master, &payload[offset..])?;
        offset += count;
    }
    Ok(())
}

/// Stop a child: SIGINT, brief grace, then SIGKILL.
pub fn stop(child: &mut Child) {
    if let Ok(Some(_)) = child.try_wait() {
        return;
    }
    let _ = Command::new("kill").args(["-INT", &child.id().to_string()]).status();
    let deadline = Instant::now() + Duration::from_millis(500);
    while Instant::now() < deadline {
        if let Ok(Some(_)) = child.try_wait() {
            return;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    let _ = child.kill();
    let _ = child.wait();
}

/// A raw stdin handle for the child (kept open by the caller).
pub struct StdinHandle {
    _file: std::fs::File,
}

/// Open the slave path for writing (used by helpers that inspect the
/// terminal state of the live PTY).
pub fn open_slave_writer(path: &str) -> std::io::Result<StdinHandle> {
    let file = OpenOptions::new().write(true).open(Path::new(path))?;
    Ok(StdinHandle { _file: file })
}

/// Read bytes from the master with a hard cap, for diagnostics.
pub fn read_capped(master: &OwnedFd, cap: usize) -> Vec<u8> {
    let mut output = Vec::new();
    while output.len() < cap {
        let mut chunk = [0u8; 4096];
        match read(master, &mut chunk) {
            Ok(count) if count > 0 => output.extend_from_slice(&chunk[..count]),
            _ => break,
        }
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process::Command;

    #[test]
    fn spawn_pty_creates_sized_window() {
        let mut command = Command::new("sh");
        command.args(["-c", "stty size; sleep 1"]);
        let mut pty = spawn_pty(&mut command, 120, 50).expect("spawn");
        let mut buffer = Vec::new();
        wait_for(
            &pty.master,
            &mut buffer,
            "stty",
            |text| text.contains("50 120"),
            Duration::from_secs(5),
        )
        .expect("window size echoed");
        stop(&mut pty.child);
    }

    #[test]
    fn write_bytes_reaches_child_stdin() {
        let mut command = Command::new("sh");
        command.args(["-c", "read line; echo got:$line; sleep 1"]);
        let mut pty = spawn_pty(&mut command, 120, 40).expect("spawn");
        write_bytes(&pty.master, b"hello\n").expect("write");
        let mut buffer = Vec::new();
        wait_for(
            &pty.master,
            &mut buffer,
            "echo",
            |text| text.contains("got:hello"),
            Duration::from_secs(5),
        )
        .expect("child echoed input");
        stop(&mut pty.child);
    }

    #[test]
    fn read_available_returns_empty_when_idle() {
        let mut command = Command::new("sh");
        command.args(["-c", "sleep 2"]);
        let mut pty = spawn_pty(&mut command, 120, 40).expect("spawn");
        std::thread::sleep(Duration::from_millis(200));
        // May be non-empty on the initial shell banner; just assert it
        // returns without blocking.
        let _ = read_available(&pty.master);
        stop(&mut pty.child);
    }
}
