# Grants bound by descriptor

*Decision on [isolation](index.md).*

**Context.** bubblewrap resolved each granted path again when binding it, after appjail had checked it. A process of
yours, or an app with a writable grant, could swap a component of the path for a symbolic link in between; a test
showed an app reading a file it was refused this way. The severity is low (the attacker already runs as you, or holds a
writable grant), but it was a hole in the jail's own boundary. Flatpak had the same flaw (CVE-2024-42472), fixed by
bubblewrap's `--bind-fd` in version 0.10.

**Options.** Bind `/proc/self/fd/N` instead of the path; compare the inode again just before starting bubblewrap (a
window remains); walk each component with `openat2`; open once, check what was opened, bind the descriptor.

**Decision.** Each grant is opened once, every check is made on the opened file, and bubblewrap binds the descriptor.
Behind `pasta`, which closes inherited descriptors, a wrapper opens each path again inside the namespace and refuses to
start unless device and inode match what was checked. Checking after the open makes walking each component
unnecessary: a swapped component changes what is opened, and that is what gets judged.

**Consequences.** bubblewrap 0.10 or later is required; both minimum systems have it. A `dirs` entry that names a
regular file is refused (`--file` is the way to grant one file).
