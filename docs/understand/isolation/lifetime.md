# Process lifetime

*Part of [Isolation](index.md). Previous: [Landlock](landlock.md). Next: [resource limits](resource-limits.md).*

## What it is

A jail exists as long as a process lives in its namespaces. Its first process (bubblewrap's small init, process 1 of the
jail's PID namespace) holds it together; when that process exits, the kernel kills every other process in the
namespace. The question this page answers is when that happens: when the app exits, when appjail is stopped, and when
appjail itself is killed without a chance to clean up.

## Why it matters

A sandboxed app that keeps running after you closed it, or after the command that started it was stopped, is a process
nobody watches. For an app with `network` the risk is concrete: the jail is started inside a network namespace that
`pasta` provides, and stopping `pasta` does not stop what runs inside it. The opposite failure matters too: an app whose
launcher starts the real program in the background and exits would be killed the moment its launcher returns.

## How appjail uses it

- **The app ends, the jail ends.** By default the jail lives as long as the command it was started with (`AppRun`).
  When that command exits, appjail kills whatever is left in the jail's process group. Closing an app closes everything
  it started.
- **Stopping appjail stops the app.** The app runs in a session and process group of its own (bubblewrap's
  `--new-session`). `SIGINT` (Ctrl-C), `SIGTERM` and `SIGHUP` sent to appjail are forwarded to the whole group, so
  `pasta` and the jail behind it stop together.
- **Killing appjail stops the app.** `SIGKILL` cannot be caught. Without `pasta`, bubblewrap's `--die-with-parent`
  ends the jail with its parent. Behind `pasta` that option does not reach the jail, so appjail gives the jail a
  *lifeline*: a pipe whose writing end only appjail holds. A small watcher inside the jail's namespace reads it; when
  appjail dies, the pipe closes, and the watcher kills every process of the namespace (it acts only if it is process 1
  of a private PID namespace, so it can never reach anything outside).
- **Helper processes die with the app.** The D-Bus proxy, the private audio graph and the portal identity are started
  for the app and stopped when it ends; each of them also dies with appjail.
- **An app's files stay while it runs.** Every launch holds a shared lock on the app (`locks/NAME.run`) from the moment
  its tree is ready until the jail ends; the kernel drops it when appjail exits, however it exits. `remove` and `reset`
  refuse while any launch holds it, and so does an update when it comes to replace the tree (the running jail binds the
  old one, which is then deleted), so a running app never loses its files under it. Changes to the files themselves (an
  update swapping the tree, a launch extracting it, a removal) take turns through a second, exclusive lock
  (`locks/NAME.lock`): a command that finds it taken waits up to a minute, then gives up with a message.

### Apps that detach: `linger`

Some launchers start the real app as a detached child and exit at once (VSCodium's does). Under the default rule the
jail, and the app with it, would end immediately. The `linger` permission changes the rule for one app: the command runs
under a small supervisor inside the jail that becomes the *subreaper* of the jail (detached processes are re-parented to
it rather than to process 1) and exits, with the command's exit status, only when no process of the app is left. The
supervisors that run it (the link relay below) wait for it, so they are not counted as processes of the app. It
grants nothing: it only changes when the jail ends.

### Apps that receive links: the relay

An app granted URL `schemes` also runs under a supervisor, which reads links from a FIFO that the launch holds open and
starts `AppRun LINK` inside the jail for each, so a single-instance app hands the link to the instance already running
(a second jail could not: it has its own PID namespace). The FIFO is closed with the launch. With `linger` the relay is the
outer supervisor and stays until `linger` ends. Decision:
[Links reach a running app through a relay](../../decisions/desktop/url-handlers.md).

## Connections

- The [PID namespace](namespaces.md) is what makes "every process of the jail" a well-defined set.
- `pasta` and its private network namespace are why the lifeline exists.
- [bubblewrap](bubblewrap.md)'s `--die-with-parent` and `--new-session` are the first two mechanisms above.
- Decision: [The jail ends with its command](../../decisions/isolation/lifetime.md).
- Decision: [No change under a running app](../../decisions/isolation/app-lock.md).

## Limits

- After `SIGKILL`, small directories and files that appjail made in your runtime directory (`$XDG_RUNTIME_DIR`: sockets,
  the lifeline pipe, the seccomp filter of an app behind `pasta`, the portal identity) stay until you log out, when the
  runtime directory is emptied.
- With `linger`, an app that leaves a process behind (a crash reporter, a background service of its own) keeps
  `appjail run` from returning until that process exits. Ctrl-C still ends everything.
- An update of a running app downloads and checks the new version, then fails before replacing anything; a candidate
  in quarantine stays pending, and `update` installs it once the app is closed.
- Extracting a large app can hold the exclusive lock for longer than a minute, so a command started meanwhile on the
  same app gives up and has to be repeated.

## References

- Linux manual pages [pid_namespaces(7)](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html) (the init process
  of a namespace and what happens when it exits) and [prctl(2)](https://man7.org/linux/man-pages/man2/prctl.2.html)
  (`PR_SET_CHILD_SUBREAPER`, `PR_SET_PDEATHSIG`).
- passt and pasta, [project site](https://passt.top/).
