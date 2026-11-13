# Network through pasta

*Decision on [desktop access](index.md).*

**Context.** An app that needs the internet should not, for that, reach the services listening on your own machine
(a database on `localhost`, a development server), nor share your network namespace and the abstract sockets in it.
Unprivileged users cannot configure a network namespace's interfaces themselves.

**Options.** Share the host network; build a private namespace with a host-side proxy on a unix socket plus a relay
inside the jail (new code on the path of every download, and `git` and `gh` speak no proxy over unix sockets); use
`pasta` (package `passt`), which gives a private namespace with ordinary outbound sockets, unprivileged.

**Decision.** `pasta`. With `network`, the app runs in a private namespace where outbound TCP and UDP work and the
host's loopback and own addresses are unreachable; DNS goes through a forwarder address, and nothing is forwarded into
the namespace. Without `pasta` an app with `network` is refused, never put on the host network. The download jails use
the same mechanism; without `pasta` they fall back to the host network with a warning, which is why `passt` is listed
among the packages to install. `network_host` keeps the host network for apps that need local services, and then
requires Landlock.

**Consequences.** Other machines on your LAN remain reachable: attacks on them are outside the threat model, whose aim
is to keep apps off your own machine's services. `pasta` closes inherited file descriptors and runs its command as
uid 0 of a user namespace, which is why the seccomp filter, the granted paths and the user ids are handed over inside
its namespace.

**Revisit when** host filtering for `network` is wanted (an allowlisting proxy for the LAN is deferred).
