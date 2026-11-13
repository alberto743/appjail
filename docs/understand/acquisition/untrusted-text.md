# Untrusted text

*Part of [Acquisition](index.md). Previous: [jailed download and extraction](jailed-steps.md). Next: [the manifest](manifest.md).*

## What it is

Much of what appjail shows you was written by someone else: repository names and descriptions, release names, asset
file names, the name and comment in an AppImage's menu entry, catalog descriptions and notes, server error messages.
This text arrives as data, but a terminal does not display data passively. Bytes such as `ESC [` start **control
sequences** (defined in ECMA-48) that move the cursor, clear the screen, change colours, rename the window, and on some
terminals write to the clipboard or create hyperlinks that show one address and open another. Unicode adds
**bidirectional and invisible characters** that make text display in a different order from the one it is stored in.

## Why it matters

A review is only as good as what it shows. A release name with control sequences can erase the warning printed above
it, or redraw the owner line with another name; a description with bidirectional characters can make a URL read as a
different one; an overly long text can push the important lines out of view. Text that reaches a shell or a menu entry
unescaped can also become a command.

## How appjail uses it

- **One cleaner for every line.** Everything appjail prints goes through `textsafe.clean`: escape and control sequences
  (CSI, OSC, DCS and the rest), C0 and C1 control characters, zero-width and bidirectional characters are removed; tabs
  and newlines become spaces; long texts are cut. The output layer (`Console`) applies it to every line, so a command
  cannot print untrusted text by mistake. The window does the same before putting text in a widget.
- **Strict parsers with limits.** Catalogs, manifests and the GitHub API's answers are parsed against a fixed schema,
  with size limits; an unexpected shape is an error, not a crash or a guess.
- **Nothing becomes a command.** appjail never passes untrusted text to a shell. Menu entries are generated: the app's
  own `.desktop` file contributes only display text, cleaned and capped, and the command is always appjail's own.
- **Names are checked.** App names become directory names, so they must match `[a-z0-9][a-z0-9._-]{0,63}`; a file
  source records only the base name of the file, never a path.

## Connections

- The catalogs `search` reads are the largest body of untrusted text; they get the same treatment.
- Menu entries and icons are data from the AppImage, handled on the desktop's side: Decisions
  [Menu entries are written by appjail](../../decisions/desktop/menu-entries.md) and
  [Icons rewritten, not decoded](../../decisions/desktop/icons.md).
- Decision: [One output vocabulary, errors on stderr](../../decisions/project/output.md).

## Limits

- What appjail prints is cleaned; what an *app* prints is not. An app started from a terminal (`appjail run`) shares that
  terminal for its input and output, as command-line tools must: control sequences it writes reach the terminal, and
  some terminals let them set the window title, create hyperlinks or write to the clipboard. The jail stops it from
  pushing keystrokes into your shell (`TIOCSTI` is refused, and the app runs in a session of its own). Start untrusted
  graphical apps from the menu, or use a terminal that ignores clipboard and title sequences.
- Cleaning removes what changes the display; it does not stop a misleading but plain text, such as a description that
  claims to be something it is not, or a lookalike name. The review shows the facts (account id, age) that such a text
  cannot change.

## References

- Ecma International, [ECMA-48: Control Functions for Coded Character Sets](https://www.ecma-international.org/publications-and-standards/standards/ecma-48/).
- MITRE, [CWE-150: Improper Neutralization of Escape, Meta, or Control Sequences](https://cwe.mitre.org/data/definitions/150.html).
- Unicode Consortium, [UTS #36: Unicode Security Considerations](https://unicode.org/reports/tr36/): bidirectional
  and invisible characters.
- Boucher and Anderson, [Trojan Source](https://trojansource.codes/): bidirectional characters that make text read
  differently from what it is.
