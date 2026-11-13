# x86-64, Debian 13 and Ubuntu 26.04

*Decision on [the project](index.md).*

**Context.** Several mechanisms are tied to an architecture or to a minimum version of the kernel and of bubblewrap:
the seccomp filter's system-call numbers, Landlock's abstract-socket scope (Linux 6.12), `--bind-fd` (bubblewrap 0.10).
Supporting older systems would mean workarounds in exactly the code that must be simplest to review.

**Decision.** Linux on x86-64 only, with Debian 13 and Ubuntu 26.04 (the CI runner's system) as the minimum supported
systems, and Python 3.12 or later. No workarounds for older systems. On another architecture `run` refuses rather
than run without its seccomp filter.

**arm64: evaluated, paused.** Feasible and moderate in code, expensive to verify. The architecture is hard-wired in the
seccomp table (other numbers, no x32, missing legacy calls), in the asset selection by name, in the two pinned tools and
in the catalog. A wrong system-call number either leaves a hole or denies a needed call, so every name must be checked
against the kernel's table and tested natively. An arm64 guest on an x86 host runs emulated, five to twenty times
slower, and real arm64 AppImages need new approvals. If resumed: an architecture-aware core first (no change on x86),
then an arm64 guest, the tool pins and an arm64 catalog, a real AppImage test, and an arm CI job if a runner exists.

**Revisit when** the arm64 work is resumed.
