# Landlock for abstract sockets only

*Decision on [isolation](index.md).*

**Context.** An app with `network_host` shares your network namespace and so every abstract unix socket of your
session, including the X server's, which lets any client read keystrokes and inject input. The mount namespace cannot
hide them.

**Options.** Refuse `network_host` outright; Landlock's filesystem and network rules as well as the scope; the
abstract-socket scope alone.

**Decision.** The abstract-socket scope (ABI 6, Linux 6.12) on every app jail not behind `pasta`, applied by a wrapper
in front of bubblewrap. Without ABI 6, `network_host` is refused. The filesystem rules would repeat the mount
namespace; the network rules cover only TCP ports and would add nothing to the private network namespace while
breaking apps that need other ports; signal scoping adds nothing to a private PID namespace. Behind `pasta` it is not
needed, and not possible: `pasta` refuses to run its command under `no_new_privs`.

**Revisit when** a network jail starts running third-party code, bubblewrap gains Landlock support, or an allowlisting
proxy for the network is wanted.
