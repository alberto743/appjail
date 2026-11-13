# Extract, never mount

*Decision on [isolation](index.md).*

**Context.** An AppImage normally mounts its embedded filesystem with FUSE and runs from the mount. FUSE does not work
well inside user namespaces, and running the AppImage's runtime means running its code before anything is known about
it.

**Decision.** appjail never mounts an AppImage and never runs its runtime outside a jail. It extracts the embedded
SquashFS with `unsquashfs`, starting at the offset where the ELF runtime ends, in a jail with no network; DwarFS images
use a pinned extractor in the same jail. Only when `unsquashfs` is missing, and only after asking, does it run the
AppImage's own `--appimage-extract`, inside that jail. The extracted tree is validated, hashed and checked before every
start.

**Consequences.** Disk space for an extracted copy of each app, and the time to extract it once per version. In return
the tree can be checked file by file, and a change to it is noticed at the next start.
