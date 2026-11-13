# A seccomp deny list

*Decision on [isolation](index.md).*

**Context.** A filter must cut the kernel interfaces that desktop apps do not need, without breaking the many that they
do through toolkits and libraries.

**Options.** An allow list per app (precise, but fragile and opaque when it breaks an app); a single deny list.

**Decision.** One deny list for every jail, following Flatpak's (so an app that works there works here), plus
`io_uring`, answered with `ENOSYS` so libraries fall back, and the refusal of nested namespaces unless the app has
`userns`. The filter is written in Python without a library, and its system-call numbers are checked against the
kernel's header by the tests.

**Consequences.** Apps that need Bluetooth or raw sockets, or `io_uring`, lose that function. Other architectures need
their own table; until then appjail refuses to run on them.

**Revisit when** another architecture is supported.
