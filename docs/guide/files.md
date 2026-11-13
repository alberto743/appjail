# Files and folders

An app sees only its own files and a private home. Nothing of yours is visible to it unless you grant it; how this is
built, and why, is explained in [the filesystem view](../understand/isolation/filesystem.md).

## Where the app's own files are

Each app has a private home that it sees as `/home/app`. On your side it is
`~/.local/share/appjail/apps/NAME/home`. Settings, caches and anything the app saves "in its home" land there and are
kept between runs. `appjail remove NAME` deletes it, after asking.

To give an app a file, you can copy it into that folder; the ways below avoid copies.

## A folder, every time

```sh
appjail perms NAME --add-dir ~/Documents/notes       # read-only
appjail perms NAME --add-dir ~/Documents/notes:rw    # read-write
appjail perms NAME --rm-dir ~/Documents/notes        # take it back
```

A folder in your home appears at the same place under the app's home: `~/Documents/notes` becomes
`/home/app/Documents/notes`. A folder outside your home, such as `/srv/media`, appears at the same path.

## A folder or a file, once

```sh
appjail run NAME --dir ~/Downloads           # this run only, read-only unless :rw
appjail run NAME --file ~/report.pdf         # this file only; its path in the jail is passed to the app
```

`--file` makes only that file visible, not the rest of its folder. Opening a file from the app's menu entry does the
same, read-only unless the entry was created with `--rw`.

Two details of `--file`:

- An app that saves by writing a new file and renaming it over the old one cannot save to a file granted with `:rw`
  (a bound file can be rewritten, not replaced). Grant its folder instead.
- A file whose own name ends in `:rw` or `:ro` needs its mode written out: `run NAME --file 'x:rw:ro'` grants the file
  `x:rw`, read-only.

## What cannot be granted

These are refused in every mode, with a message:

- credentials and secrets: `~/.ssh`, `~/.gnupg`, cloud, container and package-registry credentials, password stores,
  browser profiles, mail, shell histories, files named like keys or password databases, and any folder that contains
  one of these;
- your whole home, any folder above it, `/`, the broad `~/.config`, `~/.local` and `~/.cache`, and system trees such as
  `/etc`, `/usr` or `/dev`;
- `/tmp`, `/var/tmp` and anything below them (other programs' sockets live there; a single regular file there can still
  be opened with `--file`);
- appjail's own data and configuration.

These are refused **read-write** only, because something outside the jail would later run or decode what the app writes
there: `~/.local/bin`, `~/.local/lib`, autostart and systemd user folders, menu entries, icon themes, thumbnailers,
file-manager scripts, and shell and editor startup files.

There is no override. Grant a narrower folder: `~/.config/someapp` instead of `~/.config`, `~/Projects/site` instead of
`~/Projects` if `~/Projects` holds a key.

## Alternatives

- The **portal file chooser** (`--allow portals`) lets the app ask you for a file in a dialog it does not control; it
  gets the file you pick and nothing else, for as long as you do not revoke it (`appjail portals NAME`).
- **Copying** a file into the app's home is the simplest and keeps your original out of reach.
