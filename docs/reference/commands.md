# Commands

Every command and option of `appjail`, as `appjail COMMAND --help` lists them. Everything after `--` on the command line
belongs to the app (`appjail run lagrange -- --help`). Commands that change or delete something ask first; the answer
defaults to No.

## Installing and removing

### `add`

```
appjail add owner/repo [options]
appjail add --file PATH [options]
appjail add --url URL [options]
```

| Option | Effect |
|---|---|
| `source` | a GitHub `owner/repo` (not with `--file` or `--url`) |
| `--file PATH` | install this local AppImage instead of a GitHub release |
| `--url URL` | install the AppImage at this https URL instead of a GitHub release |
| `--sha256 HEX` | with `--file` or `--url`: the hash the publisher gives; a mismatch aborts, a match makes it tier 4 |
| `--max-size MIB` | with `--url`: refuse to download more than this (default 1024) |
| `--name NAME` | the app's local name (default: from the repository or the file) |
| `--prerelease` | allow pre-releases (the app then follows the `prerelease` channel) |
| `--tag TAG` | install this release instead of the latest; the app is then pinned |
| `--allow PERMISSION` | grant `network`, `network_host`, `audio`, `mic`, `gpu`, `camera`, `portals`, `userns`, `linger` or `full_wayland`; repeatable |
| `--dir PATH[:ro\|:rw]` | let the app see this directory, read-only unless `:rw`; repeatable |
| `--dbus NAME` | let the app talk to this session-bus name through the filtering proxy; repeatable |
| `--dbus-own NAME` | let the app own this session-bus name; repeatable |
| `--portal NAME` | also allow this privileged portal interface (needs `--allow portals`); repeatable |
| `--audio-mode pipewire\|pulse` | with `--allow audio`: the private graph (default) or the host's Pulse socket |
| `--display none\|wayland\|xwayland\|xwayland-rootful` | the display mode (default `wayland`) |
| `--display-size WxH` | with `--display xwayland-rootful`: the size of its window (default 1280x800) |
| `--desktop` | also create a menu entry |
| `--mime TYPE` | with `--desktop`: offer the app for this file type; repeatable |
| `--mime-all` | with `--desktop`: offer every file type the app declares, minus refused ones |
| `--rw` | with `--desktop`: files opened from the menu are writable |

An option that does not apply to the chosen source is refused, never ignored.

### `remove`

`appjail remove APP [--yes]`: delete the app, its private home, its menu entry, and its portal grants and decisions.

## Running

### `run`

`appjail run APP [--dir PATH[:ro|:rw]]... [--file PATH[:ro|:rw]]... [-- ARGS]`

| Option | Effect |
|---|---|
| `--dir PATH[:ro\|:rw]` | grant this directory for this run only; repeatable |
| `--file PATH[:ro\|:rw]` | bind only this file for this run, read-only unless `:rw`, and pass its path in the jail to the app; repeatable. For a file whose name ends in `:rw` or `:ro`, write the mode yourself (`x:rw:ro`) |

### `open`

`appjail open APP [--rw] -- FILE...`: open files with an app, each bound alone into its jail, read-only unless `--rw`.
This is what a menu entry with file types runs. No file means a plain start.

## Inspecting and changing

### `list`

`appjail list [-l|--long] [--json]`: the installed apps with version, source, evidence tier, channel and any update
seen. `-l` adds what each app is granted; `--json` prints one JSON document, permissions included.

### `perms`

`appjail perms APP [options] [--yes]`: without options, show the app's permissions; with options, show them before and
after and ask before saving.

| Option | Effect |
|---|---|
| `--allow PERMISSION`, `--deny PERMISSION` | grant or take back a switch (the same names as `add --allow`) |
| `--audio-mode pipewire\|pulse` | how `audio` and `mic` are provided |
| `--display MODE`, `--display-size WxH` | the display mode and the rootful window size |
| `--add-dir PATH[:ro\|:rw]`, `--rm-dir PATH` | a directory |
| `--add-dbus NAME`, `--rm-dbus NAME` | a session-bus name to talk to |
| `--add-dbus-own NAME`, `--rm-dbus-own NAME` | a session-bus name to own |
| `--add-portal NAME`, `--rm-portal NAME` | an opt-in portal interface |
| `--yes` | do not ask |

### `portals`

`appjail portals APP [--revoke DOC_ID]... [--revoke-all] [--yes]`: list the files the app was given through the document
portal, or revoke one or all of them.

### `history`

`appjail history [APP] [--limit N]`: the recorded changes to the manifests, of all apps or of one.

## Updating

### `update`

`appjail update [APP] [options]`: check one app, or every installed app, for a new version.

| Option | Effect |
|---|---|
| `APP` | one app (default: every installed app) |
| `--prerelease` | consider pre-releases for this run |
| `--channel stable\|prerelease\|pinned` | GitHub apps: which releases the app follows from now on (needs `APP`) |
| `--quarantine DAYS` | days a new release must wait after it was first seen (default 7; 0 = none) |
| `--file PATH` | an app installed from a file: replace it with this AppImage (needs `APP`) |
| `--sha256 HEX` | URL and file apps: the publisher's hash for the new content, which keeps or earns tier 4 (needs `APP`) |
| `--verify` | URL apps: at the end of the quarantine, download the file again and compare it with the candidate |

## Menu entry

### `desktop`

`appjail desktop [APP] [options]`: create or refresh an app's menu entry, or manage the entries.

| Option | Effect |
|---|---|
| `--mime TYPE` | offer the app for this file type; repeatable |
| `--mime-all` | offer every file type the app declares, minus refused ones |
| `--rw` | files opened from the menu are writable (default: read-only) |
| `--show` | show the file types registered, offered by the app and refused; writes nothing |
| `--remove` | delete the app's menu entry and icons |
| `--prune` | delete the entries of apps that no longer exist |
| `--yes` | do not ask (registers no file types unless `--mime` or `--mime-all`) |

## Catalogs and search

### `search`

`appjail search KEYWORD... [--limit N] [--all] [--json]`: suggestions from the local catalogs; never installs.
`--limit` sets the maximum (default 20), `--all` shows every match, `--json` prints one JSON document.

### `index`

| Command | Effect |
|---|---|
| `appjail index add NAME --url URL` or `--file FILE` | add a catalog source (an https URL, or a local file) |
| `appjail index remove NAME` | remove a source you added (`appjail-db` cannot be removed) |
| `appjail index update [NAME] [--commit COMMIT]` | refresh one source or all; `--commit` (40 hex digits, `appjail-db` only) fetches that commit |
| `appjail index rollback [NAME]` | go back to the previous catalog of a source (default `appjail-db`); can itself be rolled back |
| `appjail index status [--json]` | the sources, their revisions, commits and update times |

## Helpers and version

| Command | Effect |
|---|---|
| `appjail tools status` | which pinned helpers are installed and intact |
| `appjail tools install dwarfs\|gh` | download a helper whose size and hash are pinned in appjail's source |
| `appjail version`, `appjail --version` | the installed version |

## The window

| Command | Effect |
|---|---|
| `appjail-gui` | open the window (needs `python3-tk` and a display) |
| `appjail-gui --desktop` | add appjail itself to the application menu |
| `appjail-gui --remove-desktop` | take that entry out again |

## Exit status

0 on success, 1 on an error, a refusal or a cancelled confirmation (and for `update`, when any app was blocked, failed
or not checked), 2 for a usage error, 130 after Ctrl-C.
