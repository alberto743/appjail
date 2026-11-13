# Landlock and abstract sockets

*Part of [Isolation](index.md). Previous: [seccomp](seccomp.md). Next: [process lifetime](lifetime.md).*

## What they are

**Unix sockets** are how most programs on a desktop talk to each other: the display server, the session bus, the
audio server, agents. A unix socket normally has a path in the filesystem (`/run/user/1000/bus`), and a process can
connect to it only if it can see that path. Linux also has **abstract** unix sockets, whose name starts with a zero
byte and exists in no filesystem at all (written `@name`). They belong to the *network namespace* of the process
that created them, and any process in the same network namespace can connect to one by name.

**Landlock** is a Linux security module that an unprivileged process can apply to itself. The process describes what it
will still need (which files and directories, which TCP ports, and since ABI version 6 which *scopes*) and enters a
Landlock domain; from then on the kernel refuses everything else, for it and every process it starts. Each kernel
version supports an ABI version; ABI 6 (Linux 6.12) added the scope
`LANDLOCK_SCOPE_ABSTRACT_UNIX_SOCKET`: a process in the domain may not connect to an abstract unix socket created
outside it.

## Why it matters

A [mount namespace](namespaces.md) hides every socket that has a path, because the path does not exist in the jail.
It does nothing for abstract sockets: those are visible to whatever shares the network namespace. An app jail normally
has a network namespace of its own, so it shares no abstract socket with your session. An app with the `network_host`
permission is different: it keeps your network namespace, so it can reach your machine's services, and with them every
abstract socket of your session.

The dangerous one is the X server's. X servers, Xwayland included, listen on an abstract socket
(`@/tmp/.X11-unix/X0`), and desktops commonly let any process of the user connect to it. An X11 client can read the
keys typed into every other X11 window, capture their contents and send them input. On a Wayland session, every X11
app runs on that server.

## How appjail uses it

appjail uses exactly one part of Landlock: the abstract-socket scope. On a kernel with ABI 6 or later, every app jail
that is not behind `pasta` runs in a Landlock domain with that scope and no other rule. Connections to abstract sockets
created inside the jail keep working, which matters for the private Xwayland that appjail starts *inside* the jail for
X11-only apps.

bubblewrap cannot apply Landlock, so appjail starts a small wrapper (`landlock.py`, run by `python3 -I`) in front of
`bwrap`. The wrapper sets `no_new_privs`, which an unprivileged process must set before it can enter a Landlock domain,
enters the domain, and replaces itself with `bwrap`. It is a separate process rather than code run between `fork` and
`exec` in appjail itself, which is unsafe in a program that uses threads.

| The app has | Its network namespace | Landlock |
|---|---|---|
| no network | its own, empty | applied as a second layer, where the kernel has ABI 6 |
| `network` | a private one made by `pasta` | not applied: the private namespace already isolates abstract sockets, and `pasta` refuses to start its command under `no_new_privs` |
| `network_host` | yours | **required**: without ABI 6 the app is refused, both when the permission is granted and when the app starts |

## Connections

- The [network namespace](namespaces.md) is what normally isolates abstract sockets; Landlock covers the one case where
  the app shares yours.
- [The filesystem view](filesystem.md) refuses `/tmp` as a grant for the same reason with path sockets: seeing a socket
  is enough to connect to it.
- The private Xwayland for X11-only apps runs inside the jail, so it stays reachable under the scope, while the host's X
  server does not.
- Decision: [Landlock for abstract sockets only](../../decisions/isolation/landlock.md).

## Limits

- Only the abstract-socket scope is used. Landlock's filesystem rules would repeat what the mount namespace already
  does, and its network rules cover only TCP `bind` and `connect` by port number (no UDP, no host names), which adds
  nothing to the private network namespace and would break apps that need other ports.
- On a kernel older than 6.12, or with Landlock disabled, apps without `network_host` still run, protected by their own
  network namespace; apps with it are refused.

## References

- Linux kernel documentation, [Landlock: unprivileged access control](https://docs.kernel.org/userspace-api/landlock.html);
  manual page [landlock(7)](https://man7.org/linux/man-pages/man7/landlock.7.html); project site
  [landlock.io](https://landlock.io/).
- Linux kernel documentation, [No New Privileges Flag](https://docs.kernel.org/userspace-api/no_new_privs.html).
- Linux manual page [unix(7)](https://man7.org/linux/man-pages/man7/unix.7.html), section "Abstract sockets".
- X.Org Foundation, [Access control and authentication in X](https://www.x.org/wiki/Development/Documentation/Security/): ordinary ("trusted") clients can read other clients' windows and input.
