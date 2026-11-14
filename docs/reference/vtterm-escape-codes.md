# vtterm escape codes

What `vtterm.Parser` does with each byte and sequence. `ESC` is `\x1b`, and
`CSI` is `ESC [`. `n` is a number that defaults to 1, and positions count
from 1. Anything not listed is read and ignored, so a program that sends it
doesn't break the screen.

## Controls

| Byte | Name | What it does |
|---|---|---|
| `\x08` | BS | Cursor left one column |
| `\x09` | HT | Cursor to the next tab stop, every 8 columns, or the last column |
| `\x0a`, `\x0b`, `\x0c` | LF, VT, FF | Cursor down one row, scrolling at the bottom of the region |
| `\x0d` | CR | Cursor to column 1 |
| `\x18`, `\x1a` | CAN, SUB | Cancel the sequence in progress |
| `\x07` | BEL | Ignored |

## ESC sequences

| Sequence | What it does |
|---|---|
| `ESC 7`, `ESC 8` | Save and restore the cursor, its pen and origin mode |
| `ESC D` | Index: down one row, scrolling at the bottom |
| `ESC M` | Reverse index: up one row, scrolling at the top |
| `ESC E` | Next line: CR and LF |
| `ESC c` | Reset the terminal |
| `ESC # 8` | Fill the screen with `E`, the VT100 alignment test |
| `ESC (`, `ESC )`, `ESC *`, `ESC +` and a byte | Character set choice, read and ignored |
| `ESC ]`, `ESC P`, `ESC X`, `ESC ^`, `ESC _` | A string (OSC, DCS and the rest), read up to BEL or `ESC \` and ignored |

## CSI sequences

| Sequence | What it does |
|---|---|
| `CSI n A` | Cursor up |
| `CSI n B`, `CSI n e` | Cursor down |
| `CSI n C`, `CSI n a` | Cursor right |
| `CSI n D` | Cursor left |
| `CSI n E`, `CSI n F` | Cursor to column 1, down or up `n` rows |
| `CSI n G`, ``CSI n ` `` | Cursor to column `n` |
| `CSI n d` | Cursor to row `n` |
| `CSI y ; x H`, `CSI y ; x f` | Cursor to row `y`, column `x` |
| `CSI n J` | Erase the display: 0 from the cursor, 1 up to it, 2 all |
| `CSI n K` | Erase the row: 0 from the cursor, 1 up to it, 2 all |
| `CSI n X` | Erase `n` characters from the cursor |
| `CSI n @`, `CSI n P` | Insert or delete `n` characters |
| `CSI n L`, `CSI n M` | Insert or delete `n` rows |
| `CSI n S`, `CSI n T` | Scroll the region up or down `n` rows |
| `CSI top ; bottom r` | Set the scroll region |
| `CSI s`, `CSI u` | Save and restore the cursor |
| `CSI … m` | Colors and styles (below) |
| `CSI 4 h`, `CSI 4 l` | Insert mode on or off |
| `CSI 20 h`, `CSI 20 l` | Newline mode: LF also returns to column 1 |
| `CSI ? 1 h`, `CSI ? 1 l` | Application cursor keys on or off |
| `CSI ? 6 h`, `CSI ? 6 l` | Origin mode: rows count from the top of the region |
| `CSI ? 7 h`, `CSI ? 7 l` | Autowrap on or off |
| `CSI ? 25 h`, `CSI ? 25 l` | Show or hide the cursor |
| `CSI 5 n` | Status report: answers `CSI 0 n` |
| `CSI 6 n` | Cursor position report: answers `CSI y ; x R` |
| `CSI c` | Device attributes: answers `CSI ? 1 ; 2 c`, a VT100 with advanced video |

Answers go to the `answer` function given to `Parser`; a `Terminal` keeps
them for `Terminal.answers()`, and `run` and `Console` send them on.

## Colors and styles

| Code | What it does |
|---|---|
| `0` | Back to the default colors, no styles |
| `1`, `22` | Bold on, off. Bold draws colors 0 to 7 as their bright versions |
| `4`, `24` | Underline on, off |
| `7`, `27` | Reverse on, off |
| `30` to `37`, `39` | Foreground: one of the eight colors, or the default |
| `40` to `47`, `49` | Background: one of the eight colors, or the default |
| `90` to `97`, `100` to `107` | Bright foreground, bright background |
| `38;5;n`, `48;5;n` | Foreground or background: color `n` of 256 |
| `38;2;r;g;b`, `48;2;r;g;b` | 24-bit color, kept as the nearest of the 256 |

## Characters

Printable ASCII is drawn as is. UTF-8 is decoded, and a character the 8-pixel
fonts don't have is drawn as the ASCII that looks most like it (box-drawing
lines become `-`, `|` and `+`) or as `?`.
