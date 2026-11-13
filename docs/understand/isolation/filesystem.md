# The filesystem view

*Part of [Isolation](index.md). Previous: [bubblewrap](bubblewrap.md). Next: [seccomp](seccomp.md).*

## What it is

Inside its jail an app sees a filesystem that appjail assembled for it in a new mount namespace. Nothing of your
filesystem is visible unless it was placed there, and each piece is placed read-only unless there is a reason for it to
be writable.

| Path in the jail | What it is | Access |
|---|---|---|
| `/usr`, `/bin`, `/sbin`, `/lib`, `/lib32`, `/lib64` | the host's system directories, so the app's libraries can find what they need | read-only |
| `/etc` | only fonts, the dynamic linker's cache and configuration, the local time, `alternatives`; with `network`, the files that name resolution and TLS need (`hosts`, `nsswitch.conf`, `resolv.conf`, `ssl`, CA certificates); with `gpu`, the Vulkan and GLVND configuration; a generated `passwd` and `group` | read-only |
| `/app` | the extracted AppImage | read-only |
| `/home/app` | the app's private home, kept between runs in `~/.local/share/appjail/apps/NAME/home` | read-write |
| `/tmp`, `/run` | empty, private, discarded when the app exits | read-write |
| `/run/user/UID` | the runtime directory: only the Wayland socket and, per grant, the audio sockets, the filtered D-Bus socket and the portal's document folder | as granted |
| `/proc`, `/dev` | the jail's own process list; basic devices only, plus GPU and camera nodes when granted | |
| folders and files you grant | at the same path, or under `/home/app` for paths in your home | read-only unless `:rw` |

The app's working directory is its home, and `HOME` points there, so an app that writes its settings to
`~/.config/...` writes them into its private home and finds them again the next time.

