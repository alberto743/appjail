# URL apps are checked by sampling

*Decision on [updates](index.md).*

**Context.** An app added with `--url` has no release metadata: the only way to know whether it changed is to look at
the file. Downloading hundreds of megabytes at every check is wasteful, and most servers support conditional and ranged
requests.

**Decision.** `update` tries the cheapest test first, and each step either ends the check or leads to the next: a
conditional request for the first bytes with the stored `ETag` and `Last-Modified` (`304` means unchanged); then ranged
requests for fixed windows (the filesystem's superblock, the middle and the end, about 130 KB), hashed together and
compared, with the size, to the fingerprint recorded at install. Anything different, or a server that does not answer
ranges, means one full download in the jail, after asking. A changed file is a candidate keyed by its hash and goes
through the quarantine; the candidate is kept on disk and installed from there, after a last conditional request
confirms the server still serves it. `--verify` forces a full download and comparison.

**Consequences.** The fingerprint detects a new version; it is not an integrity check. A change confined to bytes it
does not sample, with the same size and validators, is seen only by a full download. A tier 4 URL app (added with a
hash) stays tier 4 only when `update` is given the new hash with `--sha256`; otherwise a changed file is blocked.
