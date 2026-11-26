# The window

```sh
sudo apt install python3-tk     # once (Fedora: sudo dnf install python3-tkinter)
appjail-gui
appjail-gui --desktop           # add appjail to your application menu (--remove-desktop takes it out)
```

The window has four tabs: **Apps** (run, run with extra access for one run, open a file, update, permissions and
environment variables, portals, history, menu entry and file types, reset the app's private home, remove), **Add** (from
GitHub, a URL or a file, with every permission option and limit; options that do not apply to the chosen source are
greyed out), **Search** (results from the catalogs, and "Add this app…" to copy a hit into the Add form), and **Tools** (helpers,
version, the history of all apps).

It runs the same commands as the terminal and shows their output in one pane. Every question a command asks appears as
a dialog, with the facts the command printed just before it, and the same default answer: No, except when writing a
menu entry you asked for. The window never answers for you. Apps started from it run in their own session, so closing
the window does not close them.
Every command-line option has a place in the window, except the few that make no sense there (`--yes`, because the
command asks and you answer; `--json`; `run --raw`). **Open file…** asks whether the app may change the file, with the
file bound alone into the jail and read-only unless you tick the box. Following redirects to private addresses (the LAN and
loopback, refused by default) is a check box on the Add tab (URL sources), in the update dialog and under Catalogs, each
with its warning; the asset pattern of a GitHub app is a field of the update dialog, and the appjail-db commit a field
under Catalogs.

An app started from the window has no terminal: its output is shown in the pane with the control sequences removed, so
`raw_terminal` (your terminal as it is, for `appjail run` in a terminal) changes nothing there.

The privileged portals are one check box each, with what the portal lets the app do beside it, in the **Add** tab and in
the permissions editor (they need the `portals` permission). Checking one builds the same `--portal`, `--add-portal` or
`--rm-portal` option as in the terminal, and the command still shows what changes and asks. D-Bus names stay free text.
