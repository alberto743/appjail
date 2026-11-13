# Evidence tiers, without a GPG tier

*Decision on [acquisition](index.md).*

**Context.** A hash proves that bytes are unchanged; it says nothing about who produced them. Different releases come
with different evidence: a build attestation, a digest published by GitHub, a hash given on a web page, or nothing.
Treating them alike either overstates weak evidence or refuses most apps.

**Decision.** Every app records an *evidence tier*: 1 for a verified build attestation, 3 for GitHub's per-asset
digest matching the download, 4 for trust on first use (a GitHub asset without a digest, anchored by the pinned owner
account; or a file or URL whose hash the user gave with `--sha256`), 5 for the bytes alone. An update that would lower
the tier is blocked. Tier 2 is reserved for signatures by a pinned GPG key and is not implemented.

**Why no GPG tier.** A signature proves a key, not its owner, so the first `add` would still trust the key's
fingerprint on first use. It would need a per-app fingerprint pin, a jailed `gpgv`, update rules (a new key blocks, a
missing signature is a downgrade) and a place to find the signature file. Attestations cover the projects that build
on GitHub, and the quarantine hash covers those that do not.

**Consequences.** Most AppImages reach tier 3 or 4, which proves "unchanged, from the same account", not "safe".
Containment is what limits the rest.

**Revisit when** a wanted app signs its releases with GPG and has no GitHub attestation.
