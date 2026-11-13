# Network

*Part of [Desktop access](index.md). Previous: [GPU and camera](devices.md). Next: [menu entries and opening files](menu-entries.md).*

## What it is

A **network namespace** gives its processes their own network interfaces, routes, ports and abstract unix sockets. A new
one contains only a loopback interface that leads nowhere else: no network at all. To give it the internet, something
has to carry its traffic out. **pasta** (from the `passt` project) does this without privileges: it creates a network
namespace, presents an ordinary interface inside it, and turns the connections made there into ordinary sockets of your
user outside, so no routing or firewall configuration of the host is involved.

## Why it matters

An app that needs the internet would otherwise get your whole network: including the services that listen only on your
machine (`localhost` databases, development servers, local admin interfaces, printing), which often assume that only you
can reach them, and the abstract unix sockets of your session, such as the X server's.

## How appjail uses it

- **No network by default.** The app jail has its own empty network namespace.
- **`network`**: the app runs in a private namespace made by `pasta`, with outbound TCP and UDP, IPv6 where your host has
  a route, and name resolution through a forwarder address. Your machine's loopback and its own addresses are not
  reachable from inside, and nothing is forwarded in. Without `pasta`, an app with `network` is refused, never put on
  your network.
- **`network_host`** (it implies `network`): the app shares your network namespace, for apps that need local services.
  Your abstract unix sockets are then reachable by name, so [Landlock](../isolation/landlock.md) refuses connections to
  those created outside the jail; without Landlock (Linux 6.12) this permission is refused.
- **The download jails** use the same `pasta` namespace. Without `pasta` they use the host network, with a warning, which
  is why `passt` is listed among the packages to install.

## Connections

- `pasta` closes inherited file descriptors and runs its command as root of a user namespace, which is why the seccomp
  filter, the granted paths and the user ids are handed over inside it ([the filesystem view](../isolation/filesystem.md#grants-are-bound-by-descriptor)),
  and why a lifeline ends the jail if appjail is killed ([process lifetime](../isolation/lifetime.md)).
- Decision: [Network through pasta](../../decisions/desktop/network.md).

## Limits

- Other machines on your local network are reachable with `network`. Keeping apps off them is not a goal; an allowlisting
  proxy is deferred.
- IPv6 over a real internet route has been tested only on a simulated network.

## References

- passt and pasta, [project site](https://passt.top/) and [about](https://passt.top/passt/about/); Debian manual page
  [pasta(1)](https://manpages.debian.org/trixie/passt/pasta.1.en.html).
- Linux manual page [network_namespaces(7)](https://man7.org/linux/man-pages/man7/network_namespaces.7.html).
