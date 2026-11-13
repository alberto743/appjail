# Jailed download and extraction

*Part of [Acquisition](index.md). Previous: [build attestations](attestations.md). Next: [untrusted text](untrusted-text.md).*

## What it is

Before an app runs, two steps handle its bytes while nothing is yet known about them: the **download**, which talks to a
server that could misbehave, and the **extraction**, which unpacks a filesystem image that could be crafted. appjail runs
each in a [helper jail](../isolation/index.md#helper-jails) built for that step alone, and checks the result on its own
side, without running anything from it.

## Why it matters

A downloader parses responses from the network; an unpacker parses an archive format; both are programs with bugs, and
both run before any check on the content has been possible. A download tool running with your full access could be made
to write anywhere you can; an extractor could be made to write outside its target directory, fill the disk, or create
device files and set-uid programs. And when `unsquashfs` is missing, the only extractor available is the AppImage's own
runtime: code from the download.

## How appjail uses it

### The download jail

The downloader is a small Python program (`fetcher.py`) run by the system's `/usr/bin/python3 -I` inside a jail that has a
network and almost nothing else: the read-only system, the CA certificates, the downloader itself (read-only) and one
empty staging directory, the only writable place. The jail's root is read-only, every namespace is private, no
capability is held, the environment is cleared.

The network comes from **pasta** (package `passt`), which gives the jail a private network namespace with ordinary
outbound connections: the internet is reachable, the services on your own machine's loopback and addresses are not,
nothing can connect in, and name resolution goes through a forwarder address. Without `pasta` the download jails use the
host network instead, with a warning on every command that does so; installing `passt` is recommended for that reason.

What the downloader may do is decided by appjail, never by the server:

| Download | Allowed |
|---|---|
| a GitHub release asset, a pinned tool | https only, to `github.com` and `*.githubusercontent.com`; an asset stops at the size GitHub announced |
| an `--url` app, or a catalog (the built-in one included) | an https start, redirects to any host; a plain-http step is reported and needs a confirmation unless your `--sha256` matches; a size cap (1 GiB for apps by default, `--max-size`; 16 MiB for catalogs) and an exact `Content-Length` |

An AppImage of any source may be at most 2 GiB. Credentials in URLs are refused everywhere. The small JSON answers of the GitHub API and the attestation bundles are
fetched by appjail itself, as data with size limits: they are parsed, never run, and the bundles are trusted only once
[verified](attestations.md).

### Checks on appjail's side

Back outside the jail, appjail reads the file it received without executing it: the size must be the announced one, the
SHA-256 is computed and must equal GitHub's digest when there is one, and the file must be a
[type 2 AppImage](appimage.md). Any failure deletes the staging directory; nothing is written elsewhere.

### The extraction jail

`unsquashfs` runs with no network at all, a read-only root, the AppImage visible read-only and one work directory
writable. The jail is watched while it runs and killed beyond 4 GiB of disk use, 500,000 entries or 15 minutes; its
output is drained as it arrives, only the first and last 16 KiB are kept, and an output stream beyond 64 MiB also kills
it. The apparent size is checked again afterwards, so sparse files cannot hide a huge tree. The same jail runs the
pinned DwarFS extractor, and the AppImage's own `--appimage-extract` when you accept that fallback.

### Validating the tree

appjail then walks the extracted tree without ever following a symbolic link:

- the root must be a real directory, and only regular files, directories and symbolic links may exist (device files,
  sockets and pipes reject the image);
- set-uid, set-gid and sticky bits are cleared, and directories are made accessible to you so the tree can always be
  deleted;
- `AppRun` must lead, through relative links only, to an executable file inside the tree;
- the whole tree is hashed (paths, types, permissions, contents and link targets) and the digest is recorded.

Extraction goes to a temporary name and is renamed only when everything passed, so a failed image leaves nothing behind
and a hostile one can fill only its work directory.

## Connections

- The jails are built from the same parts as the app jail: [Isolation](../isolation/index.md).
- `pasta` is also what the `network` permission uses for apps: Decision [Network through pasta](../../decisions/desktop/network.md).
- The tree digest is checked before every start: [the filesystem view](../isolation/filesystem.md#the-extracted-tree).
- Decision: [Extract, never mount](../../decisions/isolation/extraction.md).

## Limits

- Without `pasta`, the download jail can reach services on your own machine; it still sees no files of yours and keeps
  only what it downloaded into the staging directory.
- The limits on size and entries refuse unusually large AppImages; they protect the disk, not the content.
- The extractor and the kernel are trusted: a flaw in `unsquashfs` reachable by a crafted image is contained by the
  jail, not prevented.

## References

- passt and pasta, [project site](https://passt.top/).
- [squashfs-tools](https://github.com/plougher/squashfs-tools), which provides `unsquashfs`.
- MITRE, [CWE-22: Path Traversal](https://cwe.mitre.org/data/definitions/22.html) and
  [CWE-59: Link Following](https://cwe.mitre.org/data/definitions/59.html): the classic ways an archive writes outside
  its target.
