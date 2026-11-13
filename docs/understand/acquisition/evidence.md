# Hashes and evidence tiers

*Part of [Acquisition](index.md). Previous: [sources and the resolver](sources.md). Next: [build attestations](attestations.md).*

## What it is

A **cryptographic hash** such as SHA-256 turns a file of any size into a 64-character fingerprint. Changing a single
bit of the file changes the fingerprint completely, and nobody can construct a different file with the same one. A hash
therefore identifies *exactly these bytes*. Recording it is called **pinning**: from then on, any file can be checked
against the pin.

A hash says nothing about *who* made the bytes. That needs evidence from outside the file:

- a **digest published by the host**: GitHub computes the SHA-256 of every release asset when it is uploaded and shows
  it next to the file. A download that matches it is the file the repository's owner uploaded, unchanged on the way;
- a **build attestation**: a signed statement that a file with this hash was built by a given workflow of a given
  repository ([build attestations](attestations.md));
- a **hash you obtained yourself**, for example from the publisher's website;
- nothing: the first copy you see is trusted, and only *changes* after it can be detected. This is **trust on first
  use** (TOFU), the model SSH uses for host keys.

## Why it matters

Pinning closes the gap between the moment you decided to trust a file and every moment after: a file swapped on disk,
on the server or on the way is refused. But a pin is only as good as the first download, and different releases come
with very different evidence about it. Treating "the publisher's build system signed this" and "this is what the server
sent the first time" as equal would overstate the weak case; refusing everything but the strong case would refuse
most AppImages.

## How appjail uses it

Every app is pinned by the SHA-256 of its AppImage, and carries an **evidence tier** that records what was verified when
the pin was made:

| Tier | Evidence | Proves |
|---|---|---|
| 1 | a build attestation verified against the downloaded bytes | built by GitHub Actions for this repository, owned by the pinned account |
| 2 | *(reserved: a signature by a pinned GPG key; not implemented)* | |
| 3 | GitHub's per-asset digest matched the download | the file the repository's owner uploaded, unchanged |
| 4 | a GitHub asset without a digest, anchored by the pinned owner account; or a URL or file whose hash you gave with `--sha256` | the first copy, from the same account; or the copy whose hash you obtained elsewhere |
| 5 | a URL or file, nothing else | the first copy |

How the pin is used afterwards:

- **Before every start**, the stored AppImage must hash to the pin, and the extracted tree must match the digest
  recorded after extraction. Otherwise the app is refused, or the tree is extracted again from the verified image.
- **On every update**, the candidate's evidence is compared with the installed tier. A lower tier blocks the update,
  with no option to override it: a release that suddenly lacks the digest or the attestation its predecessors had is a
  classic sign of a compromised publisher.
- **For tier 4 GitHub apps**, where no digest identifies a candidate, `update` downloads it once when first seen, only
  to hash it, and refuses to install it at the end of the quarantine unless it still hashes the same.
- **For URL and file apps**, `update APP --sha256 HEX` raises a tier 5 app to tier 4 when the hash matches; a tier 4 app
  stays tier 4 only if every new version comes with a matching hash.

`appjail list` shows each app's tier.

## Connections

- The owner account that anchors tier 4 is pinned by the [resolver](sources.md).
- Tier 1 comes from [build attestations](attestations.md).
- The quarantine gives the rest of the world time to notice a bad release, whatever its tier.
- Decisions: [Evidence tiers, without a GPG tier](../../decisions/acquisition/evidence-tiers.md),
  [Owner changes and weaker evidence block](../../decisions/updates/blocks.md).

## Limits

- Tiers 3 to 5 prove "unchanged", and for GitHub "from the same account"; they do not prove "safe". Containment is what
  limits a publisher who ships something harmful.
- GitHub has published digests only since June 2025; older releases have none and are tier 4.
- A tier 4 asset replaced in place without a new publication time is detected only through the hash download during
  the quarantine; if you decline that download, it is not.

## References

- NIST, [FIPS 180-4, Secure Hash Standard](https://csrc.nist.gov/pubs/fips/180-4/upd1/final) (SHA-256).
- GitHub Changelog, [Releases now expose digests for release assets](https://github.blog/changelog/2025-06-03-releases-now-expose-digests-for-release-assets/),
  June 2025.
- Wikipedia, [Trust on first use](https://en.wikipedia.org/wiki/Trust_on_first_use).
- SLSA, [Supply chain threats](https://slsa.dev/spec/v1.0/threats-overview): where in the chain each kind of evidence
  helps.
