# vtterm keys

What `vtterm.keys.key_bytes` returns for each key. Key codes are the
SDL-style codes of OmniPython's `keys` module, and letters and symbols follow
a US layout.

| Key | Bytes |
|---|---|
| A letter, digit or symbol | The character; Shift and Caps Lock as on a US keyboard |
| Ctrl + a letter | The control code: Ctrl-A is `\x01`, Ctrl-C is `\x03` |
| Ctrl + Space, Ctrl + 2 | `\x00` |
| Ctrl + `[`, `\`, `]` | `\x1b`, `\x1c`, `\x1d` |
| Alt + a key | `ESC` and the key's bytes |
| Enter, keypad Enter | `\r` |
| Backspace | `\x7f` |
| Tab | `\t` |
| Escape | `\x1b` |
| Delete | `ESC [ 3 ~` |
| Insert | `ESC [ 2 ~` |
| Home, End | `ESC [ H`, `ESC [ F` |
| Page Up, Page Down | `ESC [ 5 ~`, `ESC [ 6 ~` |
| F1 to F4 | `ESC O P` to `ESC O S` |
| Up, Down, Right, Left | `ESC [ A` to `ESC [ D`; `ESC O A` to `ESC O D` with application cursor keys |

Other keys return `None`, and so does Ctrl with a key not listed.
