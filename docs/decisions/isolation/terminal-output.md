# An app's terminal output is cleaned unless granted

*Decision on [isolation](index.md).*

**Context.** An app started with `appjail run` shared the terminal: its output went straight to it. A terminal obeys
control sequences, and some of them set the clipboard or the window title, rewrite earlier lines or make the terminal
type a reply into your input. The jail already stops the app from pushing keystrokes (`TIOCSTI`, a session of its own),
but not from printing. Measured in the test guest: an app that printed an OSC 52 clipboard write, a title change, a
screen clear and two queries reached the terminal in full, and the terminal's replies were waiting in the input after the
app had exited.

**Options.** Leave it documented; give windowed apps no input and write their output to a log; clean the output of every
run; make the cleaning a default that a permission turns off; a pseudo-terminal of the app's own with a filter on its
bytes.

**Decision.** A permission `raw_terminal`, off by default, and `appjail run --raw` for one run. Unless granted, when the
app's standard output or error is a terminal, appjail gives the app no input (if its input is a terminal), reads the
output through a pipe in pieces of 64 KiB and writes it to the terminal with every escape sequence and control
character removed (`termfilter.py`, `textsafe.clean_output`). Redirected output, menu launches and the window's runs are
not terminals and are left alone. With the permission, the app has the terminal as before, and gets `TERM` from your
environment (when it is a plausible terminal name) and the terminfo directories of the host's `/usr`.

- **A terminal is the trigger, not a window.** `display` is `wayland` unless chosen otherwise, so "has a window" does not
  tell a graphical app from a command-line one, and `none` is never inferred.
- **A permission, not an option only.** Nothing is granted by default ([principles](../../understand/principles.md)): the
  terminal is one more thing an app can reach. It warns when granted, shows in `perms` and the history like the others, and
  the window shows it as a check box. `--raw` lets you try an app once without recording anything.
- **No log file.** It needs a place, a size limit, a rotation and a command to read it, and it takes away the documented
  way of finding what an app needs by reading what it prints.
- **A line is the unit,** with a cap, because a program can print without ever ending a line: reading line by line used
  to need about 400 MiB of memory for 200 MB of output.

**Rejected.** Cleaning only the apps with a window (it would also catch command-line apps installed with the default
display and spare windowed ones started from a terminal); a log file (above); no permission, always cleaning (it breaks
terminal apps with no way out); a pseudo-terminal with a filter that keeps colours and drawing (see
[deferred work](../deferred.md)).

**Consequences.** A terminal app, or a command-line tool that asks questions, needs `raw_terminal` or `--raw`. Colours
and progress bars that depend on a terminal are lost, and output can arrive late because a pipe is buffered. appjail
says after the run that sequences were removed, and how to give the terminal. An app with a window behaves as before.
