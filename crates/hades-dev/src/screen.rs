//! ANSI terminal screen emulation for the parity harness.
//!
//! This is a faithful Rust port of the `Screen`/`Style`/`Cell` model from the
//! Python probe harness (`scripts/probe_hermes_terminal_palette.py`), which
//! every reference probe and replay uses to interpret raw PTY output. The
//! semantics — escape handling, SGR parsing, cursor motion, erase modes, and
//! style naming — are identical so that reports produced through the Rust
//! harness match the Python harness's contract byte-for-byte.

use std::collections::BTreeMap;

/// Terminal style as rendered by SGR sequences.
///
/// Color naming follows the Python harness: `ansi(n)` for the 16 standard
/// colors, `indexed(n)` for 256-color mode, `rgb(r,g,b)` for truecolor, and
/// `default` when unset.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Style {
    pub fg: String,
    pub bg: String,
    pub bold: bool,
    pub dim: bool,
    pub italic: bool,
    pub underline: bool,
    pub reverse: bool,
    pub strike: bool,
}

impl Style {
    pub fn new() -> Self {
        Self {
            fg: "default".to_owned(),
            bg: "default".to_owned(),
            bold: false,
            dim: false,
            italic: false,
            underline: false,
            reverse: false,
            strike: false,
        }
    }

    pub fn as_dict(&self) -> serde_json::Value {
        serde_json::json!({
            "fg": self.fg,
            "bg": self.bg,
            "bold": self.bold,
            "dim": self.dim,
            "italic": self.italic,
            "underline": self.underline,
            "reverse": self.reverse,
            "strike": self.strike,
        })
    }
}

impl Default for Style {
    fn default() -> Self {
        Self::new()
    }
}

/// One terminal cell: a character and the style it was written with.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Cell {
    pub char: String,
    pub style: Style,
}

impl Cell {
    pub fn new() -> Self {
        Self { char: " ".to_owned(), style: Style::new() }
    }
}

impl Default for Cell {
    fn default() -> Self {
        Self::new()
    }
}

fn color_name(value: i64, _foreground: bool) -> String {
    if (30..=37).contains(&value) {
        return format!("ansi({})", value - 30);
    }
    if (40..=47).contains(&value) {
        return format!("ansi({})", value - 40);
    }
    if (90..=97).contains(&value) {
        return format!("ansi({})", value - 90 + 8);
    }
    if (100..=107).contains(&value) {
        return format!("ansi({})", value - 100 + 8);
    }
    "default".to_owned()
}

fn extended_color(values: &[i64], index: usize) -> (String, usize) {
    let Some(mode) = values.get(index) else {
        return ("default".to_owned(), index);
    };
    match mode {
        5 if index + 1 < values.len() => (format!("indexed({})", values[index + 1]), index + 2),
        2 if index + 3 < values.len() => (
            format!("rgb({},{},{})", values[index + 1], values[index + 2], values[index + 3]),
            index + 4,
        ),
        _ => ("default".to_owned(), index + 1),
    }
}

/// Apply an SGR parameter list to a style, returning the new style.
///
/// Semantics mirror `apply_sgr` in the Python harness: an empty parameter
/// list resets; unknown parameters are ignored; extended colors consume
/// their sub-parameters.
pub fn apply_sgr(style: &Style, params: &[i64]) -> Style {
    let mut values = params.to_vec();
    if values.is_empty() {
        values.push(0);
    }
    let mut current = style.clone();
    let mut index = 0;
    while index < values.len() {
        let value = values[index];
        index += 1;
        match value {
            0 => current = Style::new(),
            1 => current.bold = true,
            2 => current.dim = true,
            3 => current.italic = true,
            4 => current.underline = true,
            7 => current.reverse = true,
            9 => current.strike = true,
            22 => {
                current.bold = false;
                current.dim = false;
            }
            23 => current.italic = false,
            24 => current.underline = false,
            27 => current.reverse = false,
            29 => current.strike = false,
            39 => current.fg = "default".to_owned(),
            49 => current.bg = "default".to_owned(),
            30..=37 | 90..=97 => current.fg = color_name(value, true).to_owned(),
            40..=47 | 100..=107 => current.bg = color_name(value, false).to_owned(),
            38 => {
                let (color, next) = extended_color(&values, index);
                current.fg = color;
                index = next;
            }
            48 => {
                let (color, next) = extended_color(&values, index);
                current.bg = color;
                index = next;
            }
            _ => {}
        }
    }
    current
}

/// Saved cursor state for the `s`/`u` CSI sequences.
#[derive(Clone, Debug)]
struct SavedCursor {
    x: usize,
    y: usize,
    style: Style,
}

