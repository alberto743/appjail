# URL handlers and a second launch: the evidence

Working notes, not a specification: the open question is on [deferred work](../decisions/deferred.md) (row "URL
handlers"); no decision has been taken and no code written. Written in November 2026 from experiments in the qemu
guests. "Measured" means a command or test ran in a guest; "read" means documentation only; "not done" means neither.
Nothing here was run on the maintainer's own machine. The scripts are at the end so each run can be repeated.

The question: appjail leaves out every `x-scheme-handler/` type of an app's own menu entry on purpose (a link opened
anywhere on the desktop would start an untrusted program with an untrusted string). Letting the user opt in to some
schemes needs two answers first: what exactly the desktop hands over, and what happens when the app is already running,
since the apps people want links for (browsers, chat clients, login callbacks) are single-instance programs.

## Environment of the measurements

| | Debian 13 | Ubuntu 26.04 | Fedora 45 |
|---|---|---|---|
| Kernel | 6.12.117 | 7.0.0-44 | 7.3.4 |
| GLib (`gio`) | 2.84.4 | 2.88.0 | 2.90.0 |
| bubblewrap | 0.12.0 | 0.11.1 | 0.13.1 |
| Python | 3.13.5 | 3.14.4 | 3.15.0 |
| `kernel.yama.ptrace_scope` | 0 | 1 | 0 |
| Wayland compositor for the GUI app | weston 14.0.2 headless | not used | not used |

Test apps: Lagrange v2.0.3 (the approved GUI test app, Debian only; a Gemini browser whose own menu entry declares five
schemes) and a purpose-built Electron probe (below) on all three. The probe's Electron is `v45.4.1`, the official
`electron-v45.4.1-linux-x64.zip` of github.com/electron/electron (124 MB; its sha256 matched the release's
`SHASUMS256.txt`, `e1d077c7…560b875`). It needs the system libraries `libnss3` and `libnspr4`, which the guests lacked;
`libnss3` is now in `tests/vm/packages.txt` (Fedora: `nss`, `nspr`). Every Electron run used `--ozone-platform=headless
--disable-gpu`, so no window or compositor was involved.

## What appjail does today

| Observation | Result |
|---|---|
| Lagrange's own menu entry | `Exec=lagrange %U`, `MimeType=x-scheme-handler/gemini;…/gopher;…/spartan;…/misfin;…/nex;` |
| `appjail desktop lagrange --show` | `Offered none`, `Not offered` all five (`desktop.py`: the prefixes `x-scheme-handler/` and `inode/` are always dropped) |
| `appjail open lagrange -- gemini://example.org/x` | refused: `not a regular file: gemini://example.org/x` |
| The menu entry appjail writes | `Exec=appjail open NAME -- %F` with file types, else `appjail run NAME` |

## What a desktop hands to a handler (measured, GLib)

A stand-in entry whose `Exec` is a script that logs its arguments, registered with `gio mime` in a throwaway data
directory, and `gio open` with various inputs. The three guests have different GLib versions and gave identical results.

| Input to `gio open` | What the handler received (`%U`; `%u` the same) |
|---|---|
| `gemini://example.org/plain` | one argument, unchanged |
| `gemini://example.org/a b/ü?x=%20y&z=é#frag` | one argument, unchanged (a space stays a space, `%20` stays) |
| `gemini://example.org/q"u'o$x;`id`&\|` | one argument, unchanged: the desktop starts no shell |
| `gemini://example.org/--help` | one argument, unchanged (a leading `--` cannot occur: the scheme comes first) |
| `GEMINI://example.org/upper` | delivered to the handler of `gemini`, with the capitals kept |
| `gemini:relative-no-slashes` | delivered, unchanged |
| a URL of 4000 characters | delivered whole: the desktop applies no length limit |
| a local file `…/a b.txt` (entry `%U`) | a plain path, not a `file:` URL |
| a local file `…/-dash.txt` | the absolute path (it cannot read as an option) |
| a file and a URL in one call | two launches, one each; the order differs between guests |

