# Links reach a running app through a relay

*Decision on [desktop access](index.md).*

**Context.** [Menu entries](menu-entries.md) never carry an app's `x-scheme-handler/` types, so a link clicked anywhere on
the desktop never opens a jailed app. Users want it for browsers, chat clients and login callbacks, and all of these are
single-instance programs. The [measurements](../../develop/url-handler-evidence.md) show three things. The desktop hands
a link over as one unchanged argument, with any length and any scheme case, so the launcher has to check it. A second
jail started for a link cannot reach the app already running: every jail has its own pid namespace, Lagrange loses the
link and exits 0, and Electron starts a second instance on the same profile. A process started inside the running jail
does reach it, and a host process can talk to one through a unix socket in a granted directory. `appjail open` has the
same gap for files.

**Options.**

- **A. Refuse while running.** Offer the schemes, and when the app is running report that the link was not delivered.
  Nothing new to trust, but the usual case (an app that is already open) never works.
- **B. A new jail per link.** The simplest, and it loses the link or runs two instances on one profile.
- **C. A relay inside the running jail.** Described below.
- **D. Do nothing.** Keep the entries without links and document the gap.

**Decision.** C, opt-in for each app and each scheme.

- **The opt-in** is a list in the manifest, `schemes`, set with `perms --add-scheme S` and `--rm-scheme S` (the names the
  other lists use) and at `add --scheme S`; at most 16, each `[a-z][a-z0-9+.-]{0,31}`, never `file`. Whether the app's own
  menu entry declares `x-scheme-handler/S` is checked when the entry is written, not when the scheme is granted (the tree
  may not be extracted yet): `appjail desktop` writes the types that are both granted and declared, and says which granted
  scheme the app does not declare. The entry's command is
  `appjail open NAME -- %U`. `inode/` and every scheme not in the list stay refused, and appjail still never makes an app
  the default for anything.
- **The relay** runs only for an app with at least one scheme, as pid 2 of its jail; the app is its child. It listens on
  a unix socket in `~/.local/share/appjail/run/NAME/` (mode 700, the socket 600), bound read-write at a fixed path in the
  jail; its script is bound read-only from the package, not from a directory the app can write. For each line it reads
  (at most 4096 bytes, no control characters) it runs `AppRun` with that line as the only argument, so the app's own
  single-instance handover finds the running instance. It answers `ok` or `refused`, reaps its helpers and removes the
  socket when the app ends.
- **The client** is `appjail open`. It tests the app's `NAME.run` lock: when it is free the app is started with the link
  or file as its argument after `--`; when it is held the client connects to the socket, retrying for a few seconds while
  the app starts, and shows a notification if the link could not be delivered. Files take the same path, which closes the
  gap for `appjail open` too.
- **Checked twice.** The host checks the link against the app's list (scheme compared in lower case), the length, the
  control characters and a leading `-`; the relay checks length and control characters again, since the app can write to
  the socket too.

Prototype results, on Debian, Ubuntu and Fedora: the running Electron probe received each link byte for byte, no second
instance started, and the relay and its helpers kept the jail's seccomp filter and `NoNewPrivs`. Lagrange, run on Debian
only, handed the links over to its running process.

**Consequences.** The app can already run anything inside its own jail, so a socket it can write to gives it nothing new;
what the socket adds is that any process of the same user can send the app a link, which the desktop's own handler does
anyway. The relay cannot tell callers apart (the peer's pid is 0 across namespaces). A stale socket after a killed jail
shows as a refused connection and is replaced at the next start. A link that arrives before the app has written its own
lock may start the first instance from the helper; Chromium's lock is atomic, Lagrange's `.pid` file is not. An app that
leaves a pid file in its home after an unclean end can still fail to start, whatever the relay does. KDE and Cinnamon,
a real click and the choice of default handler by the desktop were not measured; they are listed under "Not yet verified".

**Revisit when** the desktop portals offer a way to deliver a link to a sandboxed app that works for AppImages, or an app
needs a link delivered by a different command than `AppRun LINK`.
