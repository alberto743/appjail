# Attestations verified with a pinned `gh`

*Decision on [acquisition](index.md).*

**Context.** GitHub artifact attestations are Sigstore bundles that bind a file's digest to the workflow run that built
it. Verifying one means checking a certificate chain, a transparency-log entry and the signature, against Sigstore's
trusted root. There is no verifier in Python's standard library, and appjail adds no Python dependencies.

**Options.** Implement Sigstore verification in appjail; depend on a Python library; use the GitHub CLI's verifier.

**Decision.** The GitHub CLI (`gh attestation verify --bundle`), installed only when the user asks
(`appjail tools install gh`), pinned in appjail's source by URL, size and hash, and re-hashed before every use. appjail
fetches the bundles itself (bounded in size, decoded by a small Snappy decoder), so no token is handed to `gh`, and runs
`gh` in a jail that has a network and sees only the file, the bundles and a scratch directory. It then reads the
certificate again: the issuer must be GitHub Actions, the source repository must be the app's, and the owner's account
id must be the pinned one. Verification runs on the downloaded bytes, after the download, so tier 1 does not depend on
GitHub publishing a digest.

**Consequences.** Without `gh`, an attestation is reported as "present, cannot be verified" and the tier stays 3 or 4.
A failed verification never aborts an `add`, but for an app at tier 1 it blocks the update. The identity verified is
the repository and its owner, not a particular workflow or branch: a compromised repository can still produce a
tier 1 release, which is what the quarantine is for.

## Facts about the GitHub API this rests on

- Release assets have a `digest` field, `sha256:<64 hex>` or null; older releases lack it, hence tier 4.
- Listing attestations by user or organisation needs a token; the repository-scoped
  `GET /repos/{owner}/{repo}/attestations/{digest}` works without one and returns bundles behind short-lived signed
  storage URLs. Existence alone is not proof: the bundle is verified.
- Without a token the limit is 60 requests an hour per address (`GET /rate_limit` is free). One `add` costs 4 requests,
  5 when the asset has a digest; one `update` about 4; one `index update` of the built-in catalog 1.
