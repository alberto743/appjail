# A drawn theme for the window

*Decision on [the project](index.md).*

**Context.** The window used ttk's default theme: grey, square, with every action in one grid of buttons. It looked
older than the desktop around it, and the standard-library rule of [the window](gui.md) still applies: no toolkit or
theme package from PyPI, no image files beyond appjail's own logo.

**Options.** Keep a stock ttk theme and only change the layout; add a theme package (rejected with the toolkits); draw
the theme's images in Python at start-up.

**Decision.** `gui/theme.py` builds a light and a dark palette on ttk's `clam` theme, with rounded buttons, fields,
cards, chips, check boxes, radio buttons and a switch. The images are drawn by `gui/icons.py` with antialiased shapes
and written as small PNGs in memory; nothing is read from disk. The window has a sidebar with one page per area (Apps,
Add, Search, Tools), a detail pane for the selected app with its grants as chips and its actions in groups, and an
output pane that opens when a command runs and colours errors, warnings and notes. It still builds the same command
lines and runs the same CLI.

- **Dark or light** follows the desktop: at start the window reads `color-scheme` from the Settings portal
  (`org.freedesktop.portal.Settings.ReadOne`, with `dbus-send`, a one-second limit) and starts light when it cannot.
  The switch in the sidebar changes it for the session; nothing is saved.
- **App icons** are the ones `desktop` installed, already rewritten by `pngclean` ([icons](../desktop/icons.md)). The
  window decodes that file in Python, scales it and encodes a new PNG; Tk only ever decodes images appjail wrote. The
  decoding runs on a thread, since a large icon takes a moment in Python; an app without an icon gets a stand-in, a
  rounded square in a colour chosen by its name.
- **Small screens.** The window asks for the size of its tallest page. Where the screen is shorter, the Add form scrolls
  and its Add… button stays in view.

**Rejected.** A theme from PyPI, for the standard-library rule. Tk's own decoder for app icons: it would read bytes an
app chose, in the host process, with no limit but the file's.

**Consequences.** The look is the same on every desktop rather than the desktop's own theme. Tk draws a 9-slice image by
tiling its middle and, on X11, blends each tile through the X server, so the images are drawn larger than their corners
need (a small middle made each widget take about 10 ms to draw). Fonts are the first of Inter, Cantarell, Noto Sans,
Ubuntu and DejaVu Sans that is installed, at the size Tk already uses.

**Revisit when** Tk follows the desktop's theme and colour scheme by itself, or the window needs an image appjail cannot
draw.
