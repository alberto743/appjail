# Debuggers need the `devel` permission

*Decision on [isolation](index.md).*

**Context.** The seccomp filter always refuses `ptrace` and `perf_event_open`, and allows `personality` only for the two
values a normal program uses. A tracer or a debugger therefore cannot run in a jail. Measured in the test guests (Debian
13, Ubuntu 26.04, Fedora 45): `strace` stops with `PTRACE_TRACEME: Operation not permitted`, and `gdb` cannot trace
the program (it reports exit code 127). Flatpak lifts the same three calls with `--allow=devel`.

**Options.** Leave it; one permission as Flatpak has it (`ptrace`, `perf_event_open` and any `personality`); two
permissions, `ptrace` and `perf`; one permission with the narrower set below.

**Decision.** A permission `devel`, off by default, recorded in the manifest like the others. With it the jail's filter
allows `ptrace` and, besides the two values already allowed, the one value `PER_LINUX | ADDR_NO_RANDOMIZE`
(`0x0040000`), which is what `gdb` asks for to run a program at the same addresses every time. Everything else stays as
it was, `perf_event_open` and `process_vm_readv`/`process_vm_writev` included. Only the app's own jail gets it: the
helper jails (downloads, extraction, audio, the D-Bus proxy) never do.

- **The filter still applies to a tracer's own work.** A tracer can rewrite the system call a traced process is about to
  make. Measured with a process that rewrote its child's calls to `personality(ADDR_NO_RANDOMIZE)`, `io_uring_setup` and
  `mount`: the filter answered `EPERM`, `ENOSYS` and `EPERM`, on all three kernels (the filter runs after the tracer's
  stop). The jail's init process (pid 1) has the same filter, no capabilities and `no_new_privs`, so attaching to it
  gains nothing.
- **Only the jail's own processes are reachable.** The jail has a process namespace of its own and no capabilities, so
  the host's processes are not visible and processes of other users cannot be traced.
- **`perf_event_open` stays refused.** It could not work on the systems measured: Debian and Ubuntu set
  `perf_event_paranoid` to 3 and 4, which refuses it to an unprivileged process whatever the jail allows (the jail
  cannot change the sysctl), and on Fedora (2) `perf` finds no events because the jail has no `/sys`, which appjail does
  not bind (it lists hardware and kernel details). With `/sys` bound read-only, `perf stat -e cpu-clock:u` worked on
  Fedora; that is a separate decision. Flatpak's own source calls perf "the source of many CVEs". Kept out, it costs
  nothing measured.
- **One persona, not all.** `personality` can also set `MMAP_PAGE_ZERO` and `READ_IMPLIES_EXEC`, which weaken kernel and
  memory protections, and `ADDR_NO_RANDOMIZE` turns off address randomization for the app's own children. Allowing
  exactly `0x0040000` removed `gdb`'s warning "Error disabling address space randomization" and gave the same addresses
  on three runs on every guest; without it the program ran with randomization on, which only costs repeatable addresses.
- **`process_vm_readv` is not needed.** `gdb` started a program, attached to one and listed its memory map with the call
  refused.

**Rejected.** `perf_event_open` in the same permission (above); every `personality` as Flatpak allows (above); two
permissions, `ptrace` and `perf` (the second does nothing on the systems measured); leaving debuggers out (a crashing
app is hard to diagnose without them, and the points above show the cost of allowing them is small).

**Consequences.** Granting `devel` warns, like the other risky grants. What a debugger can attach to depends on the
host's Yama setting (`kernel.yama.ptrace_scope`): at 0 (Debian, and Fedora as last measured) it may attach to any
process of the jail, at 1 (Ubuntu) only to its own descendants, so `strace CMD` and `gdb PROG` work and `strace -p PID`
on an unrelated process fails with `Operation not permitted`. A debugger that asks you things needs the terminal as
well: `raw_terminal` or `appjail run --raw` ([terminal output](terminal-output.md)). `perf` is not supported.
