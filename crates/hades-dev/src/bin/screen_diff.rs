//! Diagnostic driver for the screen-emulator differential check: reads raw
//! bytes from stdin, feeds them through `hades_dev::screen::Screen`, and
//! prints the resulting lines, inventory, and marker styles as JSON.

use std::io::{Read, Write};

use hades_dev::screen::Screen;
use serde_json::json;

fn main() {
    let mut raw = Vec::new();
    std::io::stdin().read_to_end(&mut raw).expect("read stdin");

    let mut screen = Screen::new(120, 50);
    screen.feed(&raw);

    let mut markers = serde_json::Map::new();
    for marker in ["Hades Agent", "Available Tools", "ready"] {
        if let Some((row, column, style)) = screen.marker_style(marker) {
            markers.insert(
                marker.to_owned(),
                json!({"row": row, "column": column, "style": style.as_dict()}),
            );
        }
    }

    let report = json!({
        "lines": screen.lines(),
        "inventory": screen.inventory(),
        "markers": markers,
    });
    let mut stdout = std::io::stdout();
    stdout
        .write_all(serde_json::to_string_pretty(&report).unwrap().as_bytes())
        .expect("write report");
    stdout.flush().expect("flush");
}
