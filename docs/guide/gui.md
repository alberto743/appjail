# The window

```sh
sudo apt install python3-tk     # once (Fedora: sudo dnf install python3-tkinter)
appjail-gui
appjail-gui --desktop           # add appjail to your application menu (--remove-desktop takes it out)
```

The sidebar has four pages. **Apps** lists the installed apps with their icons; type in the filter box above the list
(**Ctrl+F**) to show only the apps whose name or source contains the text. The pane beside the list shows the selected
app's version, source, evidence tier and grants, with its actions in groups: run, run with extra access for one run and
open a file; permissions and environment variables, and portals; the menu entry and its file types; updates and
history; reset the app's private home and remove it. Double-click an app (or press Return) to run it. **Add** installs
from GitHub, a URL or a file, with every permission option and limit; options that do not apply to the chosen source are
greyed out, and the directories, D-Bus names, portals and URL schemes are one list at a time, each showing how many
entries it has. **Search** shows results from the catalogs, and "Add this app…" copies a hit into the Add form.
**Tools** has the helpers, the version and the history of all apps.
The window follows the desktop's dark or light preference (read from the Settings portal when it starts); the **Dark**
switch at the bottom of the sidebar changes it until you close the window. An app's icon is the one its menu entry
installed; an app without a menu entry shows a coloured square. The window works on screens down to 800x600: where it
is short, the Add form and the app's detail pane scroll (the Add… button stays in view), and where it is narrow, rows
of buttons wrap. The **Catalogs** card on the Search page opens when you click its title. Files and folders are chosen
in the window's own chooser (places on the left, folders first, AppImages only unless you pick "All files", **Hidden
files** to show dot files), and its messages use the same look. Searching the catalogs and reading an app's portal
grants happen in the background: the window stays responsive, and a newer search replaces one still running.

It runs the same commands as the terminal and shows their output in the output pane, which opens when a command runs
(**Show output** and **Hide output** in the status bar), with errors, warnings and notes in their own colours. Every
question a command asks appears as a dialog, with the facts the command printed just before it, and the same default
answer: No, except when writing a menu entry you asked for. The window never answers for you. Apps started from it run
in their own session, so closing the window does not close them. Every command-line option has a place in the window,
except the few that make no sense there (`--yes`, because the command asks and you answer; `--json`; `run --raw`).
**Open file…** asks whether the app may change the file, with the file bound alone into the jail and read-only unless
you tick the box. Following redirects to private addresses (the LAN and loopback, refused by default) is a check box on
the Add page (URL sources), in the update dialog and under Catalogs, each with its warning; the asset pattern of a
GitHub app is a field of the update dialog, and the appjail-db commit a field under Catalogs.

An app started from the window has no terminal: its output is shown in the pane with the control sequences removed, so
`raw_terminal` (your terminal as it is, for `appjail run` in a terminal) changes nothing there.

The privileged portals are one check box each, with what the portal lets the app do beside it, on the **Add** page and
in the permissions editor (they need the `portals` permission). Checking one builds the same `--portal`, `--add-portal`
or `--rm-portal` option as in the terminal, and the command still shows what changes and asks. D-Bus names stay free
text.
