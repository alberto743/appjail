# Untrusted text

*Part of [Acquisition](index.md). Previous: [jailed download and extraction](jailed-steps.md). Next:
[the manifest](manifest.md).*

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
  (CSI, OSC, DCS and the rest, in their 7-bit and C1 forms, with their payload), C0 and C1 control characters,
  zero-width and bidirectional characters, and other invisible or spoofing characters (soft hyphen, fillers, Unicode tag
  characters, variation selectors other than the emoji one) are removed; tabs and newlines become spaces; long texts are
  cut. The output layer (`Console`) applies it to every line and to every prompt (a prompt names an asset or a
  repository from the network), so a command cannot print untrusted text by mistake. The window does the same before
  putting text in a widget.
- **An app's own output is cleaned too, on a terminal.** An app that shares your terminal could send the same sequences.
  When an app's output goes to a terminal and the app does not have `raw_terminal`, appjail gives it no input (a
  terminal answers some sequences by typing into its input), reads its output through a pipe in pieces of 64 KiB,
  removes every escape sequence and control character (`textsafe.clean_output`: tabs and spaces are kept, a carriage
  return ends a line, nothing is cut except that a line without a newline is written out at 64 KiB, so memory stays
  bounded) and writes the lines to your terminal. Standard output and standard error of one terminal share one pipe,
  which keeps their order. When the output is redirected, and for apps started from a menu or the window (which are not
  terminals; the window cleans the lines itself), nothing changes. If sequences were removed, appjail says so after the
  run.
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
- Decision: [An app's terminal output is cleaned unless granted](../../decisions/isolation/terminal-output.md).

## Limits

- An app with `raw_terminal` (or started with `appjail run --raw`) shares your terminal as it is, as command-line and
  terminal apps must: control sequences it writes reach the terminal, and some terminals let them set the window title,
  create hyperlinks or write to the clipboard, or answer by typing into your input; it can also read what you type
  there. The jail stops it from pushing keystrokes into your shell (`TIOCSTI` is refused, and the app runs in a session
  of its own). Grant it only to an app you trust, or use a terminal that ignores clipboard and title sequences.
- Without `raw_terminal`, a terminal app (a full-screen program) does not work: it gets no input, and its drawing is
  cleaned away. What the filter cannot give: colours, because the sequences that make them are removed; output that
  appears as it is written, because a program that writes to a pipe usually buffers it until it exits or fills its
  buffer; output faster than about 30 MB a second, which is slowed down. Binary output to a terminal is not meaningful
  and is cleaned like text.
- When `raw_terminal` is granted, appjail passes the app `TERM` from your environment (when it looks like a terminal
  name) and the terminfo directories of the host's `/usr`, because an app that carries its own curses library often does
  not find them; `[env]` entries of the manifest win. Without the grant the app has no `TERM`.
- Cleaning removes what changes the display; it does not stop a misleading but plain text, such as a description that
  claims to be something it is not, or a lookalike name. The review shows the facts (account id, age) that such a text
  cannot change.

## References

- Ecma International, [ECMA-48: Control Functions for Coded Character
  Sets](https://www.ecma-international.org/publications-and-standards/standards/ecma-48/).
- MITRE,
  [CWE-150: Improper Neutralization of Escape, Meta, or Control Sequences](https://cwe.mitre.org/data/definitions/150.html).
- Unicode Consortium, [UTS #36: Unicode Security Considerations](https://unicode.org/reports/tr36/): bidirectional
  and invisible characters.
- Boucher and Anderson, [Trojan Source](https://trojansource.codes/): bidirectional characters that make text read
  differently from what it is.