/// A small terminal model for the ANSI screen state used by the harness.
///
/// `feed` consumes raw bytes (as UTF-8 with replacement, exactly like the
/// Python harness) and updates the cell grid.
#[derive(Clone, Debug)]
pub struct Screen {
    pub columns: usize,
    pub rows: usize,
    cells: Vec<Vec<Cell>>,
    x: usize,
    y: usize,
    style: Style,
    saved_cursor: SavedCursor,
}

impl Screen {
    pub fn new(columns: usize, rows: usize) -> Self {
        Self {
            columns,
            rows,
            cells: vec![vec![Cell::new(); columns]; rows],
            x: 0,
            y: 0,
            style: Style::new(),
            saved_cursor: SavedCursor { x: 0, y: 0, style: Style::new() },
        }
    }

    fn clear(&mut self) {
        self.cells = vec![vec![Cell::new(); self.columns]; self.rows];
    }

    fn erase_line(&mut self, mode: i64) {
        let (start, end) = match mode {
            1 => (0, self.columns.min(self.x + 1)),
            2 => (0, self.columns),
            _ => (self.columns.min(self.x), self.columns),
        };
        for column in start..end {
            self.cells[self.y][column] = Cell::new();
        }
    }

    fn erase_display(&mut self, mode: i64) {
        match mode {
            2 | 3 => self.clear(),
            1 => {
                for row in 0..self.y {
                    self.cells[row] = vec![Cell::new(); self.columns];
                }
                self.erase_line(1);
            }
            _ => {
                for row in (self.y + 1)..self.rows {
                    self.cells[row] = vec![Cell::new(); self.columns];
                }
                self.erase_line(0);
            }
        }
    }

    fn put(&mut self, char: &str) {
        if self.x >= self.columns {
            self.x = 0;
            self.y = (self.rows - 1).min(self.y + 1);
        }
        if self.y < self.rows {
            self.cells[self.y][self.x] = Cell { char: char.to_owned(), style: self.style.clone() };
        }
        let width =
            if char.chars().next().is_some_and(|c| matches!(unicode_width(c), 2)) { 2 } else { 1 };
        self.x = self.columns.min(self.x + width);
    }

    fn csi(&mut self, body: &str, final_char: char) {
        let private = body.starts_with(['?', '>', '!']);
        let raw = if private { &body[1..] } else { body };
        let params: Vec<i64> = if raw.is_empty() {
            Vec::new()
        } else {
            raw.split(';').map(|value| value.parse::<i64>().unwrap_or(0)).collect()
        };
        let first = *params.first().unwrap_or(&1);
        match final_char {
            'm' => {
                let new_style = apply_sgr(&self.style, &params);
                self.style = new_style;
            }
            'H' | 'f' => {
                let row = params.first().copied().unwrap_or(1);
                let col = params.get(1).copied().unwrap_or(1);
                self.y = (0i64.max(row - 1)) as usize;
                self.y = self.y.min(self.rows - 1);
                self.x = (0i64.max(col - 1)) as usize;
                self.x = self.x.min(self.columns - 1);
            }
            'A' => self.y = self.y.saturating_sub(first as usize),
            'B' => self.y = (self.rows - 1).min(self.y + first as usize),
            'C' => self.x = self.columns.min(self.x + first as usize),
            'D' => self.x = self.x.saturating_sub(first as usize),
            'E' => {
                self.y = (self.rows - 1).min(self.y + first as usize);
                self.x = 0;
            }
            'F' => {
                self.y = self.y.saturating_sub(first as usize);
                self.x = 0;
            }
            'G' => {
                self.x = 0.max(first - 1) as usize;
                self.x = self.x.min(self.columns - 1);
            }
            'd' => {
                self.y = 0.max(first - 1) as usize;
                self.y = self.y.min(self.rows - 1);
            }
            'J' => self.erase_display(first),
            'K' => self.erase_line(first),
            'X' => {
                let end = self.columns.min(self.x + first as usize);
                for column in self.x..end {
                    self.cells[self.y][column] = Cell::new();
                }
            }
            'P' => {
                let count = (self.columns - self.x).min(first as usize);
                let row = &mut self.cells[self.y];
                let len = row.len();
                // Shift cells left by `count` from the cursor, replacing the
                // vacated tail with blank cells (Cell is not Copy).
                let mut shifted: Vec<Cell> = row[self.x + count..len].to_vec();
                shifted.extend(std::iter::repeat_with(Cell::new).take(count));
                row[self.x..len].clone_from_slice(&shifted);
            }
            '@' => {
                let count = (self.columns - self.x).min(first as usize);
                let row = &mut self.cells[self.y];
                let len = row.len();
                // Shift cells right by `count` from the cursor, blanking the
                // vacated head.
                let mut shifted: Vec<Cell> = row[self.x..len - count].to_vec();
                shifted = std::iter::repeat_with(Cell::new).take(count).chain(shifted).collect();
                row[self.x..len].clone_from_slice(&shifted);
            }
            's' => {
                self.saved_cursor = SavedCursor { x: self.x, y: self.y, style: self.style.clone() };
            }
            'u' => {
                let saved = self.saved_cursor.clone();
                self.x = saved.x;
                self.y = saved.y;
                self.style = saved.style;
            }
            _ => {}
        }
    }

