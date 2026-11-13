# bubblewrap

*Part of [Isolation](index.md). Previous: [namespaces](namespaces.md). Next: [the filesystem view](filesystem.md).*

## What it is

[bubblewrap](https://github.com/containers/bubblewrap) (`bwrap`) is a small program that starts another program in new
namespaces. It is the sandbox engine underneath Flatpak, and appjail uses it for every jail it starts.

bubblewrap has no configuration file and no policy of its own: everything is given as command-line options. It
creates the namespaces it is asked for, mounts an empty filesystem as the new root, adds to it exactly the paths it is
told to bind (each read-only or writable), mounts `/proc` and a minimal `/dev` if asked, drops capabilities, loads a
seccomp filter if given one, and finally runs the program. As its first process in the new PID namespace it stays
behind as a small init that reaps orphaned processes.

On systems that allow unprivileged user namespaces, which both supported systems do, bubblewrap runs as an ordinary
program, without the set-uid bit it once needed.

## Why it matters

A sandbox that needs root to start, or a daemon that runs as root, is itself a target: a flaw in its parsing of a
profile or of its arguments becomes a privilege escalation. bubblewrap does almost nothing beyond what the kernel
offers, has a small code base exercised by every Flatpak installation, and needs no privileges. It also has no
built-in idea of what a "safe" sandbox is, which is what appjail wants: the policy belongs to appjail, written in
Python, tested, and visible in one place (`jail.py` for the helper jails, `runtimejail.py` for the app jail).

## How appjail uses it

appjail builds each jail as a list of `bwrap` options. The ones that matter, and why:

| Option | Effect | Why |
|---|---|---|
| `--unshare-all` | new user, mount, PID, network, UTS, IPC and cgroup namespaces | the app's own view of everything ([namespaces](namespaces.md)) |
| `--share-net` | keep the network namespace bwrap was started in | only with `network` (inside `pasta`'s private namespace) or `network_host` |
| `--unshare-user --disable-userns` | no further user namespaces inside the jail | refuses nested namespaces, unless the app has `userns` |
| `--cap-drop ALL` | no capabilities, even inside the jail's own namespaces | the app holds no privilege at all |
| `--clearenv` | start with an empty environment | no variable of yours reaches the app: no tokens, no `SSH_AUTH_SOCK`, no session addresses. appjail then sets a short fixed list (home, path, language, time zone, display variables) |
| `--die-with-parent` | the jail is killed when appjail exits | no jail outlives the command that started it ([process lifetime](lifetime.md)) |
| `--new-session` | the app runs in a new terminal session | a program that shares your terminal's session can push characters into its input with the `TIOCSTI` request, typing commands into your shell after it exits |
| `--ro-bind`, `--symlink` | the system directories (`/usr`, `/bin`, `/lib`, ...) read-only | programs and libraries of the host are usable but not changeable ([the filesystem view](filesystem.md)) |
| `--bind-fd`, `--ro-bind-fd` | bind an already opened directory or file | grants are checked on the file really opened, so a path swapped for a symbolic link after the check changes nothing |
| `--tmpfs /tmp`, `--tmpfs /run`, `--proc`, `--dev` | empty private `/tmp` and `/run`, the jail's own `/proc`, a minimal `/dev` | no other program's sockets or files, no devices except the basic ones (`null`, `zero`, `full`, `random`, `urandom`, `tty`, a private `pts` and `shm`) |
| `--remount-ro /` | the root of the jail becomes read-only | nothing can be created outside the paths bound writable |
| `--seccomp FD` | load a [seccomp](seccomp.md) filter before running the app | refuses the kernel calls an app should not make |
| `--hostname appjail` | the host name inside the jail | your machine's name does not reach the app |
| `--json-status-fd`, `--block-fd` | report the jail's process id; hold the app until told to start | only with portals: the portal identifies the app by that process ([portals](#connections)) |

Every helper jail starts from a common base (`jail.common_args`: all namespaces, no nested user namespaces, no
capabilities, a cleared environment, the read-only system, a private `/tmp`) and adds only the one or two paths its
step needs. The app jail is built the same way with more inside.

appjail requires bubblewrap 0.10 or later, for `--bind-fd` and `--ro-bind-fd`. Both minimum supported systems ship a
newer version.

## Connections

- It creates the [namespaces](namespaces.md) and fills the mount namespace with [the filesystem view](filesystem.md).
- It loads the [seccomp](seccomp.md) filter but cannot apply [Landlock](landlock.md); appjail applies that with a small
  wrapper started before `bwrap`.
- With `network`, `bwrap` itself runs inside the private network namespace that `pasta` creates. `pasta` closes every
  file descriptor it did not open, so the seccomp filter and the granted paths cannot be passed to `bwrap` as open
  descriptors there; appjail opens them again inside that namespace and checks they are still the same files
  ([the filesystem view](filesystem.md#grants-are-bound-by-descriptor)).
- Portals identify an app by the process id `bwrap` reports, which is why `--json-status-fd` is used.
- Decision: [bubblewrap, not Firejail or sas](../../decisions/isolation/bubblewrap.md).

## Limits

- bubblewrap trusts its caller: it enforces whatever options it is given. The security of a jail is the security of
  appjail's options, which is why they are built in one place and tested.
- It cannot apply Landlock, and it has no notion of resource limits (memory, processes); an app can still exhaust
  memory or CPU.
- The app shares the terminal it was started from (standard input, output and error): it can read what you type there
  while it runs, and write control sequences to it ([untrusted text](../acquisition/untrusted-text.md#limits)).
- The system directories are bound read-only, not hidden: the app can read the programs and libraries installed on
  your system, and their configuration under `/usr`.

## References

- bubblewrap, [project page and README](https://github.com/containers/bubblewrap), and the
  [manual page source](https://github.com/containers/bubblewrap/blob/main/bwrap.xml) describing every option.
- Flatpak documentation, [Sandbox permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html).
- Linux manual page [ioctl_tty(2)](https://man7.org/linux/man-pages/man2/ioctl_tty.2.html), `TIOCSTI`: faking input on
  a terminal.