Everything else of yours (your home, your documents, other apps, appjail's own data and manifests) does not exist in
the app's world.

## Why it matters

Most of what a malicious program would want from you is in files: credentials, keys, browser sessions, documents, the
history of your shell. Equally important is what it would *write*: a program that can add a line to `~/.bashrc`, drop a
file in `~/.config/autostart` or `~/.local/bin`, or install a systemd user unit gets to run again later, outside any
sandbox. The filesystem view decides both.

## How appjail uses it

### The extracted tree

AppImages are normally mounted with FUSE, which does not work well inside user namespaces. appjail instead extracts the
AppImage once, in a [helper jail](index.md#helper-jails) with no network, validates the result (no device files, no
set-id bits, no symbolic link that leaves the tree, an `AppRun` that resolves inside it) and records a hash of the whole
tree: every path, type, permission, content and link target. Before every start, the stored AppImage must still match
its pinned hash, or appjail refuses to run it; and the tree must still match its recorded digest, or appjail extracts it
again from the verified image, with a warning. A tree changed on disk is never run.

### Granting folders and files

You can give an app a folder (`perms APP --add-dir ~/Documents/notes`, read-only; `:rw` for read-write), a folder for
one run only (`run APP --dir PATH`), or a single file for one run (`run APP --file PATH`, which also passes its path in
the jail to the app). Opening a file from the desktop's menu entry does the same as `--file`. A path in your home
appears at the same place under `/home/app`; a path elsewhere appears at the same path.

Some paths are never granted, whatever the mode:

- **credentials and secrets**: `~/.ssh`, `~/.gnupg`, cloud and container credentials (`~/.aws`, `~/.kube`,
  `~/.docker`, ...), package-registry tokens, password stores and vaults, messaging sessions, browser profiles, mail,
  shell histories, and files named like keys or password databases (`*.pem`, `*.key`, `*.kdbx`, ...), and any folder
  that contains one of these (grant a subfolder instead);
- **too broad**: `/`, your home directory or any of its parents, `~/.config`, `~/.local`, `~/.cache`, and the system
  trees (`/etc`, `/usr`, `/proc`, `/sys`, `/dev`, `/run`, ...);
- **shared temporary directories**: `/tmp` and `/var/tmp`. Programs keep their unix sockets there (the X server's,
  tmux's, agents'), and a bind mount does not stop a process from *connecting* to a socket, even when it is read-only:
  an app given `/tmp` could drive those programs. A single regular file there can still be opened, since a file carries
  no socket;
- **appjail's own files**, which hold the pins and the manifests.

Some paths are refused **read-write** only, because something outside the jail would later run or decode what an app
wrote there: `~/.local/bin`, `~/.local/lib` (where every Python of yours, appjail included, looks for modules),
`~/.config/autostart`, `~/.config/systemd`, the menu entries in `~/.local/share/applications`, icon themes (the desktop
decodes icons outside any sandbox), thumbnailers, file-manager scripts, and shell and editor startup files.

There is no override for these. The way around a refusal is always a narrower grant.

### Grants are bound by descriptor

A check made on a path and a bind made later on the same path are two lookups, and between them a symbolic link can be
swapped in: the check approves `~/Documents/notes`, then a component is replaced with a link to `~/.ssh`, and the bind
follows the link. This is a classic *time-of-check to time-of-use* race, and it was a real flaw in Flatpak
(CVE-2024-42472).

appjail opens each granted path once, then makes every check on the file it actually opened, through its descriptor:
its type, where it really is, whether that place is allowed. It then passes the descriptor itself to bubblewrap
(`--bind-fd`, `--ro-bind-fd`, added in bubblewrap 0.10 for this purpose), so the bind uses exactly the file that was
checked, whatever happens to the path afterwards.

With `network`, the jail starts inside a network namespace made by `pasta`, which closes every inherited descriptor. A
small wrapper between `pasta` and bubblewrap then opens each path again and refuses to start unless it is the same file
(same device and inode) that was checked; appjail keeps its own descriptors open meanwhile, so those numbers cannot be
reused by another file.

## Connections

- [bubblewrap](bubblewrap.md) builds the view; [namespaces](namespaces.md) make it the only one the app has.
- The runtime directory's contents depend on other grants: the Wayland socket for the window, the audio sockets, the
  filtered D-Bus socket, the document portal.
- The portal file chooser is the other way to give an app a file: you pick it in a dialog the app does not control,
  and the app gets that file alone.
- The [network namespace](namespaces.md) is why `/tmp` is not the only place sockets hide: abstract sockets live in
  the network namespace, which [Landlock](landlock.md) covers.
- Decision: [Extract AppImages instead of mounting them](../../decisions/isolation/extraction.md).
- Decision: [Paths that can never be granted, with no override](../../decisions/isolation/refused-paths.md).
- Decision: [Granted paths are bound by descriptor](../../decisions/isolation/grants-by-descriptor.md).

## Limits

- What you grant, the app can read, and with `:rw` change or delete.
- The system directories are readable. They hold no secrets of yours, but they reveal what software is installed.
- A file granted read-write with `--file` cannot be replaced, only rewritten in place: apps that save by writing a new
  file and renaming it over the old one fail on such a file. Grant its folder, or use the portal file chooser.
- A folder whose path contains `:` cannot be granted (the character separates the mode).
- The private home is persistent and is deleted only by `appjail remove`; an app can keep state there between runs, as
  any app does.

## References

- MITRE, [CWE-367: Time-of-check Time-of-use (TOCTOU) Race Condition](https://cwe.mitre.org/data/definitions/367.html).
- Flatpak security advisory [GHSA-7hgv-f2j8-xw87](https://github.com/flatpak/flatpak/security/advisories/GHSA-7hgv-f2j8-xw87)
  (CVE-2024-42472): a symbolic link swapped into a persistent directory let a Flatpak app reach host files; the fix
  introduced bubblewrap's `--bind-fd`.
- Linux manual pages [unix(7)](https://man7.org/linux/man-pages/man7/unix.7.html) (unix sockets, which a process can
  connect to when it can see their path), [open(2)](https://man7.org/linux/man-pages/man2/open.2.html) (`O_PATH`) and
  [symlink(7)](https://man7.org/linux/man-pages/man7/symlink.7.html).
- AppImage documentation, [FUSE](https://docs.appimage.org/user-guide/troubleshooting/fuse.html): why AppImages are
  normally mounted, and how they run without FUSE.