Read, in the
[Desktop Entry Specification](https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html)
(version 1.5): `%u` "a single URL", `%U` "a list of URLs. Each URL is passed as a separate argument to the executable
program", and for both "local files may either be passed as file: URLs or as file path", so a handler has to be ready
for both. Quoting in `Exec` is done by double quotes with backslashes before `"`, `` ` ``, `$` and `\`; a literal `%` is
`%%`; at most one of `%f %u %F %U` per command line, and `%F` and `%U` only "as an argument on their own". The page does
not mention `x-scheme-handler`, and the page that defines `MimeType` does not either; the MIME registration page was not
read. Not done: KDE Plasma (KIO) and Cinnamon launchers; the specification leaves them free to pass `file:` URLs for
local files.

## A second launch of a running app: Lagrange (measured, Debian)

Lagrange logs its single-instance steps. Weston headless has no seat, so GDK prints a warning; the app runs.

| Case | Result |
|---|---|
| A: `appjail run lagrange -- gemini://localhost/first`; 8 s later one `lagrange` process | stays up |
| B: `appjail run lagrange -- gemini://localhost/second` while A runs | exits **0 after about 1.9 s**; logs `open newtab:1 url:gemini://localhost/second` and `ipc.signal arg:2 raise:1`; A is unchanged |
| Files Lagrange keeps in the private home that could carry a message | only `.config/lagrange/.pid` (the text `2`); no pipe, no socket anywhere under the home |
| Where B's signal went | pid 2 of **B's own** pid namespace (not A's: the namespaces differ, `4026532381` for A); inference from the two namespaces, A's side was not logged |
| C: a second `AppRun` started **inside A's jail** (the script below swaps the jail's start command for `sh -c`) | prints `Commands sent to Lagrange process 3`, exits 0; the first instance (pid 3, the shell being pid 2) keeps running |

So Lagrange's own handover works when both processes share a pid namespace and fails silently, with exit status 0, when
they do not. Lagrange finds the running instance from the pid in `.pid`, which means pid 2 in every jail.

### A stale pid file (measured, Debian)

`.config/lagrange/.pid` held `2` and was dated 19 November, probably left by an earlier end-to-end run that ended the
app by a signal (not verified). With it present, **every** launch of Lagrange found "another instance" (pid 2 exists in
the new jail: itself), tried the signal handover and exited at once; the window never appeared. Moving the file aside
restored normal starts. This is independent of URL handlers: any app that keeps a pid file in its persistent home will
do this after an unclean end, because every jail has its own pid namespace and the numbers repeat.

## A second launch of a running app: an Electron probe (measured)

Chromium's single-instance lock (`app.requestSingleInstanceLock()`, which Electron apps use) is a symlink
`SingletonLock` named `HOSTNAME-PID` in the user-data directory (here the shared private home), plus a unix socket under
`/tmp` (`SingletonSocket`, private to each jail) and a `SingletonCookie`.

| Case | Debian | Ubuntu | Fedora |
|---|---|---|---|
| E1 sandbox: no grant, no flag | abort, `The SUID sandbox helper binary was found, but is not configured correctly` | same | not run |
| E1 sandbox: `userns` granted | starts | abort, the same message (cause not found; `kernel.apparmor_restrict_unprivileged_userns` is 0) | starts |
| E1 sandbox: `--no-sandbox` | starts | starts | not run |
| E2 second jail while the first runs | second `requestSingleInstanceLock` → **true**; both stay up | same | same |
| E2 lock before and after | `SingletonLock -> appjail-2` both times; cookie and socket replaced by the second jail's | same | same |
| E3 second process in the **same** jail | first logs `second-instance`; second gets `false` and exits 0 | same | same |
| E4a stale lock (`appjail-2`) after SIGKILL, then a fresh launch | takes it over, starts | not run | not run |
| E4b lock naming pid 3 with a dead cookie and socket, three fresh launches | all three start | not run | not run |

