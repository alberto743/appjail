# URL and file apps

*Part of [Updates](index.md). Previous: [what blocks an update](blocks.md). Next: [history and rollback](history.md).*

## What it is

An app added with `--url` has a download address and nothing else: no releases, no publisher digest. An app added with
`--file` has not even that. HTTP offers two tools to learn whether a file changed without downloading it:
**conditional requests** (the server answers `304 Not Modified` when the file still matches the `ETag` or
`Last-Modified` it gave before) and **range requests** (the server sends only the bytes asked for, with `206 Partial
Content`).

## Why it matters

An AppImage is often hundreds of megabytes. Downloading it at every check is wasteful; trusting the server's validators
alone is weak, since a server can serve new bytes with old headers. And a file app's update must not cost the private
home that `remove` and `add` would delete.

## How appjail uses it

- **URL apps, cheapest test first.** Each step ends the check or leads to the next: a conditional request for the first
  bytes with the stored validators (`304` means unchanged, and the response also gives the size); then range requests
  for fixed windows (the filesystem's superblock, the middle and the end, about 130 KB), hashed together and compared,
  with the size, to the fingerprint recorded at install. The first window alone would be useless, since every AppImage
  with the same runtime begins alike. Any difference, or a server without range support, means one full download in
  the jail, after asking.
- **A changed file is a candidate**, keyed by its hash, and goes through the quarantine. It is kept on disk meanwhile;
  at the end, a conditional request confirms the server still serves it, and the stored copy is installed without a
  second download. `--verify` forces a full download and comparison.
- **File apps.** `update APP --file PATH` replaces the image: the hash difference, a confirmation, extraction in the
  jail, rollback on failure. There is no quarantine: you hold the bytes.
- **Evidence.** A tier 5 app given a matching `--sha256` becomes tier 4; a tier 4 app stays tier 4 only when each new
  version comes with its hash.

## Connections

- The quarantine and the blocks are the same as for GitHub apps: [channels and quarantine](quarantine.md),
  [what blocks an update](blocks.md).
- Decision: [URL apps are checked by sampling](../../decisions/updates/url-check.md).

## Limits

- The fingerprint detects a new version; it is not an integrity check. A change confined to bytes it does not sample,
  with the same size and validators, is seen only by a full download.

## References

- IETF, [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html), sections on conditional and
  [range requests](https://www.rfc-editor.org/rfc/rfc9110.html#name-range-requests).
- MDN, [Conditional requests](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Conditional_requests) and
  [Range requests](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Range_requests).