    /// Feed raw terminal bytes into the screen model.
    pub fn feed(&mut self, raw: &[u8]) {
        let text = String::from_utf8_lossy(raw);
        let chars: Vec<char> = text.chars().collect();
        let mut index = 0;
        while index < chars.len() {
            let char = chars[index];
            if char == '\x1b' {
                if index + 1 >= chars.len() {
                    break;
                }
                let next_char = chars[index + 1];
                if next_char == '[' {
                    let mut end = index + 2;
                    while end < chars.len() && !('@'..='~').contains(&chars[end]) {
                        end += 1;
                    }
                    if end >= chars.len() {
                        break;
                    }
                    let body: String = chars[index + 2..end].iter().collect();
                    self.csi(&body, chars[end]);
                    index = end + 1;
                    continue;
                }
                if next_char == ']' {
                    let mut end = index + 2;
                    while end < chars.len() && chars[end] != '\x07' && chars[end] != '\x1b' {
                        end += 1;
                    }
                    if end < chars.len() && chars[end] == '\x1b' && end + 1 < chars.len() {
                        end += 1;
                    }
                    index = chars.len().min(end + 1);
                    continue;
                }
                index += 2;
                continue;
            }
            match char {
                '\r' => {
                    self.x = 0;
                    index += 1;
                    continue;
                }
                '\n' => {
                    self.y = (self.rows - 1).min(self.y + 1);
                    index += 1;
                    continue;
                }
                '\x08' => {
                    self.x = self.x.saturating_sub(1);
                    index += 1;
                    continue;
                }
                '\t' => {
                    self.x = self.columns.min(((self.x / 8) + 1) * 8);
                    index += 1;
                    continue;
                }
                _ => {}
            }
            if char >= '\x20' {
                let s = char.to_string();
                self.put(&s);
            }
            index += 1;
        }
    }

    /// Render the current screen as one string per row.
    pub fn lines(&self) -> Vec<String> {
        self.cells.iter().map(|row| row.iter().map(|cell| cell.char.clone()).collect()).collect()
    }

    /// Find the first occurrence of `marker` (case-insensitive) and return
    /// its 1-based row/column plus the style at that cell.
    pub fn marker_style(&self, marker: &str) -> Option<(usize, usize, Style)> {
        let marker_lower = marker.to_lowercase();
        for (row, line) in self.lines().iter().enumerate() {
            let lower = line.to_lowercase();
            if let Some(byte_index) = lower.find(&marker_lower) {
                // `find` returns a byte index; Python's str.find returns a
                // char index, so convert (rows hold multi-byte braille/CJK).
                let column = line[..byte_index].chars().count();
                return Some((row + 1, column + 1, self.cells[row][column].style.clone()));
            }
        }
        None
    }

    /// Count visible cells per style, sorted by count descending then fg.
    pub fn inventory(&self) -> Vec<serde_json::Value> {
        let mut counts: BTreeMap<Style, usize> = BTreeMap::new();
        for row in &self.cells {
            for cell in row {
                if cell.char != " " {
                    *counts.entry(cell.style.clone()).or_insert(0) += 1;
                }
            }
        }
        let mut entries: Vec<_> = counts.into_iter().collect();
        // Python: sorted(counts.items(), key=lambda item: (-count, fg)).
        entries.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.fg.cmp(&b.0.fg)));
        entries
            .into_iter()
            .map(|(style, count)| {
                serde_json::json!({
                    "style": style.as_dict(),
                    "visible_cell_count": count,
                })
            })
            .collect()
    }
}

/// East Asian Width `W`/`F` ranges, matching Python's
/// `unicodedata.east_asian_width(c) in {"W", "F"}` as used by the harness.
/// Braille (U+2800–U+28FF) is narrow (`N`) and stays width 1.
fn is_east_asian_wide(c: char) -> bool {
    let code = u32::from(c);
    matches!(
        code,
        // Hangul Jamo, CJK radicals/symbols, Hiragana, Katakana,
        // CJK compatibility, unified ideographs, Yi, Hangul syllables,
        // compatibility ideographs, fullwidth forms, and CJK Ext B+.
        0x1100..=0x115F
            | 0x2E80..=0x303E
            | 0x3041..=0x33FF
            | 0x3400..=0x4DBF
            | 0x4E00..=0x9FFF
            | 0xA000..=0xA4CF
            | 0xAC00..=0xD7A3
            | 0xF900..=0xFAFF
            | 0xFE30..=0xFE4F
            | 0xFF00..=0xFF60
            | 0xFFE0..=0xFFE6
            | 0x20000..=0x2FFFD
            | 0x30000..=0x3FFFD
    )
}