Reading the E2 rows: the main process of every Electron jail is pid 2 (pid 1 is bubblewrap's init), so the lock always
reads `appjail-2` (the hostname inside the jail is `appjail`). The second jail finds a lock that names its own pid,
takes it as stale and replaces it. Result: two full instances of the app run on **one profile directory**, and the first
instance's lock, cookie and socket were overwritten by the second's. Neither can receive anything from a later launch.
Corruption of the profile was not measured; it is the risk this implies for databases such as IndexedDB and LevelDB. The
URL handed to the second jail is not lost (it is its own first instance's argument), but nothing reaches the app the
user was already using.

E3 in the same jail: the first instance logs the full command line of the second, with the URL byte for byte
(`appjailprobe://second/a b?x=1&y="q"`, spaces, `&` and quotes intact); Electron added `--allow-file-access-from-files`
to it. The second exits 0 at once. This is Chromium's design working as intended.

The sandbox rows: appjail clears set-id bits when it checks an extracted tree, so Electron's `chrome-sandbox` helper can
never be set-uid in a jail. The sandbox then needs the `userns` grant or `--no-sandbox`. Ubuntu 26.04 refused the
namespace sandbox even with the grant (not investigated); `--no-sandbox` was used for the Ubuntu rows above, with
`userns` denied.

## A socket from the host into a jail (measured, all three guests)

A directory granted with `dirs = ["~/e7dir:rw"]` is bound into the jail at `/home/app/e7dir`. A process inside the jail
bound a unix socket there; the host connected to the same path, sent `open appjailprobe://x` and received a reply. It
worked on Debian, Ubuntu and Fedora. Seen from inside the jail the host peer's pid is `0` (another pid namespace) and
its uid is the user's, so a service in a jail could tell callers apart by user and directory permissions, not by
process.

## A relay inside the running jail (measured, all three guests)

A throwaway prototype (scripts at the end, not part of `src/`): the jail's start command is wrapped so that a small
Python relay runs as pid 2 and starts the app as its child (pid 3). The relay listens on a unix socket in a directory
granted with `dirs = ["~/relay-NAME:rw"]` (mode 700, the socket 600). A host client connects, sends one line, and the
relay runs `/app/AppRun LINE` inside the jail, so the app's own single-instance handover finds the running instance.

| Case | Result |
|---|---|
| Lagrange running, two links sent through the socket | both replies `ok` in under 1 ms; each helper prints `Commands sent to Lagrange process 3` and exits; one `lagrange` process remains |
| Electron probe running, links `appjailprobe://second/a b?x=1&y="q"` and `appjailprobe://third` | the first instance logs `second-instance` with the URL byte for byte; each helper gets `requestSingleInstanceLock -> false` and exits; `SingletonLock` stays `appjail-3` (the app is pid 3, so the first instance's lock is no longer overwritten) |
| A link with a control character | refused by the relay (`refused`), nothing started |
| The jail killed with SIGKILL | the socket file stays, and a client gets `ConnectionRefusedError` (not "no such file"): stale and live sockets can be told apart, and the next launch unlinks the stale file |
| A link sent about 1.1 s after the launch began, as soon as the socket existed | delivered while Electron was still starting; Chromium's lock stayed with the first instance |
| `gio open appjailprobe://via-gio/a b?q=1` with a stand-in entry whose `Exec` is the client (`%U`) and `xdg-mime`-style default set by `gio mime` | delivered unchanged to the running probe |
| Seccomp of the relay and of the app | both `Seccomp: 2`, `NoNewPrivs: 1`, no capabilities: the relay's children inherit the jail's filter |
| Socket directory | owner the user, mode 700 under the user's home; another user cannot traverse it (reasoned from the modes: the check with `sudo -u nobody` failed on the unreadable client script, not on the socket) |

The Electron rows were repeated on Ubuntu 26.04 (with `--no-sandbox`, as in the sandbox rows above, since the namespace
sandbox still aborts there) and on Fedora 45 (with the `userns` grant): the same results, `SingletonLock -> appjail-3`,
two `second-instance` events with the URLs byte for byte, the control-character link refused. Lagrange was run on Debian
only. In the process list the match for `relay.py` also caught one process outside the jail with `Seccomp: 0` (the
host-side launcher whose command line names the script); the relay and the app themselves showed `Seccomp: 2`.

An unintended first run is worth keeping: the relay at first passed the app's own arguments to every helper, so the
helper for the second link also carried the first URL; Lagrange then did not hand over (the extra argument changed its
handling) and started a second instance that rewrote `.pid`. The helper must get `AppRun` and the new link only.

Open from this run: the real unix path limit (108 bytes) bounds the length of the socket directory name; a link that
arrives before the app writes its own lock may start a first instance in the helper (Chromium's lock is atomic,
Lagrange's `.pid` is not).

## The desktop's own tools with appjail's entry (measured, all three guests)

With the built code, not the prototype: `appjail perms probe --add-scheme appjailprobe`, `appjail desktop probe` (the
entry says `Exec=… open probe -- %U` and `MimeType=x-scheme-handler/appjailprobe;`), `update-desktop-database`, then
`xdg-mime default appjail-probe.desktop x-scheme-handler/appjailprobe` in a throwaway `XDG_DATA_HOME` and
`XDG_CONFIG_HOME`. The probe ran on a headless weston (`full_wayland` granted; a menu entry is refused for
`display = none`).

| Step | Result |
|---|---|
| `xdg-mime default` | writes `x-scheme-handler/appjailprobe=appjail-probe.desktop` under `[Default Applications]` in the throwaway `mimeapps.list`; appjail itself never writes it |
| `xdg-mime query default` before that | empty on Debian; the entry itself on Ubuntu and Fedora, where `xdg-mime` takes the only registered handler from `mimeinfo.cache` |
| `gio open 'appjailprobe://cold/a b?x=1'`, app not running | the entry starts the app; its argument is the link, unchanged |
| `gio open 'appjailprobe://via-gio/a b?x=1&y="q"'`, app running | `Sent 1 link to the running probe.`; the first instance logs `second-instance` with the link byte for byte; the helper exits at once |
| `xdg-open 'appjailprobe://via-xdg-open/z'`, app running | the same (`xdg-open` ran the entry through the desktop-neutral path: no desktop environment in the guest) |
| `~/.local/share/appjail/run/` during the run | one FIFO, `probe.link`, mode `prw-------` |

Lagrange, run through `perms`, `desktop` and `open` without the desktop tools (Debian), received two links in the
running process ("Commands sent to Lagrange process 3"). `xdg-utils` is now in the guests (`tests/vm/packages.txt`).

## KDE's and Cinnamon's launchers (measured, Debian 13 with KDE Frameworks 6)

A stand-in entry (`Exec=log.sh %U`, which logs each argument it gets) registered for a scheme and for `text/plain`, with
`xdg-open` and `kde-open` (package `kde-cli-tools`) run under a private session bus in the `debian-compositors` guest,
with `XDG_CURRENT_DESKTOP=KDE`, `KDE_SESSION_VERSION=6`, `XDG_MENU_PREFIX=plasma-` (KDE builds its service cache from
the Plasma menu; without it the entry is not found and `kde-open` tries to read the URL as a file) and Qt's `offscreen`
platform. No Plasma or Cinnamon session ran: only the launchers that `xdg-open` and the desktops call.

| Input | GLib (`gio open`, also Cinnamon's `xdg-open`) | KDE (`kde-open`, also KDE's `xdg-open`) |
|---|---|---|
| `gemini://example.org/plain` | one argument, unchanged | one argument, unchanged |
| `gemini://example.org/a b/ü?x=%20y&z=é#frag` | unchanged | `%20` **decoded to a space**; the rest unchanged |
| `GEMINI://example.org/Upper` | the capitals kept | the scheme **lower-cased** |
| a `"`, `` ` `` or `\|` in the path | unchanged | percent-encoded (`%22`, `%60`, `%7C`); `'`, `$`, `;` and `&` unchanged |
| a local file (any of `a b%20c.txt`, `-dash.txt`, one with `"'$`) | a path | a plain path (not a `file:` URL), the name intact |
| a shell | none | none |

Cinnamon's `xdg-open` runs `gio open` (the `cinnamon` branch of `xdg-open`, read in the script), so Cinnamon is the GLib
column; its own menu and Nemo use GLib's application launching and were not run. Every link and file was one argument in
both. KDE rewrites a URL (a decoded `%20` can change what a link means to an app that compares it byte for byte), so a
link that reaches the app is not always the one that was clicked; appjail passes on what it receives. Not run: a click
in Dolphin or Plasma, KDE's own choice of default handler (its `kdeglobals` and `mimeapps.list`, here only
`mimeapps.list`), and the same on Ubuntu and Fedora.

## A real Electron application: Joplin (measured, Debian)

Joplin 3.7.24 (`laurent22/joplin`, the official AppImage, 212 MB, Electron; its entry declares
`x-scheme-handler/joplin`) added with `--scheme joplin --allow userns --allow full_wayland`, on a headless weston, the
entry made by `appjail desktop`, `xdg-mime default`, links sent with `gio open` and `xdg-open`. Its
`joplin://x-callback-url/openNote?id=…` links (a note that does not exist, so each handled link leaves "No such note" in
Joplin's log) were the test.

| Grants | Result |
|---|---|
| none (no network) | a link opened through the entry starts Joplin with it, but **every later link starts a full second instance** (own renderer and GPU processes): Joplin's log says `IPC: [error] Could not start server: Error: getaddrinfo EAI_AGAIN localhost`. Joplin finds a running instance through an HTTP server on `localhost` (a port from 2658 up, a secret key in its profile), and without `network` the jail has no `/etc/hosts`, so `localhost` does not resolve. |
| `network` (pasta) | the first instance served links 13 and 14 ("No such note" in its log, the helpers exited), but a cold start through the entry ended by itself a second after it started (`IPC: Sending message` with nobody to answer), and one helper in four stayed as a full instance |
| `network_host` (the host's loopback) | the cold start stayed; links 22 and 23 reached the first instance; link 24 stayed as a second full instance |

So the relay did what it is for in every row (each link started `AppRun LINK` in the running jail, in the same network
and PID namespaces as the first instance), and Joplin's own handover decided what happened next. It needs `network`, and
even then it loses about one link in three or four: a second instance of the same profile. This is the behaviour its
users report upstream (a forum thread titled "URI callback opens second instance of Joplin"). The relay cannot repair an
app whose own single-instance check is unreliable; Joplin is a poor example of one that has a check. An app that uses
Electron's `requestSingleInstanceLock` (the probe) or Lagrange's pid file works through the relay on all guests.

## A real Electron application with a working check: Obsidian (measured, Debian)

Obsidian 1.15.1 (`obsidianmd/obsidian-releases`, the official AppImage, 132 MiB, Electron; its entry declares
`x-scheme-handler/obsidian`; the hash matched the digest GitHub gives) added with
`--scheme obsidian --allow userns --allow full_wayland`, on a headless weston, the entry made by `appjail desktop`,
`xdg-mime default`, links sent with `gio open`. Obsidian uses Chromium's lock (`SingletonLock`, `SingletonSocket`) and
prints each link it handles to its standard output, so the first instance's own output shows what reached it. The vault
was a directory with six notes in the private home, listed in Obsidian's `obsidian.json`; links named it
(`obsidian://open?vault=vault&file=noteN`).

| Case | Result |
|---|---|
| a cold start through the entry (`gio open`) | one instance, `SingletonLock -> appjail-3` |
| five more links, 12 s apart, through the relay | the first instance printed `Received callback URL` and `Processed URI` for each; it stayed the only main process (the helpers exited at once); the lock stayed `appjail-3`; no `process_singleton` line in its output |
| the same with `appjail run obsidian -- LINK` (a second jail, no relay) while it runs | a second full instance that stayed running; `SingletonLock` rewritten to `appjail-2`; the first instance's count of received links did not change |
| links that named a vault that does not exist | the first instance did not answer the second launch in time (a modal error), and Chromium **killed it and took over**: the jail ended, and the next link started a new instance. Not the relay's doing; a link to a missing vault is the app's own trouble |

So with an app whose own check works, the relay does what a second jail cannot: the link reaches the instance the user
already has, and a second instance on one profile does not start. Obsidian was tried on Debian only (one 132 MiB
download).

## Not measured

- A click in Dolphin, Plasma, Nemo or the Cinnamon menu (a full desktop session); KDE's default-handler configuration
  beyond `mimeapps.list`; the KDE launcher on Ubuntu and Fedora.
- A real login flow with a real service (Obsidian's links open notes; Joplin's check is unreliable); Obsidian on Ubuntu
  and Fedora.
- Profile corruption by two instances on one profile.
- Why the Chromium namespace sandbox did not start on Ubuntu 26.04 with `userns` granted.
- Lagrange's single-instance code (not read; its behaviour was observed).

## What the evidence says

- The URL arrives as one argument, unchanged and unlimited, and may carry any scheme case; an app launcher must check it
  itself (registered scheme compared in lower case, length, control characters, placed after `--`).
- Starting a **new jail** per link is wrong for single-instance apps: Lagrange loses the URL and exits silently, and
  Chromium apps start a second instance on the same profile. The same holds today for files opened with `appjail open`.
- Handing the link to a process **inside the running jail** works for both apps, because their own handover logic then
  sees the running instance. A host process cannot join a jail without the jail's seccomp filter and Landlock domain.
- A relay inside the jail that the host reaches through a socket in a granted directory is feasible on all three guests;
  it cannot identify callers by pid. A prototype relay that runs the app's start command with the link as its only
  argument delivered links to the running Lagrange and Electron probe on Debian (section above).

## Scripts

The probe's `main.js` (the whole app: a `package.json` with `{"name": "appjail-probe", "main": "main.js"}`, an `AppRun`
of `exec "$here/electron/electron" $PROBE_FLAGS "$here/app" "$@"` and a `.desktop` file with
`MimeType=x-scheme-handler/appjailprobe;`):

```js
const { app } = require('electron');
const fs = require('fs');
const path = require('path');
const stamp = () => new Date().toISOString().slice(11, 23);
const log = (msg) => {
  try { fs.appendFileSync(path.join(app.getPath('home'), 'probe.log'), `${stamp()} pid=${process.pid} ${msg}\n`); } catch (e) { }
};
const pidns = () => { try { return fs.readlinkSync('/proc/self/ns/pid'); } catch (e) { return '?'; } };
log(`start argv=${JSON.stringify(process.argv.slice(1))} pidns=${pidns()} userData=${app.getPath('userData')}`);
const got = app.requestSingleInstanceLock();
log(`requestSingleInstanceLock -> ${got}`);
if (!got) {
  log('second instance: exiting');
  app.exit(0);
} else {
  app.on('second-instance', (event, argv, cwd) => log(`second-instance argv=${JSON.stringify(argv)} cwd=${cwd}`));
  app.setAsDefaultProtocolClient('appjailprobe');
  app.whenReady().then(() => log('ready'));
}
```

Packing without `appimagetool`: appjail reads a type-2 image as an ELF runtime followed by a SquashFS and extracts the
SquashFS with `unsquashfs`, so a 64-byte stub header and the guest's `mksquashfs` suffice (the image is never run
outside a jail). The Electron zip is unpacked with Python's `zipfile`, restoring the modes (the guests have no `unzip`):

```sh
mksquashfs AppDir probe.squashfs -noappend -quiet
python3 - <<'PY'
import struct
h = bytearray(64)
h[:4] = b"\x7fELF"; h[4], h[5] = 2, 1; h[8:11] = b"AI\x02"
struct.pack_into("<Q", h, 0x28, 64); struct.pack_into("<HH", h, 0x3A, 64, 0)
open("probe.AppImage", "wb").write(bytes(h) + open("probe.squashfs", "rb").read())
PY
appjail add --file probe.AppImage --name probe --display none
appjail perms probe --allow userns --set-env PROBE_FLAGS="--ozone-platform=headless --disable-gpu"
```

E2, a second jail while the first runs (after `cleanup`, which kills the jails and `electron` processes):

```sh
setsid appjail run probe -- appjailprobe://first > /tmp/A.out 2>&1 &
sleep 9; ls -la ~/.local/share/appjail/apps/probe/home/.config/appjail-probe | grep -i singleton
timeout 20 appjail run probe -- appjailprobe://second > /tmp/B.out 2>&1; echo "B exit $?"
cat ~/.local/share/appjail/apps/probe/home/probe.log
```

E3 and the Lagrange case C, a second process inside the first jail: a Python script that imports `appjail.runner`,
replaces `runner._run_app` with a wrapper that swaps the jail's start command (everything from `/app/AppRun`) for
`sh -c SCRIPT`, and calls `runner.launch(NAME)`. For the probe the script is:

```sh
/app/AppRun appjailprobe://first > /tmp/first.log 2>&1 &
sleep 8
/app/AppRun "appjailprobe://second/a b?x=1&y=\"q\""; echo "second exit $?"
sleep 2; cat /home/app/probe.log
```

The Lagrange script is the same with `appjail run lagrange`'s own `AppRun` and `gemini://localhost/…` URLs.

The `gio` probe (in a throwaway `XDG_DATA_HOME`; `log.sh` writes each of its arguments to a file):

```sh
mk() { printf '[Desktop Entry]\nType=Application\nName=%s\nExec=%s/log.sh %s\nMimeType=%s\nNoDisplay=true\n' \
       "$1" "$t" "$2" "$3" > "$XDG_DATA_HOME/applications/$1.desktop"; }
mk probeU %U "x-scheme-handler/gemini;text/plain;"
mk probeu %u "x-scheme-handler/gopher;"
update-desktop-database "$XDG_DATA_HOME/applications"
gio mime x-scheme-handler/gemini probeU.desktop
gio open 'gemini://example.org/a b/ü?x=%20y&z=é#frag'
gio open "$t/a b.txt" 'gemini://example.org/mixed'
```

The socket test (a pytest function run with `APPJAIL_INTEGRATION=1`, not kept in the suite):
`run_in_jail(sandbox, runtime, script=SERVER, dirs=("~/e7dir:rw",))` in a thread, where `SERVER` is a Python script that
binds `/home/app/e7dir/sock`, accepts one connection, reads it and answers with its own pid and `SO_PEERCRED`; the test
waits for the socket file on the host, connects, sends a line and reads the reply.

The relay prototype, `relay.py` (run inside the jail as `python3 relay.py SOCKDIR /app/AppRun [ARGS]`; the app is its
child):

```python
import os, socket, subprocess, sys, threading
sockdir = sys.argv[1]; cmd = sys.argv[2:]
path = os.path.join(sockdir, "sock")
try: os.unlink(path)
except OSError: pass
srv = socket.socket(socket.AF_UNIX); srv.bind(path); os.chmod(path, 0o600); srv.listen(8)
app = subprocess.Popen(cmd)
def serve():
    while True:
        c, _ = srv.accept()
        data = b""
        while not data.endswith(b"\n") and len(data) < 4097:
            b = c.recv(4097)
            if not b: break
            data += b
        line = data.decode("utf-8", "replace").rstrip("\n")
        if len(data) > 4096 or any(ord(ch) < 32 for ch in line):
            c.sendall(b"refused\n"); c.close(); continue
        p = subprocess.Popen([cmd[0], line])          # AppRun and the link, nothing else
        c.sendall(b"ok\n"); c.close()
        threading.Thread(target=p.wait, daemon=True).start()
threading.Thread(target=serve, daemon=True).start()
rc = app.wait()
try: os.unlink(path)
except OSError: pass
sys.exit(rc)
```

The launcher is a Python script that replaces `runtimejail.runtime_args` with a wrapper putting
`/usr/bin/python3 /home/app/relay-NAME/relay.py /home/app/relay-NAME` before the command, copies `relay.py` into
`~/relay-NAME` and calls `runner.launch(NAME, extra_dirs=["~/relay-NAME:rw"])`. The client is five lines: connect to the
socket, send the link and a newline, print the reply.
