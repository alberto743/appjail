# The host's system view: the evidence

Working notes, not a specification. Today's behaviour is on [bubblewrap](../understand/isolation/bubblewrap.md), and the
conclusion drawn from these measurements is [Narrowing the host's system view](../decisions/isolation/host-view.md).
Written in November 2026 from experiments in the Debian 13 guest, then repeated on Ubuntu 26.04 and Fedora 45
([below](#ubuntu-and-fedora)). "Measured" means a script ran in the guest (they are in `tests/hostview/`); "not done"
means neither. Nothing here was run on the maintainer's own machine.

The question: the jail binds the host's `/usr`, `/bin`, `/sbin` and `/lib*` read-only, so an app can list the installed
software and run any program of the host. How much of that can be taken away without breaking the apps, and what would
it hide?

## Why a list of linked libraries is not an answer

The `NEEDED` entries of an ELF file name only the shared libraries linked at build time. They say nothing about:

- programs an app starts (`ln`, `strace`, `xdg-open`);
- files opened at run time (`dlopen` of a plug-in, keyboard layouts, fonts, locales, theme and MIME data);
- what the kernel opens by itself when it runs a file: the ELF loader (`PT_INTERP`) and the interpreter named on a
  script's `#!` line.

So the study traces behaviour: the real appjail jail, under `strace -f -y`, for several scenarios per app, with the
system view narrowed in four ways. A static scan of the files for host paths is added as a pointer to where a trace
would have to look.

## Method

**Apps** (approved test AppImages, installed with `appjail add`; Electron apps were not installed): htop 3.5.3 (a
terminal app, DwarFS), Galculator 2.1.4 (GTK 3, DwarFS), Lagrange 2.0.4 (SDL) and ImageMagick 7.1.2-36 (command line,
whose `AppRun` is a Bash script). GUI apps ran against a headless weston (no seat, so no key or pointer input); htop ran
in a pseudo-terminal that sent keys.

**Scenarios.** Start (all four); htop: the text screen, `s` (htop's strace screen) and `l` (the `lsof` screen);
ImageMagick: `-version`, a PNG to JPEG conversion, drawing text, `-list font`, writing a PDF. A scenario passes when
the app does what it did in the first variant: exit status 0, or still running at the time limit for a window.

**Variants** (`tests/hostview/matrix.py` replaces `system_args` of `jail.py`; everything else is appjail's own jail):

| | What the jail shows of the host |
|---|---|
| **C** | today: `/usr`, `/bin`, `/sbin`, `/lib*`, read-only |
| **A** | C with `/usr/bin`, `/usr/sbin`, `/usr/libexec` and `/usr/share/applications` emptied; only `sh` and `env` put back |
| **A2** | A plus the programs the app was seen to run (and the interpreters they and the app's own scripts need) |
| **B** | an empty `/usr`, `/bin`, `/sbin`, `/lib*`; only the files the run was seen to open, run or look up (about 30 for htop, 1000 to 1250 for the others, each bound by itself) |

A2 and B are trained on one scenario (the "training" run, in variant C) and then run on all of them. The table is the
result of three identical rounds; all rounds agreed.

## What the apps run (measured, variant C)

Host programs the four apps started: `ln` (htop and Galculator), `strace` (htop, on `s`), `basename` and `env`
(Lagrange), `bash`, `dirname` and `readlink` (ImageMagick), and `sh` (the shebang of Lagrange's `AppRun`). Attempts that
found nothing: `xdg-user-dir` (Lagrange) and `lsof` (htop, on `l`; the guest does not install it). Everything else in
the `exec` calls was the app's own tree.

These are not features of the apps. The two "anylinux" AppImages (htop, Galculator) run a hook script that calls `ln` to
map hard-coded paths (`/tmp/_…/galculator/ui/main_frame.ui`); ImageMagick's `AppRun` needs `bash`, `dirname` and
`readlink`; Lagrange's needs `basename` and `env`. The one real feature is htop's: its strace screen runs `strace`.

## A static scan names more than a run shows (measured)

Scanning the extracted trees (`tests/hostview/static_refs.py`) for host paths and helper names gives a longer list,
which shows what a scenario that was not run could use:

| App | Named in its files (not run in the scenarios) |
|---|---|
| htop | `xdg-open`, `lsof`, `strace`, `curl`, `wget`, `zenity`, `kdialog`, `notify-send`, `pkexec` |
| Galculator | `update-mime-database`, `gsettings`, `dbus-launch`, `xdg-open`, `gio`, `lpr`, `convert`, `notify-send` |
| Lagrange | `xdg-open`, `/usr/bin/dbus-send`, `zenity`, `convert` |
| ImageMagick | `/usr/bin/gs`, `/usr/bin/lpr`, `perl`, `make`, `pkg-config`, `xdg-open`, `curl` |

A name in a file is not an `exec`: the list is noisy (a word like `ps` or `display` matches strings of other kinds) and
is a place to look, not a result. It does show that `xdg-open`, which a link click or an "open file" would run, is named
by all four apps and was run by none of the scenarios, because a headless compositor cannot click.

## Results (measured)

Each cell is the result of the scenario in that variant, over three rounds.

| App and scenario | C | A | A2 | B |
|---|---|---|---|---|
| htop: text screen | ok | ok | ok | ok |
| htop: `s` (runs `strace`), trained on `s` | ok, ran `strace` | ok, but `strace` not found | ok, ran `strace` | ok, ran `strace` |
| htop: `s`, trained on the text screen only | ok, ran `strace` | `strace` not found | **`strace` not found** | **`strace` not found** |
| htop: `l` (`lsof` is not installed) | nothing to run | same | same | same |
| Galculator: start | ok | **fails** (hook needs `ln`: "main_frame.ui: No such file") | ok | **aborts** (XKB keymap) |
| Lagrange: start | ok | ok (`basename` missing, harmless) | ok | ok |
| ImageMagick: all five scenarios | ok | **all fail** (`AppRun` needs `bash`) | ok | ok |

Three things are plain:

- **A fixed minimal list is not enough.** `sh` and `env` break two of four apps outright: Galculator needs `ln`,
  ImageMagick needs `bash`, `dirname` and `readlink`. A list that would have covered these four holds at least `sh`,
  `bash`, `env`, `ln`, `dirname`, `basename` and `readlink`, and is the list of these four apps: it says nothing about
  the next one; on Ubuntu and Fedora a library needs more ([below](#ubuntu-and-fedora)).
- **A list recorded from one scenario misses the helpers of another.** Trained on htop's text screen, A2 and B had no
  `strace`, and the strace screen failed with no error to the user other than the helper's absence.
- **A trace of open calls never shows what the kernel opens.** The first version of B started no program at all ("No
  such file or directory" on the app's own `AppRun`): the ELF loader and the shell or Bash named on its `#!` line were
  never opened by a process the trace could see. After adding both to the set, B started htop, Lagrange and ImageMagick.

Variant B did not start Galculator in any round: its GTK start aborts with "Failed to create XKB keymap", after
`xkbcommon` could not find `types/mousekeys`, a file that the training run had opened and that was bound in the jail
(checked in the arguments and in the jail's own mount trace). The cause was not found, so the failure is reported as
what it is: B needs an explanation before it could be called workable, and it binds 1000 to 1250 single files per app,
named by the host's own library versions (`libssl.so.3`, `libcap.so.2.75`), so it would have to be re-recorded after
the host's packages change.

## What a program in the jail can still list (measured, htop's jail)

| | C | A and A2 |
|---|---|---|
| programs in `/usr/bin` | 1029 | 2 (`sh`, `env`) |
| `/usr/sbin`, `/usr/libexec` | 244, 25 | 0, 0 |
| menu entries in `/usr/share/applications` | 11 | 0 |
| package directories in `/usr/share/doc` | 916 | 916 |
| files in `/usr/lib/x86_64-linux-gnu` | 1412 | 1412 |
| library versions (`libssl.so.3`, `libc.so.6`) | visible | visible |
| `/usr/lib/os-release` (the distribution and release) | readable | still bound |

So narrowing the programs hides which programs and desktop entries are installed. It does not hide the names of the
installed packages (`/usr/share/doc`), the library versions, or the distribution: those live in `/usr/lib` and
`/usr/share`, which the apps need (libraries, fonts, keyboard layouts, themes). Hiding them would take variant B's
approach.

## Ubuntu and Fedora

The same apps (same hashes) and the same matrix ran once on Ubuntu 26.04 and Fedora 45, and once more on Debian with the
final version of the script (it skips only the harness's own `bwrap` in a trace, and puts back a program at its own
path, so a helper in a subdirectory of `/usr/libexec` counts). Debian gave the results above again.

| App and scenario | Ubuntu 26.04: C / A / A2 / B | Fedora 45: C / A / A2 / B |
|---|---|---|
| htop: text screen; `s` trained on `s` | ok / ok, `strace` not found / ok / ok | same |
| htop: `s` trained on the text screen only | A2 and B: `strace` not found | same |
| htop: `l` | C runs `lsof` (installed there); A, A2, B: not found | `lsof` not installed |
| Galculator: start | ok / **fails** / ok / **aborts** (XKB keymap) | ok / **fails** / ok / ok |
| Lagrange: start | ok / **aborts** / ok / **aborts** | ok / **aborts** / ok / **aborts** |
| ImageMagick: all five scenarios | ok / **all fail** / ok / ok | same |

The new result is Lagrange's. On both systems the GTK image loader (glycin, which GTK uses through gdk-pixbuf) runs host
programs itself: `/usr/bin/bwrap`, to sandbox its loader (which fails in the jail, after which glycin says "running
without sandbox"), then the loader `/usr/libexec/glycin-loaders/2+/glycin-svg`; Ubuntu's also runs `xdg-user-dir`. With
A, `bwrap` is missing and the app aborts. B aborts too: on Ubuntu it ran only `basename`, on Fedora glycin chose another
loader, `glycin-image-rs`, that the training run had not used. So a host library, not the app's own scripts, can need
programs in `/usr/bin` and in a subdirectory of `/usr/libexec`, and which one depends on the system and on the run.
Galculator, which aborted under B in every run on Debian and Ubuntu, started under B on Fedora.

What a program in the jail can list, in the same jail on each system:

| | Debian 13 | Ubuntu 26.04 | Fedora 45 |
|---|---|---|---|
| `/usr/bin`, `/usr/sbin` | 1029, 244 | 1442, 590 | 1556 (one directory: `/usr/sbin` is a link to `bin`) |
| `/usr/libexec`, menu entries | 25, 11 | 45, 14 | 88, 9 |
| package directories in `/usr/share/doc` | 916 | 1164 | 565 |
| the distribution (`/usr/lib/os-release`) | readable | readable | readable |

With A, the programs and menu entries drop to the two put back (on Fedora `sh` and `env` show in both names), and the
package directories, libraries and release stay, as on Debian.

## What is not done

- **Interactive features.** The compositor had no input device, so no file dialog, print dialog, link click, drag and
  drop or "open with" ran. Those are where `xdg-open`, `gio`, `update-mime-database` and `dbus-send` would be started.
- **Electron apps** (Obsidian, Joplin), which start more helpers, were not installed.
- **The effect on an attacker.** That fewer programs make a compromised app's work harder (no `perl`, `python3`, `gcc`,
  `curl`) is the reason for the idea, not a measured result: an app can bring its own tools in its tree, and the jail
  still gives it no network without `network`.

## Reproducing

In the Debian guest, with the four apps installed (`APPJAIL_DATA_DIR` and `APPJAIL_CONFIG_DIR` pointing at a scratch
directory; `appjail tools install dwarfs` first), a headless weston on `WAYLAND_DISPLAY`, and the project at `~/appjail`
(`tests/vm/sync.sh`):

```
python3 tests/hostview/matrix.py htop tui strace-key lsof-key --train strace-key
python3 tests/hostview/matrix.py galculator start
python3 tests/hostview/matrix.py lagrange start
python3 tests/hostview/matrix.py imagemagick version png-jpg text fonts pdf --train text
python3 tests/hostview/matrix.py probe htop
python3 -I tests/hostview/static_refs.py PATH/TO/EXTRACTED/TREE...
```

`strace` is already a guest package (`tests/vm/packages.txt`).

## References

- Linux, [execve(2)](https://man7.org/linux/man-pages/man2/execve.2.html), "Interpreter scripts": a script is run
  through the interpreter named on its `#!` line, which is why that interpreter has to exist in the jail although no
  process opens it.
- Linux, [elf(5)](https://man7.org/linux/man-pages/man5/elf.5.html): `PT_INTERP` names the program interpreter (the
  loader).
- [strace(1)](https://man7.org/linux/man-pages/man1/strace.1.html): `-f` follows children, and a call interrupted by
  another thread is printed as an `unfinished` line and a `resumed` line.
- Flatpak documentation, [Sandbox permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html): the
  `host-os` (the host's `/usr`, `/bin`, `/sbin`, `/lib*`) and `host-etc` filesystem options.
