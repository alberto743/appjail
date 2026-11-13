# The window

```sh
sudo apt install python3-tk     # once
appjail-gui
appjail-gui --desktop           # add appjail to your application menu (--remove-desktop takes it out)
```

The window has four tabs: **Apps** (run, run with extra access for one run, open a file, update, permissions, portals,
history, menu entry and file types, remove), **Add** (from GitHub, a URL or a file, with every permission option; options
that do not apply to the chosen source are greyed out), **Search** (results from the catalogs, and "Add this app…" to
copy a hit into the Add form), and **Tools** (helpers, version, the history of all apps).

It runs the same commands as the terminal and shows their output in one pane. Every question a command asks appears as
a dialog, with the facts the command printed just before it, and the same default answer: No, except when writing a
menu entry you asked for. The window never answers for you. Apps started from it run in their own session, so closing
the window does not close them.