/// Cell advance width for a character: 2 for East Asian wide/fullwidth,
/// 1 otherwise (the Python harness's `unicodedata.east_asian_width` rule).
fn unicode_width(c: char) -> u8 {
    if is_east_asian_wide(c) { 2 } else { 1 }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sgr_reset_and_attributes() {
        let mut style = Style::new();
        style = apply_sgr(&style, &[1, 3, 4]);
        assert!(style.bold && style.italic && style.underline);
        style = apply_sgr(&style, &[0]);
        assert_eq!(style, Style::new());
    }

    #[test]
    fn sgr_standard_colors() {
        let mut style = Style::new();
        style = apply_sgr(&style, &[31]);
        assert_eq!(style.fg, "ansi(1)");
        style = apply_sgr(&style, &[44]);
        assert_eq!(style.bg, "ansi(4)");
        style = apply_sgr(&style, &[92]);
        assert_eq!(style.fg, "ansi(10)");
        style = apply_sgr(&style, &[107]);
        assert_eq!(style.bg, "ansi(15)");
    }

    #[test]
    fn sgr_extended_colors() {
        let mut style = Style::new();
        style = apply_sgr(&style, &[38, 5, 220]);
        assert_eq!(style.fg, "indexed(220)");
        style = apply_sgr(&style, &[48, 2, 10, 20, 30]);
        assert_eq!(style.bg, "rgb(10,20,30)");
    }

    #[test]
    fn screen_put_wraps_at_column_boundary() {
        let mut screen = Screen::new(4, 2);
        screen.feed(b"abcdef");
        let lines = screen.lines();
        assert_eq!(lines[0], "abcd");
        assert_eq!(lines[1], "ef  ");
    }

    #[test]
    fn screen_cursor_motion() {
        let mut screen = Screen::new(5, 5);
        screen.feed(b"\x1b[2;2HX");
        let lines = screen.lines();
        assert_eq!(lines[1], " X   ");
    }

    #[test]
    fn screen_erase_modes() {
        let mut screen = Screen::new(5, 3);
        screen.feed(b"abcdefghij");
        screen.feed(b"\x1b[1;1H\x1b[2J");
        assert_eq!(screen.lines(), vec!["     ".to_owned(); 3]);
    }

    #[test]
    fn screen_marker_style_finds_first_occurrence() {
        let mut screen = Screen::new(20, 3);
        screen.feed(b"\x1b[38;5;220mBrand");
        let (row, column, style) = screen.marker_style("brand").unwrap();
        assert_eq!((row, column), (1, 1));
        assert_eq!(style.fg, "indexed(220)");
    }

    #[test]
    fn screen_inventory_counts_visible_cells() {
        let mut screen = Screen::new(20, 3);
        screen.feed(b"\x1b[31mab\x1b[0mcd");
        let inventory = screen.inventory();
        assert_eq!(inventory.len(), 2);
        assert_eq!(inventory[0]["visible_cell_count"], 2);
        assert_eq!(inventory[0]["style"]["fg"], "ansi(1)");
        assert_eq!(inventory[1]["visible_cell_count"], 2);
    }

    #[test]
    fn screen_braille_is_narrow_like_python_harness() {
        let mut screen = Screen::new(10, 2);
        screen.feed("⠁".as_bytes());
        screen.feed(b"x");
        let lines = screen.lines();
        // Braille is East Asian Width "N", so it advances the cursor by one
        // column, matching `unicodedata.east_asian_width` in the Python
        // harness; x lands at column 2 (0-indexed 1).
        assert_eq!(lines[0], "⠁x        ");
    }

    #[test]
    fn screen_east_asian_wide_advances_two_columns() {
        let mut screen = Screen::new(10, 2);
        screen.feed("界".as_bytes());
        screen.feed(b"x");
        let lines = screen.lines();
        // U+754C is East Asian Width "W": advances two columns (second
        // column blank, matching the Python harness), x at column 3.
        assert_eq!(lines[0], "界 x       ");
    }

    #[test]
    fn screen_handles_alternate_screen_and_osc() {
        let mut screen = Screen::new(10, 2);
        screen.feed(b"\x1b[?1049h\x1b]0;title\x07hello");
        let lines = screen.lines();
        assert_eq!(lines[0], "hello     ");
    }
}
