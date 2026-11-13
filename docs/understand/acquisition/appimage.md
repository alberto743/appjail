# The AppImage format

*Part of [Acquisition](index.md). Next: [sources and the resolver](sources.md).*

## What it is

An **AppImage** is a single executable file that carries an application and the libraries it needs, so that it runs on
many distributions without being installed. A type 2 AppImage, the current format, has two parts glued together:

1. a small **runtime**: an ordinary ELF executable, the part that runs when you start the file;
2. a **filesystem image** appended right after it, normally SquashFS (a compressed, read-only filesystem), in some newer
   AppImages DwarFS.

When you run an AppImage directly, the runtime mounts the appended filesystem with FUSE and starts the program
`AppRun` at its root. The file is marked by the bytes `AI` followed by the type number (2) at offset 8 of its ELF
header. It may also carry *update information*, which tells an updater where to find the next version, and a digital
signature section.

## Why it matters

Running an AppImage means running its runtime first: code from the download, before anything inside it has been looked
at. Mounting with FUSE from inside a user namespace is unreliable, and a mounted image is read from the file on every
access, so nothing guarantees that what runs is what was checked. The embedded update information would let the
software decide where its next version comes from.

## How appjail uses it

appjail treats the file as data:

- **Recognition.** The file must be a 64-bit little-endian ELF with the `AI` marker and type 2; type 1 and anything else
  are refused.
- **Locating the filesystem.** The end of the runtime is computed from the ELF header (where the section table ends:
  `e_shoff + e_shentsize × e_shnum`). The bytes there must start a SquashFS (`hsqs`) or a DwarFS (`DWARFS`) image.
- **Extraction, not mounting.** SquashFS is unpacked by `unsquashfs` from that offset, in a jail without network
  ([jailed extraction](jailed-steps.md)). DwarFS is unpacked by a pinned extractor in the same jail. Only when
  `unsquashfs` is not installed, and only after you agree, does appjail run the AppImage's own extractor
  (`--appimage-extract`), and then inside that jail.
- **The entry point.** `AppRun` must resolve, through relative links that stay inside the tree, to an executable regular
  file. The app is started as `/app/AppRun` inside its jail.
- **The update information is ignored.** The source is the one you named
  ([principle 3](../principles.md#3-you-name-the-one-source)).

## Connections

- The download is checked as an AppImage before extraction: [hashes and evidence](evidence.md).
- The extracted tree is validated and hashed, and checked again before every start:
  [the filesystem view](../isolation/filesystem.md#the-extracted-tree).
- Decision: [Extract, never mount](../../decisions/isolation/extraction.md).
- Decision: [Helper tools pinned in the source](../../decisions/acquisition/pinned-tools.md) (the DwarFS extractor).

## Limits

- Type 1 AppImages, 32-bit runtimes and filesystems other than SquashFS and DwarFS are not supported.
- An extracted copy takes disk space next to the AppImage itself, which is kept so the tree can be rebuilt from verified
  bytes.
- The AppImage's own embedded signature is not checked; the evidence comes from GitHub instead
  ([evidence tiers](evidence.md)).

## References

- AppImage project, [AppImage specification (draft)](https://github.com/AppImage/AppImageSpec/blob/master/draft.md):
  type 2 format, magic bytes, update information.
- AppImage documentation, [Architecture](https://docs.appimage.org/reference/architecture.html) and
  [FUSE](https://docs.appimage.org/user-guide/troubleshooting/fuse.html).
- Linux manual page [elf(5)](https://man7.org/linux/man-pages/man5/elf.5.html): the header fields used to find the end
  of the runtime.
- [squashfs-tools](https://github.com/plougher/squashfs-tools) (`unsquashfs`) and [DwarFS](https://github.com/mhx/dwarfs).
