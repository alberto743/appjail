# URL handlers and a second launch: the evidence

Working notes, not a specification: the open question is on [deferred work](../decisions/deferred.md) (row "URL
handlers"); no decision has been taken and no code written. Written in November 2026 from experiments in the qemu guests.
"Measured" means a command or test ran in a guest; "read" means documentation only; "not done" means neither. Nothing
here was run on the maintainer's own machine. The scripts are at the end so each run can be repeated.

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

Read, in the [Desktop Entry Specification](https://specifications.freedesktop.org/desktop-entry-spec/latest/exec-variables.html)
(version 1.5; the address redirects to `specifications.freedesktop.org/desktop-entry/latest/`): `%u` "a single URL", `%U`
"a list of URLs. Each URL is passed as a separate argument to the executable program", and for both "local files may either
be passed as file: URLs or as file path", so a handler has to be ready for both. Quoting in `Exec` is done by double quotes with
backslashes before `"`, `` ` ``, `$` and `\`; a literal `%` is `%%`; at most one of `%f %u %F %U` per command line, and
`%F` and `%U` only "as an argument on their own". The page does not mention `x-scheme-handler`, and the page that defines
`MimeType` does not either; the MIME registration page was not read. Not done: KDE Plasma (KIO) and Cinnamon launchers; the
specification leaves them free to pass `file:` URLs for local files.

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

`.config/lagrange/.pid` held `2` and was dated 19 November, probably left by an earlier end-to-end run that ended the app
by a signal (not verified). With it present, **every** launch of Lagrange found "another instance" (pid 2 exists in the new
jail: itself), tried the signal handover and exited at once; the window never appeared. Moving the file aside restored
normal starts. This is independent of URL handlers: any app that keeps a pid file in its persistent home will do this after
an unclean end, because every jail has its own pid namespace and the numbers repeat.

## A second launch of a running app: an Electron probe (measured)

Chromium's single-instance lock (`app.requestSingleInstanceLock()`, which Electron apps use) is a symlink `SingletonLock`
named `HOSTNAME-PID` in the user-data directory (here the shared private home), plus a unix socket under `/tmp`
(`SingletonSocket`, private to each jail) and a `SingletonCookie`.

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
reads `appjail-2` (the hostname inside the jail is `appjail`). The second jail finds a lock that names its own pid, takes
it as stale and replaces it. Result: two full instances of the app run on **one profile directory**, and the first
instance's lock, cookie and socket were overwritten by the second's. Neither can receive anything from a later launch.
Corruption of the profile was not measured; it is the risk this implies for databases such as IndexedDB and LevelDB.
The URL handed to the second jail is not lost (it is its own first instance's argument), but nothing reaches the app the
user was already using.

E3 in the same jail: the first instance logs the full command line of the second, with the URL byte for byte
(`appjailprobe://second/a b?x=1&y="q"`, spaces, `&` and quotes intact); Electron added `--allow-file-access-from-files` to
it. The second exits 0 at once. This is Chromium's design working as intended.

The sandbox rows: appjail clears set-id bits when it checks an extracted tree, so Electron's `chrome-sandbox` helper can
never be set-uid in a jail. The sandbox then needs the `userns` grant or `--no-sandbox`. Ubuntu 26.04 refused the
namespace sandbox even with the grant (not investigated); `--no-sandbox` was used for the Ubuntu rows above, with `userns`
denied.

## A socket from the host into a jail (measured, all three guests)

A directory granted with `dirs = ["~/e7dir:rw"]` is bound into the jail at `/home/app/e7dir`. A process inside the jail
bound a unix socket there; the host connected to the same path, sent `open appjailprobe://x` and received a reply. It
worked on Debian, Ubuntu and Fedora. Seen from inside the jail the host peer's pid is `0` (another pid namespace) and its
uid is the user's, so a service in a jail could tell callers apart by user and directory permissions, not by process.

## Not measured

- KDE Plasma and Cinnamon launchers (how they quote and what they pass for local files and URLs under `%U`), and a real
  click in a full desktop session.
- A real Electron application (login flows, its own protocol registration); only a probe was used.
- Profile corruption by two instances on one profile.
- Why the Chromium namespace sandbox did not start on Ubuntu 26.04 with `userns` granted.
- Whether the desktop's own default-handler choice (`xdg-mime default`) behaves the same with appjail's entries; the stand-in
  entries were registered directly with `gio mime`.
- Lagrange's single-instance code (not read; its behaviour was observed).

## What the evidence says

- The URL arrives as one argument, unchanged and unlimited, and may carry any scheme case; an app launcher must check it
  itself (registered scheme compared in lower case, length, control characters, placed after `--`).
- Starting a **new jail** per link is wrong for single-instance apps: Lagrange loses the URL and exits silently, and
  Chromium apps start a second instance on the same profile. The same holds today for files opened with `appjail open`.
- Handing the link to a process **inside the running jail** works for both apps, because their own handover logic then
  sees the running instance. A host process cannot join a jail without the jail's seccomp filter and Landlock domain.
- A relay inside the jail that the host reaches through a socket in a granted directory is feasible on all three guests;
  it cannot identify callers by pid.

## Scripts

The probe's `main.js` (the whole app: a `package.json` with `{"name": "appjail-probe", "main": "main.js"}`, an `AppRun` of
`exec "$here/electron/electron" $PROBE_FLAGS "$here/app" "$@"` and a `.desktop` file with
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

E3 and the Lagrange case C, a second process inside the first jail: a Python script that imports `appjail.runner`, replaces
`runner._run_app` with a wrapper that swaps the jail's start command (everything from `/app/AppRun`) for
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

The socket test (a pytest function run with `APPJAIL_INTEGRATION=1`, not kept in the suite): `run_in_jail(sandbox, runtime,
script=SERVER, dirs=("~/e7dir:rw",))` in a thread, where `SERVER` is a Python script that binds `/home/app/e7dir/sock`,
accepts one connection, reads it and answers with its own pid and `SO_PEERCRED`; the test waits for the socket file on the
host, connects, sends a line and reads the reply.
