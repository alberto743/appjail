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
- **The relay** runs only for an app with at least one scheme: the app's command runs under a small Python supervisor,
  started in the jail by the system interpreter like [`linger`](../isolation/lifetime.md), which starts the app as its child
  and forwards the stop signals to it. It reads one link per line from a FIFO. For each good link it starts `AppRun LINK` in
  the jail (the link as the only argument), so the app's own single-instance handover finds the running instance, and it
  reaps the helpers. It waits until the app has run for a second before the first delivery. A link is at most 4000
  bytes, so a line is written to the pipe atomically.
- **The FIFO** is a node in appjail's private run directory (`~/.local/share/appjail/run/NAME.link`, directory mode 700),
  created by the launch and held open by it until the launch ends. Only that node is bound into the jail, not a
  directory, so the app never sees anything it could swap, and the host never follows a path the app controls. A client can
  open the FIFO for writing only while a launch holds it, so it tells a running app from a leftover node (a FIFO nobody
  reads is replaced by the next launch); a link written while the app starts waits in the pipe. A second launch of the
  same app, while one holds the FIFO, runs without a relay. The check and the creation happen under an exclusive lock on the
  run directory, so two launches started together cannot each replace the other's new FIFO.
- **The client** is `appjail open`. Given only links, it writes them to the FIFO when a launch holds it and says so; when
  none does, it starts the app with the links as its arguments after `--`. Given files, it starts the app as before: a
  file is bound into a jail when the jail starts, so a running app cannot be given one, and the gap for files stays.
  The client reports no delivery failure of the relay itself: there is no reply channel (the relay logs a refused link to
  the app's error output).
- **Checked twice.** The host checks the link against the app's list (scheme compared in lower case), the length in bytes,
  the control characters and a leading `-`; the supervisor checks the scheme, the length and the control characters again,
  since the app can also write to the FIFO (through its own mount of it).

With `linger` the relay is the outer supervisor and `linger` the inner one, so `linger` counts as infrastructure everything
that was running when it started (the relay, the script that starts a private Xwayland and what they started) when it
looks for processes still running; counting the relay, or an Xwayland that is no longer its child, would keep the jail
alive for ever (both found by combination tests). `linger` still waits for what the app leaves behind.

A first prototype used a socket in a directory bound into the jail and was changed: the app could have replaced the socket
by a symbolic link that the host client would then follow. Measured with the prototype, on Debian, Ubuntu and Fedora: the running Electron probe received each link byte for byte, no second
instance started, and the relay and its helpers kept the jail's seccomp filter and `NoNewPrivs`. Lagrange, run on Debian
only, handed the links over to its running process.

**Consequences.** The app can already run anything inside its own jail, so a FIFO it can write to gives it nothing new;
what the FIFO adds is that any process of the same user can send the app a link, which the desktop's own handler does
anyway. The relay cannot tell callers apart. A FIFO left by a killed launch has no reader and is replaced at the next
start. A link that arrives before the app has written its own
lock may start the first instance from the helper; Chromium's lock is atomic, Lagrange's `.pid` file is not. An app that
leaves a pid file in its home after an unclean end can still fail to start, whatever the relay does. KDE and Cinnamon,
a real click and the choice of default handler by the desktop were not measured; they are listed under "Not yet verified".

KDE's launcher rewrites a link before it reaches the entry (it decodes `%20` and encodes `"`; GLib passes it unchanged), so the
link an app receives is not always the one that was clicked ([measured](../../develop/url-handler-evidence.md#kdes-and-cinnamons-launchers-measured-debian-13-with-kde-frameworks-6)).

An app whose own single-instance check does not work in a jail gets nothing from the relay: Joplin finds its running
instance through an HTTP server on `localhost`, needs `network` for the name to resolve and still starts a second instance
for about one link in four ([measured](../../develop/url-handler-evidence.md#a-real-electron-application-joplin-measured-debian)).

A link that is not valid text (a lone surrogate, which argv cannot hold but JSON can) is refused like any bad link.

Two weaknesses are known and open ([deferred](../deferred.md)): the launch holds the FIFO open itself, so a link sent after
the relay or the app died is accepted and only waits in the pipe (a full queue is reported after about 64 kB); and the
relay starts a helper for every good link with no limit (1500 links in a flood made 136 at once).

**Revisit when** the desktop portals offer a way to deliver a link to a sandboxed app that works for AppImages, or an app
needs a link delivered by a different command than `AppRun LINK`.
