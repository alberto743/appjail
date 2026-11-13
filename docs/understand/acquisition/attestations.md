# Build attestations

*Part of [Acquisition](index.md). Previous: [hashes and evidence tiers](evidence.md). Next: [jailed download and extraction](jailed-steps.md).*

## What it is

A **build attestation** is a signed statement about how a file was made: "the file with this SHA-256 was built by this
workflow, in this repository, from this commit". GitHub produces them for projects that ask for it in their build
workflow (`actions/attest-build-provenance`), using **Sigstore**:

- the workflow proves its identity to Sigstore's certificate authority (Fulcio) with a short-lived token from GitHub
  Actions, and receives a certificate valid for a few minutes that names the repository, the workflow and the account
  that owns them;
- it signs the statement with that certificate, and the signature is recorded in a public, append-only transparency log
  (Rekor), so it cannot be made quietly afterwards;
- the bundle (statement, signature, certificate, log entry) is stored by GitHub and can be listed by the file's digest.

The statement follows the SLSA provenance format. Verifying it means checking the certificate chain up to Sigstore's
root, the signature, the log entry, that the statement names the file's digest, and that the certificate's identity is
the one expected.

## Why it matters

A digest proves the file is what the repository's owner uploaded. An attestation proves more: that it came out of the
repository's own build system rather than from someone's laptop. A file uploaded by hand, even with the owner's
credentials, has no valid attestation; producing one requires running a workflow in the repository. It is the strongest
evidence a GitHub release can carry.

## How appjail uses it

- **Optional tool.** Verification uses the GitHub CLI (`gh attestation verify --bundle`), installed only when you run
  `appjail tools install gh`. It is pinned by URL, size and hash in appjail's source and re-hashed before every use.
  Without it, an attestation is reported as "present, cannot be verified" and the tier stays 3 or 4.
- **appjail fetches the bundles itself.** It lists them through the API by the file's digest, downloads each from the
  short-lived storage address GitHub gives (https only, at most 1 MiB, no credentials) and decompresses it with a small,
  bounded decoder. Nothing from a bundle is trusted before verification.
- **`gh` runs in a jail** with a network (it fetches Sigstore's trusted root) that sees only the downloaded file, the
  bundles and a scratch directory. No GitHub token is passed to it.
- **appjail re-reads the certificate** after `gh` succeeds: the issuer must be GitHub Actions, the source repository must
  be the app's repository, and the repository owner's account id must equal the pinned `owner_id`.
- **After the download, on the real bytes.** Tier 1 does not depend on GitHub publishing a digest. A failed verification
  never aborts an `add` (the app gets tier 3 or 4, with the reason), but an app already at tier 1 does not accept an
  update without an attestation that verifies.

## Connections

- The tier this earns, and how it is protected on updates: [hashes and evidence tiers](evidence.md).
- The pinned `gh` is one of two helper tools: Decision [Helper tools pinned in the source](../../decisions/acquisition/pinned-tools.md).
- Decision: [Attestations verified with a pinned `gh`](../../decisions/acquisition/attestations.md).

## Limits

- The identity checked is the repository and its owner, not a particular workflow file or branch. Someone who can push
  to the repository can produce a tier 1 release; the quarantine is what gives others time to notice.
- An attestation proves where a file was built, not that the source code was benign.
- Only releases whose publishers set up attestations in their build workflow can reach tier 1.

## References

- GitHub Docs, [Artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations) and
  [Using artifact attestations to establish provenance for builds](https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds).
- GitHub CLI manual, [gh attestation verify](https://cli.github.com/manual/gh_attestation_verify).
- Sigstore, [Overview](https://docs.sigstore.dev/about/overview/): Fulcio, Rekor and keyless signing.
- SLSA, [Provenance](https://slsa.dev/spec/v1.0/provenance).
- Google, [Snappy format description](https://github.com/google/snappy/blob/main/format_description.txt): the
  compression of the bundles as GitHub stores them.
